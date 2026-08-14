"""Phase 1のダミー分類器(指示書35章: 「Phase 1はダミー分類でも構わない」)。

キーワードベースの粗い推定のみを行う。LLMによる本格的な自動ラベリング
(指示書9章)はPhase 2/4で本実装する。差し替えを容易にするため、
入力はraw_textの文字列のみ、出力は models.ClassificationResult に
固定しており、この関数を丸ごとLLM版に置き換えられるようにしてある。

推測(この分類器の判定)を事実として扱わないこと自体が指示書の絶対原則
(5章・34章)だが、Phase 1では実際のAI推論を一切行っていない
(単なるキーワード一致)ため、ここではAI_INFERENCE型は使わず、
confidenceは常に1.0(=本人の原文をそのまま保持しているだけ)とする。
"""
from __future__ import annotations

from brain_twin.models import ClassificationResult, MemoryType

_MIN_MEMORY_LENGTH = 12  # これ未満は「雑談」としてDaily Logのみに残す(粗い閾値)

_DECISION_KEYWORDS = ("決めた", "することにした", "やめることにした", "応募する", "辞めることにした", "始めることにした")
_PREFERENCE_KEYWORDS = ("好き", "嫌い", "苦手", "得意")
_GOAL_KEYWORDS = ("したい", "やりたい", "目指す", "目標")
_PAST_TENSE_MARKERS = ("した", "だった", "できた", "やった", "終わった")
_HIGH_IMPORTANCE_KEYWORDS = ("人生", "重大", "転職", "結婚", "引っ越し")

_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "work": ("仕事", "会社", "業務", "プロジェクト", "作業"),
    "health": ("体調", "疲れ", "病院", "睡眠", "健康"),
    "idea": ("アイデア", "思いつ", "アプリ", "考えた", "設計"),
    "family": ("家族", "子供", "こども", "妻", "夫", "親"),
    "money": ("お金", "給料", "貯金", "支払"),
    "learning": ("勉強", "学習", "読書"),
}

_TITLE_MAX_LEN = 24


def _extract_topics(text: str) -> list[str]:
    topics = [topic for topic, keywords in _TOPIC_KEYWORDS.items() if any(k in text for k in keywords)]
    return topics


def _make_title(text: str) -> str:
    stripped = text.strip().splitlines()[0]
    if len(stripped) <= _TITLE_MAX_LEN:
        return stripped
    return stripped[:_TITLE_MAX_LEN] + "…"


def classify(text: str) -> ClassificationResult:
    stripped = text.strip()
    topics = _extract_topics(stripped)
    title = _make_title(stripped)

    importance = 3 if any(k in stripped for k in _HIGH_IMPORTANCE_KEYWORDS) else 2

    if any(k in stripped for k in _DECISION_KEYWORDS):
        return ClassificationResult(
            is_memory_worthy=True, type=MemoryType.DECISION, importance=max(importance, 3),
            confidence=1.0, topics=topics, entities=[], title=title,
        )

    if any(k in stripped for k in _GOAL_KEYWORDS):
        return ClassificationResult(
            is_memory_worthy=True, type=MemoryType.GOAL, importance=max(importance, 3),
            confidence=1.0, topics=topics, entities=[], title=title,
        )

    if any(k in stripped for k in _PREFERENCE_KEYWORDS):
        return ClassificationResult(
            is_memory_worthy=True, type=MemoryType.PREFERENCE, importance=importance,
            confidence=1.0, topics=topics, entities=[], title=title,
        )

    if len(stripped) >= _MIN_MEMORY_LENGTH:
        mem_type = MemoryType.EXPERIENCE if any(k in stripped for k in _PAST_TENSE_MARKERS) else MemoryType.THOUGHT
        return ClassificationResult(
            is_memory_worthy=True, type=mem_type, importance=importance,
            confidence=1.0, topics=topics, entities=[], title=title,
        )

    # 短い/雑談らしい入力はLong-term Memoryへ昇格させない(Daily Logにはそのまま残る)。
    return ClassificationResult(
        is_memory_worthy=False, type=MemoryType.THOUGHT, importance=1, confidence=1.0,
        topics=topics, entities=[], title=title,
    )
