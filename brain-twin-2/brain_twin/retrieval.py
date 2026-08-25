"""Phase 3 associative retrieval over persisted one-hop memory links.

Sprint 4D: the 1-hop expansion below is shared by plain lexical search, Vector Primary
Search, and Hybrid Primary Search alike -- `retrieve_from_primary()` only needs each
primary result's `memory_id`, so it works with `search.ScoredResult`, `vector_search.
VectorResult`, and `hybrid_search.HybridResult` without depending on any of those modules.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Generic, Protocol, TypeVar

from brain_twin import db, search
from brain_twin.config import Config

DEFAULT_RELATED_LIMIT = 20

@dataclass(frozen=True)
class RelatedRelation:
    primary_memory_id: str
    relation_type: str
    reason: str
    strength: float
    direction: str


@dataclass
class RelatedMemory:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    relations: list[RelatedRelation] = field(default_factory=list)


class _HasMemoryId(Protocol):
    memory_id: str


PrimaryT = TypeVar("PrimaryT", bound=_HasMemoryId)


@dataclass(frozen=True)
class RetrievalResult(Generic[PrimaryT]):
    primary: list[PrimaryT]
    related: list[RelatedMemory]


def retrieve_from_primary(
    conn: sqlite3.Connection,
    primary: list[PrimaryT],
    *,
    related_limit: int = DEFAULT_RELATED_LIMIT,
) -> RetrievalResult[PrimaryT]:
    """1-hop expansion over any primary result list (lexical, Vector, or Hybrid)."""
    if related_limit < 0:
        raise ValueError("related_limit must be non-negative")
    primary_ids = [item.memory_id for item in primary]
    if not primary_ids or related_limit == 0:
        return RetrievalResult(primary=primary, related=[])

    primary_id_set = set(primary_ids)
    primary_rank = {memory_id: rank for rank, memory_id in enumerate(primary_ids)}
    candidates_by_id: dict[str, list[db.RelatedCandidateRow]] = {}
    for row in db.related_link_candidates_for_memories(conn, primary_ids):
        if row.memory_id in primary_id_set:
            continue
        candidates_by_id.setdefault(row.memory_id, []).append(row)

    def sort_key(memory_id: str) -> tuple[float, int, int, str]:
        rows = candidates_by_id[memory_id]
        # Phase 2のlink生成と同じく、同一Related Memoryへの複数根拠は実strengthを
        # 合計する。根拠を保持したまま、relation_type固定優先度を再導入しないため。
        combined_strength = sum(row.strength for row in rows)
        best_primary = min(primary_rank[row.primary_memory_id] for row in rows)
        importance = max(row.importance for row in rows)
        return (-combined_strength, best_primary, -importance, memory_id)

    selected_ids = sorted(candidates_by_id, key=sort_key)[:related_limit]
    details_by_id = db.memory_details_by_ids(conn, selected_ids)
    related_items: list[RelatedMemory] = []
    for memory_id in selected_ids:
        detail = details_by_id.get(memory_id)
        if detail is None:
            continue
        relations: list[RelatedRelation] = []
        for row in candidates_by_id[memory_id]:
            relation = RelatedRelation(
                primary_memory_id=row.primary_memory_id,
                relation_type=row.relation_type,
                reason=row.reason,
                strength=row.strength,
                direction=row.direction,
            )
            if relation not in relations:
                relations.append(relation)
        related_items.append(RelatedMemory(
            memory_id=detail.memory_id,
            title=detail.title,
            content=detail.content,
            type=detail.type,
            event_date=detail.event_date,
            relations=relations,
        ))

    return RetrievalResult(primary=primary, related=related_items)


def retrieve(
    conn: sqlite3.Connection,
    query: str,
    *,
    primary_limit: int = 20,
    related_limit: int = DEFAULT_RELATED_LIMIT,
) -> RetrievalResult[search.ScoredResult]:
    primary = search.search(conn, query, limit=primary_limit)
    return retrieve_from_primary(conn, primary, related_limit=related_limit)


def retrieve_with_config(
    config: Config,
    query: str,
    *,
    primary_limit: int = 20,
    related_limit: int = DEFAULT_RELATED_LIMIT,
) -> RetrievalResult:
    with db.connect(config) as conn:
        return retrieve(
            conn,
            query,
            primary_limit=primary_limit,
            related_limit=related_limit,
        )
