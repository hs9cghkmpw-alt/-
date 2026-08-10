"""設定画面の『詳細な状態』表示(仕様書9・13)を支えるAPI。
静かな状態表示が目的で、Ollamaが落ちていてもエラーにはせず`unknown`/`false`を返す。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.ollama_client import OllamaClient
from app.auth import get_current_device
from app.config import get_settings
from app.db import get_db
from app.models import Capture, ProcessingJob, SyncDevice
from app.schemas import StatusResponse

router = APIRouter(tags=["status"])
settings = get_settings()


@router.get("/api/status", response_model=StatusResponse)
async def get_status(
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> StatusResponse:
    ollama = OllamaClient()
    try:
        ollama_available = await ollama.check_health()
    except Exception:  # noqa: BLE001 - 状態表示自体は絶対に落とさない
        ollama_available = "unknown"

    pending_sync = await db.execute(
        select(func.count()).select_from(Capture).where(Capture.sync_status.in_(["queued", "syncing"]))
    )
    pending_processing = await db.execute(
        select(func.count()).select_from(ProcessingJob).where(ProcessingJob.status.in_(["queued", "processing"]))
    )
    failed_processing = await db.execute(
        select(func.count()).select_from(ProcessingJob).where(ProcessingJob.status == "failed")
    )

    return StatusResponse(
        ollama_available=ollama_available,
        ollama_base_url=settings.ollama_base_url,
        pending_sync_count=pending_sync.scalar_one(),
        pending_processing_count=pending_processing.scalar_one(),
        failed_processing_count=failed_processing.scalar_one(),
    )
