"""全文検索(仕様書17)。db_schema.sqlのFTS5(trigramトークナイザ)テーブルを直接叩く。
未処理(AI整理待ち)のcaptureもraw_text経由でヒットする(仕様書13: Ollamaが使えなくても
検索自体は機能し続ける)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.db import get_db
from app.models import Capture, SyncDevice, Thought
from app.schemas import CaptureOut, SearchResponse, SearchThoughtHit
from app.serializers import capture_to_out, load_thought_entities_batch, thought_to_out

router = APIRouter(tags=["search"])

# trigramトークナイザは3文字未満のクエリでは実用的にヒットしないため、
# 無駄なフルスキャン的クエリを避ける意味も兼ねてここで足切りする
# (verification/db_schema_check.pyのコメントと合わせている)。
_MIN_QUERY_LENGTH = 3


def _fts_phrase(q: str) -> str:
    """FTS5クエリ構文へのインジェクションを避けるため、常にフレーズとして渡す
    (ダブルクオートはFTS5のフレーズ内エスケープ規則通り二重化する)。"""
    return '"' + q.replace('"', '""') + '"'


@router.get("/api/search", response_model=SearchResponse)
async def search(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> SearchResponse:
    query_text = q.strip()
    if len(query_text) < _MIN_QUERY_LENGTH:
        return SearchResponse(query=query_text, thoughts=[], captures=[])

    phrase = _fts_phrase(query_text)

    thought_rows = await db.execute(
        text("SELECT thought_id FROM thoughts_fts WHERE thoughts_fts MATCH :q ORDER BY rank LIMIT :limit"),
        {"q": phrase, "limit": limit},
    )
    thought_ids = [row[0] for row in thought_rows.all()]

    capture_rows = await db.execute(
        text("SELECT capture_id FROM captures_fts WHERE captures_fts MATCH :q ORDER BY rank LIMIT :limit"),
        {"q": phrase, "limit": limit},
    )
    capture_ids = [row[0] for row in capture_rows.all()]

    thoughts: list[SearchThoughtHit] = []
    if thought_ids:
        result = await db.execute(select(Thought).where(Thought.id.in_(thought_ids), Thought.deleted_at.is_(None)))
        rows = list(result.scalars().all())
        entities_by_thought = await load_thought_entities_batch(db, [t.id for t in rows])
        by_id = {t.id: t for t in rows}
        for tid in thought_ids:
            t = by_id.get(tid)
            if t is not None:
                thoughts.append(
                    SearchThoughtHit(thought=thought_to_out(t, entities_by_thought.get(t.id, [])), capture_id=t.capture_id)
                )

    captures: list[CaptureOut] = []
    if capture_ids:
        result = await db.execute(select(Capture).where(Capture.id.in_(capture_ids), Capture.deleted_at.is_(None)))
        by_id = {c.id: c for c in result.scalars().all()}
        for cid in capture_ids:
            c = by_id.get(cid)
            if c is not None:
                captures.append(capture_to_out(c))

    return SearchResponse(query=query_text, thoughts=thoughts, captures=captures)
