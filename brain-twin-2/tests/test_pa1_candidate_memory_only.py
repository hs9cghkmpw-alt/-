from __future__ import annotations

from brain_twin_eval.candidate_memory_only import prepare_dense_from_memories
from brain_twin_eval.candidate_runtime import DenseCandidateProfile
from brain_twin_eval.dataset import EvaluationMemory


class FakeDenseModel:
    def encode(self, sentences, **kwargs):
        rows = []
        for sentence in sentences:
            rows.append([1.0, 0.0] if "alpha" in sentence.lower() else [0.0, 1.0])
        return rows


def test_memory_only_dense_preparation_needs_no_query_judgements() -> None:
    memories = (
        EvaluationMemory("alpha", "Alpha", "alpha memory", ("en",), "short", True),
        EvaluationMemory("beta", "Beta", "beta memory", ("en",), "short", True),
    )
    profile = DenseCandidateProfile(
        candidate_id="fake",
        model_path="unused-with-injected-model",
        model_name="fake/model",
        model_revision="a" * 40,
        instruction_id="none",
        query_template="{query}",
        document_template="{document}",
        dimension=2,
    )
    retriever, stats = prepare_dense_from_memories(memories, profile, model=FakeDenseModel())
    assert [item.memory_id for item in retriever.search("alpha", 2)] == ["alpha", "beta"]
    assert stats.active_memory_count == 2
