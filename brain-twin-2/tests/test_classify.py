from brain_twin import classify
from brain_twin.models import MemoryType


def test_short_casual_input_is_not_memory_worthy():
    result = classify.classify("ナイキのカバンだ")
    assert result.is_memory_worthy is False


def test_decision_keyword_detected():
    result = classify.classify("クラルティに応募することにした")
    assert result.is_memory_worthy is True
    assert result.type == MemoryType.DECISION
    assert result.confidence == 1.0


def test_preference_keyword_detected():
    result = classify.classify("コーヒーが好き")
    assert result.is_memory_worthy is True
    assert result.type == MemoryType.PREFERENCE


def test_goal_keyword_detected():
    result = classify.classify("いつか海外で働くのを目指す")
    assert result.is_memory_worthy is True
    assert result.type == MemoryType.GOAL


def test_long_plain_statement_becomes_thought_or_experience():
    result = classify.classify("病院いったら診断書お願いしなきゃ")
    assert result.is_memory_worthy is True
    assert result.type in (MemoryType.THOUGHT, MemoryType.EXPERIENCE)
    assert "health" in result.topics


def test_confidence_is_always_1_0_in_phase1():
    """指示書11章: 本人が直接述べた内容はconfidence=1.0。Phase1はAI推測を行わないため常に1.0。"""
    for text in ("コーヒーが好き", "病院いったら診断書お願いしなきゃ", "クラルティに応募することにした"):
        assert classify.classify(text).confidence == 1.0


def test_title_is_truncated_for_long_text():
    long_text = "あ" * 50
    result = classify.classify(long_text)
    assert len(result.title) <= 25
    assert result.title.endswith("…")
