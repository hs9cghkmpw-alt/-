"""検索(指示書15・16・27章)。

Phase 1ではベクトル検索は使わず、FTS(キーワード) + メタデータ
(importance/confidence/recency)を組み合わせた簡易Hybrid Retrievalとする。
重みは将来調整できるよう、この関数の外(呼び出し側)から差し替え可能にしている。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from brain_twin import db
from brain_twin.config import Config

# 指示書16章: 「configで重み変更可能にする」への対応。ひとまずモジュール定数として
# 公開し、将来的に設定ファイル/CLIオプションから上書きできるようにしてある。
IMPORTANCE_WEIGHT = 0.15
CONFIDENCE_WEIGHT = 1.0
RECENCY_HALF_LIFE_DAYS = 90.0

_MIN_QUERY_LENGTH = 3  # trigramトークナイザの実用上の下限(brain-twin側の実績を踏襲)


@dataclass(frozen=True)
class ScoredResult:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    confidence: float
    topics: list[str]
    entities: list[str]
    score: float


@dataclass(frozen=True)
class TimelineResult:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    importance: int
    confidence: float


def _recency_weight(event_date: str) -> float:
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.5
    days_ago = max((datetime.now(timezone.utc) - event_dt).days, 0)
    # 半減期ベースの単純な減衰。importance 5のMemoryは他の要素で十分上位に来るため、
    # ここでは「新しいほど有利」程度の緩い重みに留める(指示書14章: 忘れる=検索順位低下)。
    return 0.5 ** (days_ago / RECENCY_HALF_LIFE_DAYS)


def search(conn: sqlite3.Connection, query: str, *, limit: int = 20) -> list[ScoredResult]:
    query = query.strip()
    if len(query) < _MIN_QUERY_LENGTH:
        return []

    hits = db.search(conn, query, limit=max(limit * 3, limit))  # 再スコアリング前に少し多めに取る

    scored = []
    for hit in hits:
        # bm25()は小さい(より負の)ほど一致度が高いため、符号反転して「大きいほど良い」に揃える。
        base_relevance = -hit.rank
        weight = (1.0 + IMPORTANCE_WEIGHT * hit.importance) * (CONFIDENCE_WEIGHT * hit.confidence) * _recency_weight(hit.event_date)
        score = base_relevance * weight
        scored.append(
            ScoredResult(
                memory_id=hit.memory_id, title=hit.title, content=hit.content, type=hit.type,
                event_date=hit.event_date, importance=hit.importance, confidence=hit.confidence,
                topics=hit.topics, entities=hit.entities, score=score,
            )
        )

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:limit]


def search_with_config(config: Config, query: str, *, limit: int = 20) -> list[ScoredResult]:
    with db.connect(config) as conn:
        return search(conn, query, limit=limit)


def _validate_date(value: str | None, name: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"{name} must be a valid YYYY-MM-DD date")
    return value


def timeline(
    conn: sqlite3.Connection,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
) -> list[TimelineResult]:
    from_date = _validate_date(from_date, "from_date")
    to_date = _validate_date(to_date, "to_date")
    if from_date is not None and to_date is not None and from_date > to_date:
        raise ValueError("from_date must be on or before to_date")
    if limit < 1:
        raise ValueError("limit must be positive")
    return [
        TimelineResult(
            memory_id=row.memory_id,
            title=row.title,
            content=row.content,
            type=row.type,
            event_date=row.event_date,
            importance=row.importance,
            confidence=row.confidence,
        )
        for row in db.timeline_memories(
            conn, from_date=from_date, to_date=to_date, limit=limit
        )
    ]


def timeline_with_config(
    config: Config,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
) -> list[TimelineResult]:
    with db.connect(config) as conn:
        return timeline(conn, from_date=from_date, to_date=to_date, limit=limit)
