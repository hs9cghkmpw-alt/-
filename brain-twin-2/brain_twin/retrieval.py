"""Phase 3 associative retrieval over persisted one-hop memory links."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from brain_twin import db, search
from brain_twin.config import Config

DEFAULT_RELATED_LIMIT = 20

RELATION_WEIGHTS = {
    "same_entity": 3,
    "same_topic": 2,
    "temporal_relation": 1,
}


@dataclass(frozen=True)
class RelatedRelation:
    primary_memory_id: str
    relation_type: str
    reason: str
    direction: str


@dataclass
class RelatedMemory:
    memory_id: str
    title: str
    content: str
    type: str
    event_date: str
    relations: list[RelatedRelation] = field(default_factory=list)


@dataclass(frozen=True)
class RetrievalResult:
    primary: list[search.ScoredResult]
    related: list[RelatedMemory]


def retrieve(
    conn: sqlite3.Connection,
    query: str,
    *,
    primary_limit: int = 20,
    related_limit: int = DEFAULT_RELATED_LIMIT,
) -> RetrievalResult:
    if related_limit < 0:
        raise ValueError("related_limit must be non-negative")
    primary = search.search(conn, query, limit=primary_limit)
    primary_ids = [item.memory_id for item in primary]
    if not primary_ids or related_limit == 0:
        return RetrievalResult(primary=primary, related=[])

    primary_id_set = set(primary_ids)
    primary_rank = {memory_id: rank for rank, memory_id in enumerate(primary_ids)}
    related_by_id: dict[str, RelatedMemory] = {}
    rows_by_id: dict[str, list[db.RelatedLinkRow]] = {}
    for row in db.related_links_for_memories(conn, primary_ids):
        if row.memory_id in primary_id_set:
            continue
        rows_by_id.setdefault(row.memory_id, []).append(row)
        related = related_by_id.setdefault(
            row.memory_id,
            RelatedMemory(
                memory_id=row.memory_id,
                title=row.title,
                content=row.content,
                type=row.type,
                event_date=row.event_date,
            ),
        )
        relation = RelatedRelation(
            primary_memory_id=row.primary_memory_id,
            relation_type=row.relation_type,
            reason=row.reason,
            direction=row.direction,
        )
        if relation not in related.relations:
            related.relations.append(relation)

    def sort_key(item: RelatedMemory) -> tuple[int, int, int, str]:
        rows = rows_by_id[item.memory_id]
        best_primary = min(primary_rank[row.primary_memory_id] for row in rows)
        best_relation = max(RELATION_WEIGHTS.get(row.relation_type, 0) for row in rows)
        importance = max(row.importance for row in rows)
        return (best_primary, -best_relation, -importance, item.memory_id)

    related_items = sorted(related_by_id.values(), key=sort_key)[:related_limit]
    return RetrievalResult(primary=primary, related=related_items)


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
