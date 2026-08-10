from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Capture, Entity, Thought, ThoughtEntity
from app.schemas import CaptureOut, ThoughtEntityOut, ThoughtOut


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def capture_to_out(c: Capture) -> CaptureOut:
    return CaptureOut(
        id=c.id,
        client_id=c.client_id,
        raw_text=c.raw_text,
        input_type=c.input_type,
        captured_at=iso(c.captured_at),
        received_at=iso(c.received_at),
        sync_status=c.sync_status,
        processing_status=c.processing_status,
        source_device=c.source_device,
        client_version=c.client_version,
        created_at=iso(c.created_at),
        updated_at=iso(c.updated_at),
        deleted_at=iso(c.deleted_at),
    )


def thought_to_out(t: Thought, entities: list[ThoughtEntityOut] | None = None) -> ThoughtOut:
    return ThoughtOut(
        id=t.id,
        capture_id=t.capture_id,
        content=t.content,
        summary=t.summary,
        types=list(t.types_json or []),
        action_intent=t.action_intent,
        resurface_need=t.resurface_need,
        emotional_weight=t.emotional_weight,
        sentiment=t.sentiment,
        user_notes=t.user_notes,
        certainty=t.certainty,
        importance=t.importance,
        urgency=t.urgency,
        mental_load=t.mental_load,
        forget_safely_score=t.forget_safely_score,
        entities=entities or [],
        possible_dates=list(t.possible_dates_json or []),
        project_names=list(t.project_names_json or []),
        people=list(t.people_json or []),
        places=list(t.places_json or []),
        ai_model=t.ai_model,
        ai_prompt_version=t.ai_prompt_version,
        analysis_version=t.analysis_version,
        created_at=iso(t.created_at),
        updated_at=iso(t.updated_at),
    )


async def load_thought_entities(db: AsyncSession, thought_id: str) -> list[ThoughtEntityOut]:
    result = await db.execute(
        select(Entity, ThoughtEntity.confidence)
        .join(ThoughtEntity, ThoughtEntity.entity_id == Entity.id)
        .where(ThoughtEntity.thought_id == thought_id)
    )
    return [
        ThoughtEntityOut(name=entity.display_name, entity_type=entity.entity_type, confidence=confidence)
        for entity, confidence in result.all()
    ]


async def load_thought_entities_batch(db: AsyncSession, thought_ids: list[str]) -> dict[str, list[ThoughtEntityOut]]:
    """複数thoughtのentitiesを1クエリでまとめて取得する(N+1クエリを避けるため)。
    戻り値は thought_id -> entities のdict。該当が無いthought_idはキー自体が
    存在しない(呼び出し側で `.get(id, [])` を使うこと)。"""
    if not thought_ids:
        return {}
    result = await db.execute(
        select(ThoughtEntity.thought_id, Entity, ThoughtEntity.confidence)
        .join(Entity, ThoughtEntity.entity_id == Entity.id)
        .where(ThoughtEntity.thought_id.in_(thought_ids))
    )
    by_thought: dict[str, list[ThoughtEntityOut]] = {}
    for tid, entity, confidence in result.all():
        by_thought.setdefault(tid, []).append(
            ThoughtEntityOut(name=entity.display_name, entity_type=entity.entity_type, confidence=confidence)
        )
    return by_thought
