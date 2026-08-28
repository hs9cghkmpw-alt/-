"""Run a local-only PA1 dense candidate, optionally with a local CrossEncoder reranker.

No model is downloaded by this script. Every model path must already exist locally.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin.embedding_document import DOCUMENT_TEMPLATE_VERSION  # noqa: E402
from brain_twin_eval.candidate_runtime import (  # noqa: E402
    DenseCandidateProfile,
    RerankerCandidateProfile,
    RerankingRetriever,
    load_local_cross_encoder,
    prepare_dense_candidate,
    stats_json,
)
from brain_twin_eval.dataset import dataset_from_mapping  # noqa: E402
from brain_twin_eval.manifest import build_manifest, manifest_json  # noqa: E402
from brain_twin_eval.open_gold_v2 import build_open_gold_v2  # noqa: E402
from brain_twin_eval.report import report_json, report_markdown  # noqa: E402
from brain_twin_eval.runner import evaluate_retriever  # noqa: E402
from brain_twin_eval.statistics import paired_metric_delta  # noqa: E402


def _read_text(path: str | None, default: str) -> str:
    if path is None:
        return default
    return Path(path).read_text(encoding="utf-8").rstrip("\r\n")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--split", choices=("dev", "blind"), default="dev")
    parser.add_argument("--warm-repeats", type=int, default=3)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--out-dir", required=True)

    parser.add_argument("--reranker-candidate-id")
    parser.add_argument("--reranker-model-path")
    parser.add_argument("--reranker-model-name")
    parser.add_argument("--reranker-model-revision")
    parser.add_argument("--reranker-instruction-id", default="brain-twin-memory-relevance-v1")
    parser.add_argument("--reranker-instruction-file")
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-candidate-k", type=int, default=50)
    parser.add_argument("--reranker-warm-repeats", type=int, default=0)
    parser.add_argument("--reranker-trust-remote-code", action="store_true")
    return parser.parse_args()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = _args()
    dataset = dataset_from_mapping(build_open_gold_v2())
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

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
    dense, prep = prepare_dense_candidate(dataset, dense_profile)
    dense_run = evaluate_retriever(
        dataset,
        dense,
        split=args.split,
        k=10,
        warm_repeats=args.warm_repeats,
    )
    dense_manifest = build_manifest(
        dataset=dataset,
        experiment_id=args.candidate_id,
        git_commit=args.git_commit,
        provider_label="sentence_transformers_local_eval",
        model_name=args.model_name,
        model_revision=args.model_revision,
        instruction_id=args.instruction_id,
        instruction_text=query_template,
        dimension=prep.vector_dimension,
        normalized=True,
        document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
        backend_label="evaluation_exact_dense",
        backend_params={
            "split": args.split,
            "warm_repeats": args.warm_repeats,
            "corpus_memory_count": prep.active_memory_count,
        },
        random_seed=0,
    )
    _write(out / "dense_preparation.json", stats_json(prep) + "\n")
    _write(out / "dense_manifest.json", manifest_json(dense_manifest) + "\n")
    _write(out / "dense_report.json", report_json(dense_run, dense_manifest))
    _write(out / "dense_report.md", report_markdown(dense_run, dense_manifest))

    reranker_requested = any(
        value
        for value in (
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
        reranked = RerankingRetriever(
            dataset=dataset,
            base=dense,
            scorer=scorer,
            candidate_k=args.reranker_candidate_k,
        )
        reranked_run = evaluate_retriever(
            dataset,
            reranked,
            split=args.split,
            k=10,
            warm_repeats=args.reranker_warm_repeats,
        )
        reranker_manifest = build_manifest(
            dataset=dataset,
            experiment_id=f"{args.candidate_id}+{args.reranker_candidate_id}",
            git_commit=args.git_commit,
            provider_label="sentence_transformers_cross_encoder_local_eval",
            model_name=args.reranker_model_name,
            model_revision=args.reranker_model_revision,
            instruction_id=args.reranker_instruction_id,
            instruction_text=reranker_instruction,
            dimension=prep.vector_dimension,
            normalized=True,
            document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
            backend_label="evaluation_rerank",
            backend_params={
                "base_candidate_id": args.candidate_id,
                "base_model_name": args.model_name,
                "base_model_revision": args.model_revision,
                "candidate_k": args.reranker_candidate_k,
                "split": args.split,
                "warm_repeats": args.reranker_warm_repeats,
            },
            random_seed=0,
        )
        _write(out / "reranker_load.json", stats_json(load_stats) + "\n")
        _write(out / "reranker_manifest.json", manifest_json(reranker_manifest) + "\n")
        _write(out / "reranked_report.json", report_json(reranked_run, reranker_manifest))
        _write(out / "reranked_report.md", report_markdown(reranked_run, reranker_manifest))

        deltas = {}
        for metric in ("recall_at_5", "mrr_at_10", "ndcg_at_10", "must_hit_at_5", "false_positive_at_5"):
            try:
                deltas[metric] = asdict(paired_metric_delta(dense_run, reranked_run, metric))
            except ValueError:
                continue
        _write(
            out / "reranker_delta.json",
            json.dumps(deltas, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        )

    print(f"dataset: {dataset.version}")
    print(f"dense candidate: {args.candidate_id}")
    print(f"output: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
