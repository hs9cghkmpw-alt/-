from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.db import get_db
from app.jobs.queue import enqueue_thought_split_job
from app.models import Capture, SyncDevice, Thought
from app.schemas import (
    SyncCaptureResult,
    SyncCapturesRequest,
    SyncCapturesResponse,
    SyncChangesResponse,
)
from app.serializers import capture_to_out, iso, thought_to_out
from app.utils.time import now_iso, parse_iso
from app.utils.uuids import is_valid_uuid, new_id

router = APIRouter(tags=["sync"])


@router.post("/api/sync/captures", response_model=SyncCapturesResponse)
async def sync_captures(
    body: SyncCapturesRequest,
    db: AsyncSession = Depends(get_db),
    device: SyncDevice = Depends(get_current_device),
) -> SyncCapturesResponse:
    """
    仕様書10「冪等な同期API」。同じclient_idが複数回送られても1回分としてしか保存しない。
    PC停止中にiPhoneが溜めたオフラインキューを再接続時にまとめて送る想定(最大200件/回)。
    """
    now = datetime.now(timezone.utc)
    results: list[SyncCaptureResult] = []

    for item in body.captures:
        if not is_valid_uuid(item.client_id):
            # 不正なclient_idは静かにスキップする(仕様書9: エラーを強く表示しない)。
            continue

        existing = await db.execute(select(Capture).where(Capture.client_id == item.client_id))
        existing_capture = existing.scalar_one_or_none()
        if existing_capture is not None:
            results.append(SyncCaptureResult(client_id=item.client_id, status="already_exists", capture=capture_to_out(existing_capture)))
            continue

        try:
            captured_at = parse_iso(item.captured_at)
        except ValueError:
            captured_at = now

        capture = Capture(
            id=new_id(),
            client_id=item.client_id,
            raw_text=item.raw_text,
            input_type=item.input_type,
            captured_at=captured_at,
            received_at=now,
            sync_status="synced",
            processing_status="not_started",
            source_device=item.source_device or device.device_name,
            client_version=item.client_version,
            created_at=now,
            updated_at=now,
        )
        db.add(capture)
        await db.flush()
        await enqueue_thought_split_job(db, capture)

        results.append(SyncCaptureResult(client_id=item.client_id, status="created", capture=capture_to_out(capture)))

    device.last_seen_at = now
    await db.commit()
    return SyncCapturesResponse(results=results)


@router.get("/api/sync/changes", response_model=SyncChangesResponse)
async def sync_changes(
    since: str | None = Query(default=None, description="ISO8601。省略時は全件(初回同期)。"),
    limit: int = Query(default=200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    device: SyncDevice = Depends(get_current_device),
) -> SyncChangesResponse:
    """
    PC復帰時にiPhoneが『前回同期以降に変わったもの』(AIが整理し終えたthoughts等)を
    取得するための増分同期。sinceを渡さなければ全件を返す(初回ペアリング直後など)。
    """
    since_dt = parse_iso(since) if since else datetime.fromtimestamp(0, tz=timezone.utc)

    captures_result = await db.execute(
        select(Capture).where(Capture.updated_at > since_dt).order_by(Capture.updated_at.asc()).limit(limit)
    )
    captures = list(captures_result.scalars().all())

    thoughts_result = await db.execute(
        select(Thought).where(Thought.updated_at > since_dt).order_by(Thought.updated_at.asc()).limit(limit)
    )
    thoughts = list(thoughts_result.scalars().all())

    all_ts = [c.updated_at for c in captures] + [t.updated_at for t in thoughts]
    next_cursor = iso(max(all_ts)) if all_ts else (since or now_iso())

    device.last_seen_at = datetime.now(timezone.utc)
    await db.commit()

    return SyncChangesResponse(
        server_time=now_iso(),
        captures=[capture_to_out(c) for c in captures],
        thoughts=[thought_to_out(t) for t in thoughts],
        next_cursor=next_cursor,
    )
