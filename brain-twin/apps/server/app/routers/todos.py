"""『やること』として使える一覧(ユーザー要望による追加機能)。

新しい分類ロジックは持たず、既存のAI出力(thoughts.types に含まれる
'action_candidate'、または action_intent の推定値)をそのまま流用する。
Brain Twinの設計思想(入力時に整理を強制しない)通り、ユーザーが明示的に
『todo』として入力する専用の型は用意しない。あくまでAIが行動候補として
拾った思考のうち、未完了(done_at IS NULL)のものを並べるだけの軽いビュー。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.db import get_db
from app.models import SyncDevice, Thought
from app.schemas import ThoughtListResponse
from app.serializers import load_thought_entities_batch, thought_to_out

router = APIRouter(tags=["todos"])

_ACTION_INTENT_THRESHOLD = 0.5


def _is_actionable(thought: Thought) -> bool:
    types = thought.types_json or []
    if "action_candidate" in types:
        return True
    return thought.action_intent is not None and thought.action_intent >= _ACTION_INTENT_THRESHOLD


def _earliest_resolved_date(thought: Thought) -> str | None:
    dates = [d.get("resolved_date") for d in (thought.possible_dates_json or []) if d.get("resolved_date")]
    return min(dates) if dates else None


def _sort_key(thought: Thought) -> tuple:
    earliest = _earliest_resolved_date(thought)
    # 期限のあるものを先に(昇順)、無いものは末尾へ。同条件ならurgencyが高い順、
    # さらに同条件なら新しいものを先に。
    return (
        0 if earliest is not None else 1,
        earliest or "",
        -(thought.urgency if thought.urgency is not None else -1.0),
        -thought.created_at.timestamp(),
    )


@router.get("/api/todos", response_model=ThoughtListResponse)
async def list_todos(
    include_done: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> ThoughtListResponse:
    query = select(Thought).where(Thought.deleted_at.is_(None))
    if not include_done:
        query = query.where(Thought.done_at.is_(None))

    result = await db.execute(query)
    rows = [t for t in result.scalars().all() if _is_actionable(t)]
    rows.sort(key=_sort_key)
    rows = rows[:limit]

    entities_by_thought = await load_thought_entities_batch(db, [t.id for t in rows])
    items = [thought_to_out(t, entities_by_thought.get(t.id, [])) for t in rows]
    return ThoughtListResponse(items=items)
