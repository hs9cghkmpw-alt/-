"""Central retrieval weighting shared by lexical `search.py` and Sprint 4C Hybrid ranking.

Extracted so that the `(1 + importance_weight * importance) * confidence * recency` formula
exists in exactly one place. `search.py` keeps applying it once, the same as before; Hybrid
applies it once too, after RRF fusion, never per-channel (metadata must never be applied twice).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

# 指示書16章: 「configで重み変更可能にする」への対応。ひとまずモジュール定数として
# 公開し、将来的に設定ファイル/CLIオプションから上書きできるようにしてある。
IMPORTANCE_WEIGHT = 0.15
CONFIDENCE_WEIGHT = 1.0
RECENCY_HALF_LIFE_DAYS = 90.0

MIN_QUERY_LENGTH = 3  # trigramトークナイザの実用上の下限(brain-twin側の実績を踏襲)


def recency_weight(event_date: str, *, now: datetime | None = None) -> float:
    try:
        event_dt = datetime.strptime(event_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0.5
    reference = now or datetime.now(timezone.utc)
    days_ago = max((reference - event_dt).days, 0)
    # 半減期ベースの単純な減衰。importance 5のMemoryは他の要素で十分上位に来るため、
    # ここでは「新しいほど有利」程度の緩い重みに留める(指示書14章: 忘れる=検索順位低下)。
    return 0.5 ** (days_ago / RECENCY_HALF_LIFE_DAYS)


def metadata_multiplier(
    *, importance: int, confidence: float, event_date: str, now: datetime | None = None
) -> float:
    """The single place that turns importance/confidence/recency into one scalar multiplier.

    Callers apply this exactly once to a pure relevance score (lexical rank, RRF fusion score,
    etc.). Applying it twice would double-count metadata and is a contract violation for
    Hybrid ranking."""
    return (
        (1.0 + IMPORTANCE_WEIGHT * importance)
        * (CONFIDENCE_WEIGHT * confidence)
        * recency_weight(event_date, now=now)
    )


@dataclass(frozen=True)
class RetrievalWeights:
    """Central Hybrid fusion configuration; no magic numbers scattered across modules."""

    lexical_weight: float = 0.6
    vector_weight: float = 0.4
    rrf_k: int = 60
    candidate_multiplier: int = 3

    def __post_init__(self) -> None:
        if self.lexical_weight < 0 or self.vector_weight < 0:
            raise ValueError("retrieval weights must be non-negative")
        if self.lexical_weight == 0 and self.vector_weight == 0:
            raise ValueError("at least one of lexical_weight/vector_weight must be positive")
        if self.rrf_k <= 0:
            raise ValueError("rrf_k must be positive")
        if self.candidate_multiplier <= 0:
            raise ValueError("candidate_multiplier must be positive")
