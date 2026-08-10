"""依存フリー。日本語の日付表現をルールベースで抽出する。
AIが見つけた possible_dates を補完する目的(pipeline.py参照)であり、
ここで見つからなくてもAI側の抽出があれば問題ない、あくまで保険的な機能。
断定できない場合は resolved_date=None, precision='unknown' とする。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]


@dataclass(frozen=True)
class DateCandidate:
    raw_text: str
    resolved_date: str | None
    precision: str  # day | week | month | unknown


def _fmt(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def _next_weekday(base: datetime, weekday_index: int, *, next_week: bool) -> datetime:
    days_ahead = (weekday_index - base.weekday()) % 7
    if next_week:
        days_ahead = days_ahead + 7 if days_ahead > 0 else 7
    return base + timedelta(days=days_ahead)


_RELATIVE_DAY_OFFSETS = {
    "今日": 0,
    "本日": 0,
    "明日": 1,
    "明後日": 2,
    "昨日": -1,
    "一昨日": -2,
}


def extract_date_candidates(text: str, captured_at: datetime) -> list[DateCandidate]:
    if not text:
        return []
    candidates: list[DateCandidate] = []
    seen_raw: set[str] = set()

    def add(raw: str, resolved: str | None, precision: str) -> None:
        if raw in seen_raw:
            return
        seen_raw.add(raw)
        candidates.append(DateCandidate(raw_text=raw, resolved_date=resolved, precision=precision))

    # 1. 相対的な日 (今日/明日/明後日/昨日/一昨日)
    for word, offset in _RELATIVE_DAY_OFFSETS.items():
        if word in text:
            add(word, _fmt(captured_at + timedelta(days=offset)), "day")

    # 2. 来週/再来週/来月/再来月 (幅があるためprecisionはweek/month、resolved_dateはNone)
    if "再来週" in text:
        add("再来週", None, "week")
    elif "来週" in text:
        add("来週", None, "week")
    if "再来月" in text:
        add("再来月", None, "month")
    elif "来月" in text:
        add("来月", None, "month")

    # 3. 明示的な日付 (YYYY年M月D日 / M月D日 / M/D)
    for m in re.finditer(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", text):
        year_str, month_str, day_str = m.groups()
        year = int(year_str) if year_str else captured_at.year
        try:
            candidate_dt = datetime(year, int(month_str), int(day_str))
        except ValueError:
            continue
        if year_str is None and candidate_dt.date() < captured_at.date():
            # 年指定が無く、すでに過ぎた日付なら来年のことと解釈する
            candidate_dt = candidate_dt.replace(year=year + 1)
        add(m.group(0), _fmt(candidate_dt), "day")

    for m in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text):
        month_str, day_str = m.groups()
        try:
            candidate_dt = datetime(captured_at.year, int(month_str), int(day_str))
        except ValueError:
            continue
        if candidate_dt.date() < captured_at.date():
            candidate_dt = candidate_dt.replace(year=captured_at.year + 1)
        add(m.group(0), _fmt(candidate_dt), "day")

    # 4. 曜日 (今度の/来週の 月曜日 等)。直近の該当曜日を解決する。
    for idx, w in enumerate(_WEEKDAYS_JA):
        for pattern, next_week in ((rf"来週の?{w}曜日", True), (rf"(?:今度の)?{w}曜日", False)):
            m = re.search(pattern, text)
            if m:
                resolved = _next_weekday(captured_at, idx, next_week=next_week)
                add(m.group(0), _fmt(resolved), "day")

    return candidates
