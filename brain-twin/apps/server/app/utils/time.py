"""ISO8601文字列とdatetimeの相互変換。DBには常にUTCのISO8601文字列("...Z"終わり)で保存する。"""
from __future__ import annotations

from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    """"Z"サフィックスを含むISO8601文字列をtimezone-awareなdatetimeへ変換する。
    不正な値はValueErrorを送出する(呼び出し側で捕捉して静かにフォールバックする設計)。"""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
