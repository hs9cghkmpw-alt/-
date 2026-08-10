"""依存フリー。processing_jobsの再試行方針(仕様書12)。
指数バックオフ(上限あり)。Ollama未起動時は worker.py 側で理由が上書きされるが、
「次にいつ試すか」の計算はここに集約する。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

_BASE_DELAY_SECONDS = 10
_MAX_DELAY_SECONDS = 600  # 10分


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    next_attempt_at: datetime | None


def decide_retry(*, attempt_count: int, max_attempts: int, now: datetime) -> RetryDecision:
    delay = min(_BASE_DELAY_SECONDS * (2 ** max(attempt_count - 1, 0)), _MAX_DELAY_SECONDS)
    next_attempt_at = now + timedelta(seconds=delay)
    should_retry = attempt_count < max_attempts
    return RetryDecision(should_retry=should_retry, next_attempt_at=next_attempt_at)
