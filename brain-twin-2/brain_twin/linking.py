"""Phase 2: Memory間のLink生成(指示書17・28章)。

依存フリーの純粋関数のみで構成する(brain-twin/apps/server/app/core/linking.py で
検証済みの設計をそのまま踏襲。指示書38章「既存構成の再利用可能部分」)。
ベクトル類似度は使わない(Vector SearchはREADME記載の別Phase)。ここでは
同一トピック・同一エンティティ・時間的近さの3種類のみを扱う。

生成されたリンクは、指示書17章「二段階想起(Associative Retrieval)」で
Memory同士を辿るための土台になる。

--- strengthの設計(レビュー対応) ---

以前の実装は same_entity のstrengthを same_topic より常に強く設定していたが、
Entity抽出(entity_extract.py)は精度の低いヒューリスティックであり、
精度の低い一致を強いリンクの根拠として扱うべきではない、という指摘を受けて
以下のように変更した:

  - same_topic / temporal_relation は固定の基礎strengthを使う
    (topicはPhase 1由来のキーワード分類で、Entity抽出より精度が高いと見なせるため)。
  - same_entity は「両エンティティのconfidenceの最小値」を基礎strengthに掛け合わせる。
    低confidence(=一般語かもしれない)の一致は自動的にstrengthが下がり、
    high confidenceの一致が複数重なった場合にのみsame_topicと同等以上になりうる
    (test_linking.py 参照)。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from brain_twin.models import ExtractedEntity

# 指示書17章「二段階想起」のための時間的近さの窓。pipeline.py がDB側の候補検索
# (時間範囲クエリ)にもこの値を使うため、モジュール外から参照できるよう公開する。
TEMPORAL_CLOSE_WINDOW = timedelta(minutes=30)

# 「関連Memory」の上限は、relation行数ではなくMemory数(target_memory_id)に対して
# 適用する(レビュー対応: 以前はrelation単位で上限を適用していたため、1つのMemoryペアで
# same_topic/same_entity/temporal_relationが同時に発生すると3枠消費し、10件設定でも
# 実質3〜4件しか関連Memoryが残らない問題があった)。1つのMemoryペアに複数種類の関連が
# 同時に成立するのは自然なことなので、それ自体は間引かず、
# 「target_memory_idごとの合計strengthで上位N件のMemoryを選び、選ばれたMemoryに
# 付随する全relationをそのまま返す」方式にする。
_MAX_LINKED_MEMORIES = 10

_SAME_TOPIC_STRENGTH = 1.0
_SAME_ENTITY_BASE_STRENGTH = 1.0
_TEMPORAL_STRENGTH = 0.5


@dataclass(frozen=True)
class MemoryCandidate:
    id: str
    topics: list[str]
    entities: list[ExtractedEntity]
    created_at: datetime


@dataclass(frozen=True)
class LinkSuggestion:
    target_memory_id: str
    relation_type: str  # same_topic | same_entity | temporal_relation
    reason: str
    strength: float


def _confidence_by_name(entities: list[ExtractedEntity]) -> dict[str, float]:
    return {e.name: e.confidence for e in entities}


def _entity_match_strength(target_conf: dict[str, float], cand_conf: dict[str, float], shared: set[str]) -> float:
    """共有エンティティごとに「両側のconfidenceの小さい方」を信頼度とし、その平均を
    strengthへ反映する。min(積ではなく)を使うのは、片方のみ信頼度が高くても
    もう片方が低ければ全体としては弱い根拠、という保守的な扱いにするため。"""
    pair_confidences = [min(target_conf[name], cand_conf[name]) for name in shared]
    avg_confidence = sum(pair_confidences) / len(pair_confidences)
    return _SAME_ENTITY_BASE_STRENGTH * len(shared) * avg_confidence


def suggest_links(
    target_topics: list[str],
    target_entities: list[ExtractedEntity],
    target_created_at: datetime,
    candidates: list[MemoryCandidate],
) -> list[LinkSuggestion]:
    target_entity_conf = _confidence_by_name(target_entities)
    window_seconds = TEMPORAL_CLOSE_WINDOW.total_seconds()

    all_suggestions: list[LinkSuggestion] = []

    for cand in candidates:
        shared_topics = set(target_topics) & set(cand.topics)
        if shared_topics:
            all_suggestions.append(
                LinkSuggestion(
                    target_memory_id=cand.id,
                    relation_type="same_topic",
                    reason=f"共通のトピック: {', '.join(sorted(shared_topics))}",
                    strength=_SAME_TOPIC_STRENGTH * len(shared_topics),
                )
            )

        cand_entity_conf = _confidence_by_name(cand.entities)
        shared_entities = set(target_entity_conf) & set(cand_entity_conf)
        if shared_entities:
            all_suggestions.append(
                LinkSuggestion(
                    target_memory_id=cand.id,
                    relation_type="same_entity",
                    reason=f"共通の固有名詞: {', '.join(sorted(shared_entities))}",
                    strength=_entity_match_strength(target_entity_conf, cand_entity_conf, shared_entities),
                )
            )

        if window_seconds > 0:
            delta = abs((target_created_at - cand.created_at).total_seconds())
            if delta <= window_seconds:
                recency = max(0.3, 1.0 - delta / window_seconds)
                all_suggestions.append(
                    LinkSuggestion(
                        target_memory_id=cand.id,
                        relation_type="temporal_relation",
                        reason="近い時刻に記録されたMemory",
                        strength=_TEMPORAL_STRENGTH * recency,
                    )
                )

    return _select_top_memories(all_suggestions)


def _select_top_memories(suggestions: list[LinkSuggestion]) -> list[LinkSuggestion]:
    strength_by_target: dict[str, float] = {}
    for s in suggestions:
        strength_by_target[s.target_memory_id] = strength_by_target.get(s.target_memory_id, 0.0) + s.strength

    top_targets = sorted(strength_by_target, key=lambda tid: strength_by_target[tid], reverse=True)
    top_target_set = set(top_targets[:_MAX_LINKED_MEMORIES])

    selected = [s for s in suggestions if s.target_memory_id in top_target_set]
    selected.sort(key=lambda s: (strength_by_target[s.target_memory_id], s.strength), reverse=True)
    return selected


def to_wikilink(memory_id: str) -> str:
    return f"[[{memory_id}]]"


def from_wikilink(value: str) -> str | None:
    value = value.strip()
    if value.startswith("[[") and value.endswith("]]"):
        return value[2:-2]
    return None
