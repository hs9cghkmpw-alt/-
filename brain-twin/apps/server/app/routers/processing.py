"""AI再解析(仕様書7.4「再解析」)。モデル/プロンプトを変えた後などに、
特定のcaptureだけを再度キューへ積み直す。処理自体はバックグラウンドワーカーに
任せるため、ここでは202 Acceptedを返してすぐ制御を戻す。"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.db import get_db
from app.jobs.queue import enqueue_thought_split_job
from app.models import Capture, SyncDevice
from app.schemas import ProcessingRetryResponse

router = APIRouter(tags=["processing"])


@router.post(
    "/api/processing/{capture_id}/retry",
    response_model=ProcessingRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_processing(
    capture_id: str,
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> ProcessingRetryResponse:
    result = await db.execute(select(Capture).where(Capture.id == capture_id))
    capture = result.scalar_one_or_none()
    if capture is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="見つかりませんでした")

    job = await enqueue_thought_split_job(db, capture)
    capture.updated_at = datetime.now(timezone.utc)
    await db.commit()

    return ProcessingRetryResponse(accepted=True, capture_id=capture.id, job_id=job.id)
