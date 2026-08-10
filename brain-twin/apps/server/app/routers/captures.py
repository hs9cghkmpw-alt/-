"""1件ずつの即時保存API。iPhoneがPCへ到達可能な間はこちらを使い、
オフラインで溜まったキューをまとめて送るときだけ `/api/sync/captures` を使う想定
(仕様書10)。同一client_idでの冪等性は sync.py と同じ扱いにする。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.db import get_db
from app.jobs.queue import enqueue_thought_split_job
from app.models import Capture, SyncDevice
from app.schemas import CaptureCreate, CaptureListResponse, CaptureOut
from app.serializers import capture_to_out
from app.utils.time import parse_iso
from app.utils.uuids import new_id

router = APIRouter(tags=["captures"])


@router.post("/api/captures", response_model=CaptureOut, status_code=status.HTTP_201_CREATED)
async def create_capture(
    body: CaptureCreate,
    db: AsyncSession = Depends(get_db),
    device: SyncDevice = Depends(get_current_device),
) -> CaptureOut:
    existing = await db.execute(select(Capture).where(Capture.client_id == body.client_id))
    existing_capture = existing.scalar_one_or_none()
    if existing_capture is not None:
        device.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
        return capture_to_out(existing_capture)

    now = datetime.now(timezone.utc)
    try:
        captured_at = parse_iso(body.captured_at)
    except ValueError:
        captured_at = now

    capture = Capture(
        id=new_id(),
        client_id=body.client_id,
        raw_text=body.raw_text,
        input_type=body.input_type,
        captured_at=captured_at,
        received_at=now,
        sync_status="synced",
        processing_status="not_started",
        source_device=body.source_device or device.device_name,
        client_version=body.client_version,
        created_at=now,
        updated_at=now,
    )
    db.add(capture)
    await db.flush()
    await enqueue_thought_split_job(db, capture)

    device.last_seen_at = now
    await db.commit()
    return capture_to_out(capture)


@router.get("/api/captures", response_model=CaptureListResponse)
async def list_captures(
    range: str = Query(default="today", pattern="^(today|all)$"),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> CaptureListResponse:
    query = select(Capture).where(Capture.deleted_at.is_(None))
    if range == "today":
        start_of_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(Capture.captured_at >= start_of_today)
    query = query.order_by(Capture.captured_at.desc()).limit(limit)

    result = await db.execute(query)
    items = [capture_to_out(c) for c in result.scalars().all()]
    return CaptureListResponse(items=items)


@router.get("/api/captures/{capture_id}", response_model=CaptureOut)
async def get_capture(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> CaptureOut:
    result = await db.execute(select(Capture).where(Capture.id == capture_id))
    capture = result.scalar_one_or_none()
    if capture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見つかりませんでした")
    return capture_to_out(capture)
