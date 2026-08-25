"""検索(指示書15・16・27章)。

Phase 1ではベクトル検索は使わず、FTS(キーワード) + メタデータ
(importance/confidence/recency)を組み合わせた簡易Hybrid Retrievalとする。
重みは将来調整できるよう、この関数の外(呼び出し側)から差し替え可能にしている。

【Sprint 4C】metadata multiplierの計算式そのものは `retrieval_weights.py` へ集約した
(Hybrid Primary Searchも同じ式をRRF融合後に1回だけ適用する必要があるため)。この
モジュールの`search()`自体の入出力・スコア式は一切変更していない
(`tests/test_search.py`のcharacterization testで固定)。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from brain_twin import db
from brain_twin.config import Config
from brain_twin.retrieval_weights import (
    CONFIDENCE_WEIGHT, IMPORTANCE_WEIGHT, MIN_QUERY_LENGTH, RECENCY_HALF_LIFE_DAYS,
    metadata_multiplier,
)

_MIN_QUERY_LENGTH = MIN_QUERY_LENGTH  # 後方互換のためモジュール属性名を維持する


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


def search(
    conn: sqlite3.Connection, query: str, *, limit: int = 20, now: datetime | None = None
) -> list[ScoredResult]:
    query = query.strip()
    if len(query) < _MIN_QUERY_LENGTH:
        return []

    hits = db.search(conn, query, limit=max(limit * 3, limit))  # 再スコアリング前に少し多めに取る

    scored = []
    for hit in hits:
        # bm25()は小さい(より負の)ほど一致度が高いため、符号反転して「大きいほど良い」に揃える。
        base_relevance = -hit.rank
        weight = metadata_multiplier(
            importance=hit.importance, confidence=hit.confidence, event_date=hit.event_date, now=now
        )
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
