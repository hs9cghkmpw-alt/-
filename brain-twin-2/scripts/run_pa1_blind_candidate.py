"""Run a frozen local retrieval configuration against a judgement-free formal blind runner package.

The runner package contains query text but no relevance labels. This script emits rankings/timing only;
it cannot compute quality metrics and does not accept a private judgement package.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin.embedding_document import DOCUMENT_TEMPLATE_VERSION  # noqa: E402
from brain_twin_eval.blind_ranking import (  # noqa: E402
    build_blind_manifest,
    evidence_json,
    run_blind_rankings,
    runner_input_from_mapping,
)
from brain_twin_eval.candidate_memory_only import (  # noqa: E402
    prepare_dense_from_memories,
    reranker_from_memories,
)
from brain_twin_eval.candidate_runtime import (  # noqa: E402
    DenseCandidateProfile,
    RerankerCandidateProfile,
    load_local_cross_encoder,
)
from brain_twin_eval.privacy_paths import require_outside_repository  # noqa: E402


def _read_text(path: str | None, default: str) -> str:
    if path is None:
        return default
    return Path(path).read_text(encoding="utf-8").rstrip("\r\n")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-package", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--instruction-id", required=True)
    parser.add_argument("--query-template-file")
    parser.add_argument("--document-template-file")
    parser.add_argument("--dimension", type=int)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--warm-repeats", type=int, default=30)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--out", required=True)

    parser.add_argument("--reranker-candidate-id")
    parser.add_argument("--reranker-model-path")
    parser.add_argument("--reranker-model-name")
    parser.add_argument("--reranker-model-revision")
    parser.add_argument("--reranker-instruction-id", default="brain-twin-memory-relevance-v1")
    parser.add_argument("--reranker-instruction-file")
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-candidate-k", type=int, default=50)
    parser.add_argument("--reranker-trust-remote-code", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _args()
    repository_root = Path(__file__).resolve().parents[2]
    runner_path = require_outside_repository(args.runner_package, repository_root, label="formal blind runner package")
    out_path = require_outside_repository(args.out, repository_root, label="formal blind ranking evidence")
    if runner_path == out_path:
        raise SystemExit("runner package and ranking evidence paths must be distinct")

    runner_raw = json.loads(runner_path.read_text(encoding="utf-8-sig"))
    runner = runner_input_from_mapping(runner_raw)
    query_template = _read_text(args.query_template_file, "{query}")
    document_template = _read_text(args.document_template_file, "{document}")
    dense_profile = DenseCandidateProfile(
        candidate_id=args.candidate_id,
        model_path=args.model_path,
        model_name=args.model_name,
        model_revision=args.model_revision,
        instruction_id=args.instruction_id,
        query_template=query_template,
        document_template=document_template,
        dimension=args.dimension,
        normalized=True,
        batch_size=args.batch_size,
        trust_remote_code=args.trust_remote_code,
    )
    dense, prep = prepare_dense_from_memories(runner.memories, dense_profile)
    retriever = dense
    final_experiment_id = args.candidate_id
    provider_label = "sentence_transformers_local_eval"
    model_name = args.model_name
    model_revision = args.model_revision
    instruction_id = args.instruction_id
    instruction_text = query_template
    backend_label = "evaluation_exact_dense"
    backend_params = {
        "corpus_memory_count": prep.active_memory_count,
        "query_template_sha256": prep.query_template_sha256,
        "document_template_sha256": prep.document_template_sha256,
        "warm_repeats": args.warm_repeats,
    }
    extra = {"dense_preparation": asdict(prep)}

    reranker_requested = any(
        value for value in (
            args.reranker_candidate_id,
            args.reranker_model_path,
            args.reranker_model_name,
            args.reranker_model_revision,
        )
    )
    if reranker_requested:
        required = {
            "reranker_candidate_id": args.reranker_candidate_id,
            "reranker_model_path": args.reranker_model_path,
            "reranker_model_name": args.reranker_model_name,
            "reranker_model_revision": args.reranker_model_revision,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("missing reranker arguments: " + ", ".join(missing))
        reranker_instruction = _read_text(
            args.reranker_instruction_file,
            "Given a personal memory retrieval query, identify passages that are relevant to the user's intended recollection.",
        )
        reranker_profile = RerankerCandidateProfile(
            candidate_id=args.reranker_candidate_id,
            model_path=args.reranker_model_path,
            model_name=args.reranker_model_name,
            model_revision=args.reranker_model_revision,
            instruction_id=args.reranker_instruction_id,
            instruction_text=reranker_instruction,
            batch_size=args.reranker_batch_size,
            trust_remote_code=args.reranker_trust_remote_code,
        )
        scorer, load_stats = load_local_cross_encoder(reranker_profile)
        retriever = reranker_from_memories(
            runner.memories,
            base=dense,
            scorer=scorer,
            candidate_k=args.reranker_candidate_k,
        )
        final_experiment_id = f"{args.candidate_id}+{args.reranker_candidate_id}"
        provider_label = "sentence_transformers_cross_encoder_local_eval"
        model_name = args.reranker_model_name
        model_revision = args.reranker_model_revision
        instruction_id = args.reranker_instruction_id
        instruction_text = reranker_instruction
        backend_label = "evaluation_rerank"
        backend_params = {
            "base_candidate_id": args.candidate_id,
            "base_model_name": args.model_name,
            "base_model_revision": args.model_revision,
            "base_instruction_id": args.instruction_id,
            "base_instruction_sha256": prep.query_template_sha256,
            "base_dimension": prep.vector_dimension,
            "candidate_k": args.reranker_candidate_k,
            "corpus_memory_count": prep.active_memory_count,
            "warm_repeats": args.warm_repeats,
        }
        extra["reranker_load"] = asdict(load_stats)

    manifest = build_blind_manifest(
        runner=runner,
        experiment_id=final_experiment_id,
        git_commit=args.git_commit,
        provider_label=provider_label,
        model_name=model_name,
        model_revision=model_revision,
        instruction_id=instruction_id,
        instruction_text=instruction_text,
        dimension=prep.vector_dimension,
        normalized=True,
        document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
        backend_label=backend_label,
        backend_params=backend_params,
    )
    evidence = run_blind_rankings(
        runner,
        retriever,
        manifest,
        k=10,
        warm_repeats=args.warm_repeats,
    )
    evidence.update(extra)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(evidence_json(evidence), encoding="utf-8")
    print(f"blind runner sha256: {runner.runner_sha256}")
    print(f"experiment: {final_experiment_id}")
    print(f"ranking evidence: {out_path}")
    print("quality metrics intentionally unavailable on the model-execution side")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
