"""
仕様書12「AI処理設計」のパイプライン本体。

capture保存 -> 正規化 -> 機密情報検出 -> 思考分割 -> 属性抽出 -> エンティティ抽出
-> 日付候補抽出 -> 類似思考検索 -> リンク候補生成 -> データベース保存

このモジュールはSQLAlchemy/FastAPIに依存するため、このリポジトリの開発サンドボックス
(外部ネットワーク不可)では直接実行できない。ロジックの大半(JSON検証/日付抽出/
リンクスコアリング/埋め込み類似度)は app/core/ 配下の依存フリーな関数に切り出し済みで、
そちらは apps/server/tests/test_core_*.py で実際に検証されている。
このファイルはそれらを「DBへどう保存するか」の配線を担当する薄い層。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ollama_client import OllamaClient, OllamaModelMissingError, OllamaUnavailableError
from app.ai.prompt_loader import render_thought_split_prompt, load_thought_split_schema
from app.config import get_settings
from app.core import dates_ja, job_policy, pii
from app.core.embeddings import cosine_similarity
from app.core.json_repair import ParseResult, parse_and_validate_thought_split
from app.core.linking import ThoughtForLinking, suggest_links
from app.models import (
    Capture,
    Entity,
    ProcessingJob,
    Thought,
    ThoughtEmbedding,
    ThoughtEntity,
    ThoughtLink,
)
from app.utils.time import now_iso, parse_iso
from app.utils.uuids import new_id

logger = logging.getLogger("brain_twin.pipeline")
settings = get_settings()

ANALYSIS_VERSION = "v1"
SEMANTIC_LINK_THRESHOLD = 0.82
SEMANTIC_CANDIDATE_LIMIT = 300  # 直近N件のみ類似度計算対象にする(個人利用規模なら十分)


@dataclass
class PipelineOutcome:
    ok: bool
    reason: str = ""
    thought_ids: list[str] = field(default_factory=list)
    unavailable: bool = False  # Ollama自体に到達できない(モデル云々ではなく起動していない)


def _normalize_text(raw_text: str) -> str:
    """軽い正規化のみ。原文の意味を変えるような加工はしない
    (前後の空白除去、行末の余分な空白除去程度)。"""
    lines = [line.rstrip() for line in raw_text.split("\n")]
    return "\n".join(lines).strip()


async def _ensure_entity(db: AsyncSession, entity_type: str, name: str) -> Entity | None:
    name = name.strip()
    if not name:
        return None
    canonical = name  # v1では正規化は行わず表記そのものをcanonicalとする(将来: 表記ゆれ統合)
    result = await db.execute(
        select(Entity).where(Entity.entity_type == entity_type, Entity.canonical_name == canonical)
    )
    entity = result.scalar_one_or_none()
    if entity is None:
        entity = Entity(
            id=new_id(),
            entity_type=entity_type,
            canonical_name=canonical,
            display_name=name,
            aliases_json=[],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(entity)
        await db.flush()
    return entity


async def _persist_thought(db: AsyncSession, capture: Capture, item: dict, *, ai_model: str, prompt_version: str) -> Thought:
    now = datetime.now(timezone.utc)

    # AIが見つけた日付候補と、ルールベースの候補をマージする(重複するraw_textは1つに)。
    ai_dates = list(item.get("possible_dates") or [])
    ai_raw_texts = {d.get("raw_text") for d in ai_dates}
    captured_dt = capture.captured_at if capture.captured_at.tzinfo else capture.captured_at.replace(tzinfo=timezone.utc)
    for cand in dates_ja.extract_date_candidates(item["content"], captured_dt):
        if cand.raw_text not in ai_raw_texts:
            ai_dates.append(
                {"raw_text": cand.raw_text, "resolved_date": cand.resolved_date, "precision": cand.precision}
            )

    thought = Thought(
        id=new_id(),
        capture_id=capture.id,
        content=item["content"],
        summary=item.get("summary"),
        types_json=item.get("types", []),
        action_intent=item.get("action_intent"),
        resurface_need=item.get("resurface_need"),
        emotional_weight=item.get("emotional_weight"),
        sentiment=item.get("sentiment"),
        certainty=item.get("certainty"),
        importance=item.get("importance"),
        urgency=item.get("urgency"),
        mental_load=item.get("mental_load"),
        forget_safely_score=item.get("forget_safely_score"),
        possible_dates_json=ai_dates,
        project_names_json=item.get("project_names", []),
        people_json=item.get("people", []),
        places_json=item.get("places", []),
        ai_model=ai_model,
        ai_prompt_version=prompt_version,
        analysis_version=ANALYSIS_VERSION,
        created_at=now,
        updated_at=now,
    )
    db.add(thought)
    await db.flush()

    for ent in item.get("entities", []):
        entity_row = await _ensure_entity(db, ent.get("entity_type", "other"), ent.get("name", ""))
        if entity_row is not None:
            db.add(ThoughtEntity(thought_id=thought.id, entity_id=entity_row.id, confidence=None, created_by="ai"))
    for name in item.get("people", []):
        entity_row = await _ensure_entity(db, "person", name)
        if entity_row is not None:
            db.add(ThoughtEntity(thought_id=thought.id, entity_id=entity_row.id, confidence=None, created_by="ai"))
    for name in item.get("places", []):
        entity_row = await _ensure_entity(db, "place", name)
        if entity_row is not None:
            db.add(ThoughtEntity(thought_id=thought.id, entity_id=entity_row.id, confidence=None, created_by="ai"))
    for name in item.get("project_names", []):
        entity_row = await _ensure_entity(db, "project", name)
        if entity_row is not None:
            db.add(ThoughtEntity(thought_id=thought.id, entity_id=entity_row.id, confidence=None, created_by="ai"))

    return thought


async def _generate_links_for_thought(db: AsyncSession, thought: Thought, ollama: OllamaClient, ollama_available: bool) -> None:
    # ルールベースのリンク候補 (同一capture内共起 / 同一プロジェクト / 同一人物 / 表層類似 / 時間的近さ)
    recent_result = await db.execute(
        select(Thought)
        .where(Thought.deleted_at.is_(None), Thought.id != thought.id)
        .order_by(Thought.created_at.desc())
        .limit(SEMANTIC_CANDIDATE_LIMIT)
    )
    recent_thoughts = recent_result.scalars().all()

    candidates = [
        ThoughtForLinking(
            id=t.id,
            content=t.content,
            people=list(t.people_json or []),
            places=list(t.places_json or []),
            project_names=list(t.project_names_json or []),
            created_at=t.created_at if t.created_at.tzinfo else t.created_at.replace(tzinfo=timezone.utc),
            capture_id=t.capture_id,
        )
        for t in recent_thoughts
    ]
    target = ThoughtForLinking(
        id=thought.id,
        content=thought.content,
        people=list(thought.people_json or []),
        places=list(thought.places_json or []),
        project_names=list(thought.project_names_json or []),
        created_at=thought.created_at if thought.created_at.tzinfo else thought.created_at.replace(tzinfo=timezone.utc),
        capture_id=thought.capture_id,
    )

    suggestions = suggest_links(target, candidates)
    now = datetime.now(timezone.utc)
    for cand_id, suggestion in suggestions:
        db.add(
            ThoughtLink(
                id=new_id(),
                source_thought_id=thought.id,
                target_thought_id=cand_id,
                relation_type=suggestion.relation_type,
                score=suggestion.score,
                reason=suggestion.reason,
                created_by="rule",
                created_at=now,
            )
        )

    # 意味的類似度 (Ollama埋め込みが使える場合のみ。使えなくても他のリンクは既に生成済み)
    if not ollama_available:
        return
    try:
        vector = await ollama.generate_embedding(thought.content)
    except Exception:  # noqa: BLE001 - 埋め込みはベストエフォート。失敗しても全体は止めない
        vector = None
    if not vector:
        return

    db.add(
        ThoughtEmbedding(
            thought_id=thought.id,
            model=settings.ollama_embedding_model,
            dim=len(vector),
            vector_json=vector,
            created_at=now,
        )
    )

    existing_embeddings = await db.execute(select(ThoughtEmbedding).where(ThoughtEmbedding.thought_id != thought.id))
    for row in existing_embeddings.scalars().all():
        score = cosine_similarity(vector, list(row.vector_json))
        if score >= SEMANTIC_LINK_THRESHOLD:
            db.add(
                ThoughtLink(
                    id=new_id(),
                    source_thought_id=thought.id,
                    target_thought_id=row.thought_id,
                    relation_type="semantic_similarity",
                    score=score,
                    reason="埋め込みベクトルの類似度",
                    created_by="ai",
                    created_at=now,
                )
            )


async def process_capture(capture_id: str, db: AsyncSession, ollama: OllamaClient | None = None) -> PipelineOutcome:
    ollama = ollama or OllamaClient()

    result = await db.execute(select(Capture).where(Capture.id == capture_id))
    capture = result.scalar_one_or_none()
    if capture is None:
        return PipelineOutcome(ok=False, reason="capture not found")

    normalized = _normalize_text(capture.raw_text)
    has_pii = pii.has_sensitive_content(normalized)
    if has_pii:
        # 本文はそのまま処理する(仕様書3-11: AIは原文を上書きしない)。
        # ログにだけ内容を出さないようにする。
        logger.info("capture %s: 機密情報らしき内容を検出したためログには内容を出力しません", capture.id)
    else:
        logger.debug("capture %s: processing", capture.id)

    healthy = await ollama.check_health()
    if not healthy:
        return PipelineOutcome(ok=False, reason="Ollamaに接続できません", unavailable=True)

    system_prompt, prompt_version = render_thought_split_prompt(
        capture_text=normalized,
        captured_at_iso=now_iso() if capture.captured_at is None else _safe_iso(capture.captured_at),
    )
    schema = load_thought_split_schema()

    try:
        generation = await ollama.generate_json(
            system_prompt=system_prompt,
            user_prompt=normalized,
            json_schema=schema,
        )
    except OllamaModelMissingError as e:
        return PipelineOutcome(ok=False, reason=str(e), unavailable=True)
    except OllamaUnavailableError as e:
        return PipelineOutcome(ok=False, reason=str(e), unavailable=True)

    parsed: ParseResult = parse_and_validate_thought_split(generation.raw_text)
    if not parsed.ok:
        return PipelineOutcome(ok=False, reason=parsed.error_summary or "AI出力の検証に失敗しました")

    thought_ids: list[str] = []
    for item in parsed.data["thoughts"]:
        thought = await _persist_thought(db, capture, item, ai_model=generation.model, prompt_version=prompt_version)
        thought_ids.append(thought.id)

    await db.flush()

    for tid in thought_ids:
        result2 = await db.execute(select(Thought).where(Thought.id == tid))
        thought_row = result2.scalar_one()
        await _generate_links_for_thought(db, thought_row, ollama, ollama_available=healthy)

    capture.processing_status = "done"
    capture.updated_at = datetime.now(timezone.utc)

    return PipelineOutcome(ok=True, thought_ids=thought_ids)


def _safe_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
