from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_device
from app.db import get_db
from app.models import ProcessingJob, SyncDevice
from app.schemas import JobListResponse, JobOut
from app.serializers import iso

router = APIRouter(tags=["jobs"])


@router.get("/api/jobs", response_model=JobListResponse)
async def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _device: SyncDevice = Depends(get_current_device),
) -> JobListResponse:
    """詳細画面の技術的な状態表示 (仕様書9・19) を支えるAPI。"""
    query = select(ProcessingJob)
    if status_filter:
        query = query.where(ProcessingJob.status == status_filter)
    query = query.order_by(ProcessingJob.updated_at.desc()).limit(limit)
    result = await db.execute(query)
    items = [
        JobOut(
            id=j.id,
            capture_id=j.capture_id,
            job_type=j.job_type,
            status=j.status,
            attempt_count=j.attempt_count,
            last_error=j.last_error,
            scheduled_at=iso(j.scheduled_at),
            started_at=iso(j.started_at),
            completed_at=iso(j.completed_at),
        )
        for j in result.scalars().all()
    ]
    return JobListResponse(items=items)
