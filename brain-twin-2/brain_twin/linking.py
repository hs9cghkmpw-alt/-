"""Phase 2: Memory間のLink生成(指示書17・28章)。

依存フリーの純粋関数のみで構成する(brain-twin/apps/server/app/core/linking.py で
検証済みの設計をそのまま踏襲。指示書38章「既存構成の再利用可能部分」)。
ベクトル類似度は使わない(Vector SearchはREADME記載の別Phase)。ここでは
同一トピック・同一エンティティ・時間的近さの3種類のみを扱う。

生成されたリンクは、指示書17章「二段階想起(Associative Retrieval)」で
Memory同士を辿るための土台になる。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

_TEMPORAL_CLOSE_WINDOW = timedelta(minutes=30)
_MAX_LINKS_PER_MEMORY = 10


@dataclass(frozen=True)
class MemoryCandidate:
    """Link候補となる既存Memoryの、比較に必要な最小限の情報。"""

    id: str
    topics: list[str]
    entities: list[str]
    created_at: datetime


@dataclass(frozen=True)
class LinkSuggestion:
    target_memory_id: str
    relation_type: str  # same_topic | same_entity | temporal_relation
    reason: str
    strength: int  # 並べ替え用の粗いスコア(共有数が多いほど大きい)


def suggest_links(
    target_topics: list[str],
    target_entities: list[str],
    target_created_at: datetime,
    candidates: list[MemoryCandidate],
) -> list[LinkSuggestion]:
    suggestions: list[LinkSuggestion] = []

    for cand in candidates:
        shared_topics = set(target_topics) & set(cand.topics)
        if shared_topics:
            suggestions.append(
                LinkSuggestion(
                    target_memory_id=cand.id,
                    relation_type="same_topic",
                    reason=f"共通のトピック: {', '.join(sorted(shared_topics))}",
                    strength=len(shared_topics),
                )
            )

        shared_entities = set(target_entities) & set(cand.entities)
        if shared_entities:
            suggestions.append(
                LinkSuggestion(
                    target_memory_id=cand.id,
                    relation_type="same_entity",
                    reason=f"共通の固有名詞: {', '.join(sorted(shared_entities))}",
                    strength=len(shared_entities) * 2,  # 固有名詞の一致はトピックより強いシグナルとみなす
                )
            )

        delta = abs((target_created_at - cand.created_at).total_seconds())
        if delta <= _TEMPORAL_CLOSE_WINDOW.total_seconds():
            suggestions.append(
                LinkSuggestion(
                    target_memory_id=cand.id,
                    relation_type="temporal_relation",
                    reason="近い時刻に記録されたMemory",
                    strength=1,
                )
            )

    suggestions.sort(key=lambda s: s.strength, reverse=True)
    return suggestions[:_MAX_LINKS_PER_MEMORY]


def to_wikilink(memory_id: str) -> str:
    return f"[[{memory_id}]]"


def from_wikilink(value: str) -> str | None:
    value = value.strip()
    if value.startswith("[[") and value.endswith("]]"):
        return value[2:-2]
    return None
