"""
バックグラウンドでprocessing_jobsを処理するワーカー。
仕様書12「AI処理はバックグラウンドで実行」/ 13「AIが使用できない場合」対応。

外部キュー(Redis/Celery等)は導入せず、SQLiteをキューとして使うシンプルな
ポーリングループにする(個人利用・単一プロセスという規模に対して十分)。
FastAPIのstartupイベントから asyncio.create_task で起動する想定。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.ai.ollama_client import OllamaClient
from app.ai.pipeline import process_capture
from app.config import get_settings
from app.core.job_policy import decide_retry
from app.db import session_scope
from app.jobs.queue import fetch_due_jobs
from app.models import Capture, ProcessingJob

logger = logging.getLogger("brain_twin.worker")
settings = get_settings()


class JobWorker:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self.ollama = OllamaClient()

    def start(self) -> None:
        if self._task is None:
            self._stop.clear()
            self._task = asyncio.create_task(self._loop(), name="brain-twin-job-worker")
            logger.info("job worker started")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
            logger.info("job worker stopped")

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed_any = await self._drain_once()
            except Exception:  # noqa: BLE001 - ワーカーループ自体は絶対に落とさない
                logger.exception("job worker loop iteration failed")
                processed_any = False

            if not processed_any:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=settings.job_poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass

    async def _drain_once(self) -> bool:
        async with session_scope() as db:
            jobs = await fetch_due_jobs(db, limit=5)
            if not jobs:
                return False
            for job in jobs:
                await self._process_job(db, job)
            await db.commit()
            return True

    async def _process_job(self, db, job: ProcessingJob) -> None:
        now = datetime.now(timezone.utc)
        job.status = "processing"
        job.started_at = now
        job.attempt_count += 1
        job.updated_at = now
        await db.flush()

        result = await db.execute(select(Capture).where(Capture.id == job.capture_id))
        capture = result.scalar_one_or_none()
        if capture is None:
            job.status = "failed"
            job.last_error = "capture が見つかりません(削除された可能性)"
            job.updated_at = datetime.now(timezone.utc)
            return

        capture.processing_status = "processing"

        try:
            outcome = await process_capture(job.capture_id, db, self.ollama)
        except Exception as e:  # noqa: BLE001 - 想定外の例外もジョブ失敗として扱い、原文は必ず残す
            logger.exception("unexpected error while processing capture %s", job.capture_id)
            outcome = None
            error_message = f"予期しないエラー: {e}"
        else:
            error_message = outcome.reason if not outcome.ok else None

        if outcome is not None and outcome.ok:
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.last_error = None
            capture.processing_status = "done"
        else:
            unavailable = bool(outcome and outcome.unavailable)
            decision = decide_retry(
                attempt_count=job.attempt_count,
                max_attempts=settings.job_max_attempts,
                now=datetime.now(timezone.utc),
            )
            job.last_error = error_message
            if unavailable:
                # Ollama自体に繋がらない場合は、短い間隔でしつこく再試行するより
                # 『起きたら整理します』という体験に合わせて少し長めの間隔で待つ。
                job.status = "queued"
                job.scheduled_at = decision.next_attempt_at or datetime.now(timezone.utc)
                capture.processing_status = "unavailable"
            elif decision.should_retry:
                job.status = "queued"
                job.scheduled_at = decision.next_attempt_at
                capture.processing_status = "queued"
            else:
                job.status = "failed"
                capture.processing_status = "failed"

        job.updated_at = datetime.now(timezone.utc)
        capture.updated_at = datetime.now(timezone.utc)


worker = JobWorker()
