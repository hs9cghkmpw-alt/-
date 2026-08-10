"""依存フリー。ルールベースのthought間リンク候補生成(仕様書8「関連付け」)。
意味的類似度(embeddings)は呼び出し側(pipeline.py)が別途担当するため、
ここでは同一capture内共起・同一プロジェクト・同一人物・表層類似・時間的近さのみを扱う。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

_TEMPORAL_CLOSE_WINDOW = timedelta(minutes=15)
_SURFACE_SIMILARITY_THRESHOLD = 0.5
_MAX_SUGGESTIONS = 15


@dataclass(frozen=True)
class ThoughtForLinking:
    id: str
    content: str
    people: list[str]
    places: list[str]
    project_names: list[str]
    created_at: datetime
    capture_id: str


@dataclass(frozen=True)
class LinkSuggestion:
    relation_type: str
    score: float
    reason: str


def _trigrams(text: str) -> set[str]:
    normalized = "".join(text.split())
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {normalized[i : i + 3] for i in range(len(normalized) - 2)}


def _surface_similarity(a: str, b: str) -> float:
    ta, tb = _trigrams(a), _trigrams(b)
    if not ta or not tb:
        return 0.0
    intersection = len(ta & tb)
    union = len(ta | tb)
    return intersection / union if union else 0.0


def suggest_links(
    target: ThoughtForLinking, candidates: list[ThoughtForLinking]
) -> list[tuple[str, LinkSuggestion]]:
    results: list[tuple[float, str, LinkSuggestion]] = []

    for cand in candidates:
        if cand.id == target.id:
            continue

        if cand.capture_id == target.capture_id:
            results.append(
                (1.0, cand.id, LinkSuggestion(relation_type="temporal_relation", score=1.0, reason="同じ入力内"))
            )

        shared_projects = set(target.project_names) & set(cand.project_names)
        if shared_projects:
            score = min(1.0, 0.6 + 0.1 * len(shared_projects))
            results.append(
                (
                    score,
                    cand.id,
                    LinkSuggestion(
                        relation_type="same_project",
                        score=score,
                        reason=f"共通のプロジェクト: {', '.join(sorted(shared_projects))}",
                    ),
                )
            )

        shared_people = set(target.people) & set(cand.people)
        if shared_people:
            score = min(1.0, 0.6 + 0.1 * len(shared_people))
            results.append(
                (
                    score,
                    cand.id,
                    LinkSuggestion(
                        relation_type="same_person",
                        score=score,
                        reason=f"共通の人物: {', '.join(sorted(shared_people))}",
                    ),
                )
            )

        shared_places = set(target.places) & set(cand.places)
        if shared_places:
            score = min(1.0, 0.5 + 0.1 * len(shared_places))
            results.append(
                (
                    score,
                    cand.id,
                    LinkSuggestion(
                        relation_type="same_topic",
                        score=score,
                        reason=f"共通の場所: {', '.join(sorted(shared_places))}",
                    ),
                )
            )

        surface_score = _surface_similarity(target.content, cand.content)
        if surface_score >= _SURFACE_SIMILARITY_THRESHOLD:
            results.append(
                (
                    surface_score,
                    cand.id,
                    LinkSuggestion(relation_type="same_topic", score=surface_score, reason="表現が似ている"),
                )
            )

        if cand.capture_id != target.capture_id:
            delta = abs((target.created_at - cand.created_at).total_seconds())
            if delta <= _TEMPORAL_CLOSE_WINDOW.total_seconds():
                score = max(0.3, 1.0 - delta / _TEMPORAL_CLOSE_WINDOW.total_seconds())
                results.append(
                    (
                        score,
                        cand.id,
                        LinkSuggestion(
                            relation_type="temporal_relation",
                            score=score,
                            reason="近い時刻に記録された思考",
                        ),
                    )
                )

    results.sort(key=lambda item: item[0], reverse=True)
    return [(cand_id, suggestion) for _score, cand_id, suggestion in results[:_MAX_SUGGESTIONS]]
