"""thought一覧・詳細・フィードバック(仕様書19)。
フィードバックは feedback_events への追記(履歴)であり、上書きしない。
一部のイベント種別だけ、ユーザーの明確な意思表示として対応するthoughtの
属性(推定値)を書き換える(例: marked_important -> importance=1.0)。
他の種別は履歴としてのみ記録し、属性は変えない(仕様が明確な範囲のみ実装する)。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.db import get_db
from app.models import FeedbackEvent, SyncDevice, Thought
from app.schemas import FeedbackCreate, FeedbackEventOut, ThoughtListResponse, ThoughtOut
from app.serializers import iso, load_thought_entities, load_thought_entities_batch, thought_to_out
from app.utils.uuids import new_id

router = APIRouter(tags=["thoughts"])

# marked_important: 「これは大事」という明確な意思表示 -> importanceを最大へ。
# marked_ok_to_forget: 「もう忘れていい」という意思表示 -> forget_safely_scoreを最大へ。
# marked_want_to_act: 「やる」という意思表示 -> action_intentを最大へ。
# marked_just_a_thought: 「ただ浮かんだだけ」という意思表示 -> action_intentを最小へ。
_ATTRIBUTE_EFFECTS: dict[str, tuple[str, float]] = {
    "marked_important": ("importance", 1.0),
    "marked_ok_to_forget": ("forget_safely_score", 1.0),
    "marked_want_to_act": ("action_intent", 1.0),
    "marked_just_a_thought": ("action_intent", 0.0),
}


@router.get("/api/thoughts", response_model=ThoughtListResponse)
async def list_thoughts(
    capture_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> ThoughtListResponse:
    query = select(Thought).where(Thought.deleted_at.is_(None))
    if capture_id:
        query = query.where(Thought.capture_id == capture_id)
    query = query.order_by(Thought.created_at.desc()).limit(limit)

    result = await db.execute(query)
    rows = list(result.scalars().all())
    entities_by_thought = await load_thought_entities_batch(db, [t.id for t in rows])
    items = [thought_to_out(t, entities_by_thought.get(t.id, [])) for t in rows]
    return ThoughtListResponse(items=items)


@router.get("/api/thoughts/{thought_id}", response_model=ThoughtOut)
async def get_thought(
    thought_id: str,
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> ThoughtOut:
    result = await db.execute(select(Thought).where(Thought.id == thought_id))
    thought = result.scalar_one_or_none()
    if thought is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見つかりませんでした")
    entities = await load_thought_entities(db, thought_id)
    return thought_to_out(thought, entities)


@router.post("/api/thoughts/{thought_id}/feedback", response_model=FeedbackEventOut, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    thought_id: str,
    body: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> FeedbackEventOut:
    result = await db.execute(select(Thought).where(Thought.id == thought_id))
    thought = result.scalar_one_or_none()
    if thought is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見つかりませんでした")

    now = datetime.now(timezone.utc)
    event = FeedbackEvent(
        id=new_id(),
        thought_id=thought_id,
        capture_id=thought.capture_id,
        event_type=body.event_type,
        event_value=body.event_value,
        context_json=body.context_json,
        created_at=now,
    )
    db.add(event)

    effect = _ATTRIBUTE_EFFECTS.get(body.event_type)
    if effect is not None:
        attr, value = effect
        setattr(thought, attr, value)
        thought.updated_at = now

    await db.commit()

    return FeedbackEventOut(
        id=event.id,
        thought_id=event.thought_id,
        capture_id=event.capture_id,
        event_type=event.event_type,
        event_value=event.event_value,
        created_at=iso(event.created_at),
    )
