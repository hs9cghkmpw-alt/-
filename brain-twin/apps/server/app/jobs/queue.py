"""processing_jobs テーブルへの薄いアクセス層。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Capture, ProcessingJob
from app.utils.uuids import new_id


async def enqueue_thought_split_job(db: AsyncSession, capture: Capture) -> ProcessingJob:
    now = datetime.now(timezone.utc)
    job = ProcessingJob(
        id=new_id(),
        capture_id=capture.id,
        job_type="thought_split",
        status="queued",
        attempt_count=0,
        scheduled_at=now,
        created_at=now,
        updated_at=now,
    )
    capture.processing_status = "queued"
    capture.updated_at = now
    db.add(job)
    await db.flush()
    return job


async def fetch_due_jobs(db: AsyncSession, *, limit: int = 5) -> list[ProcessingJob]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.status == "queued", ProcessingJob.scheduled_at <= now)
        .order_by(ProcessingJob.scheduled_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())
