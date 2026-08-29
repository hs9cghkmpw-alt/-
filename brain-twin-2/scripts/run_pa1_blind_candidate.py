'''Run one frozen retrieval configuration against a judgement-free formal blind runner.

The model side receives query text but never receives relevance labels. The launch envelope and
clean Git checkout are verified before any model is loaded or blind query is executed.
'''
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin.embedding_document import DOCUMENT_TEMPLATE_VERSION  # noqa: E402
from brain_twin_eval.acceptance import retrieval_config_sha256  # noqa: E402
from brain_twin_eval.blind import payload_sha256  # noqa: E402
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
from brain_twin_eval.formal_config import (  # noqa: E402
    DENSE_BACKEND_LABEL,
    DENSE_PROVIDER_LABEL,
    RERANK_BACKEND_LABEL,
    RERANK_PROVIDER_LABEL,
    dense_backend_params,
    rerank_backend_params,
    retrieval_config_mapping,
)
from brain_twin_eval.launch_envelope import (  # noqa: E402
    envelope_from_mapping,
    envelope_sha256,
    verify_manifest_against_envelope,
)
from brain_twin_eval.privacy_paths import require_outside_repository  # noqa: E402
from brain_twin_eval.repo_identity import require_frozen_repository  # noqa: E402


def _read_text(path: str | None, default: str) -> str:
    if path is None:
        return default
    return Path(path).read_text(encoding="utf-8").rstrip("\r\n")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-package", required=True)
    parser.add_argument("--launch-envelope", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--instruction-id", required=True)
    parser.add_argument("--query-template-file")
    parser.add_argument("--document-template-file")
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--trust-remote-code", action="store_true")
    parser.add_argument("--warm-repeats", type=int, default=30)
    parser.add_argument(
        "--git-commit",
        help="optional compatibility assertion; the actual clean Git HEAD is always verified independently",
    )
    parser.add_argument("--model-artifact-manifest")
    parser.add_argument("--out", required=True)

    parser.add_argument("--reranker-candidate-id")
    parser.add_argument("--reranker-model-path")
    parser.add_argument("--reranker-model-name")
    parser.add_argument("--reranker-model-revision")
    parser.add_argument(
        "--reranker-instruction-id",
        default="brain-twin-memory-relevance-v1",
    )
    parser.add_argument("--reranker-instruction-file")
    parser.add_argument("--reranker-batch-size", type=int, default=8)
    parser.add_argument("--reranker-candidate-k", type=int, default=50)
    parser.add_argument("--reranker-trust-remote-code", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _args()
    repository_root = Path(__file__).resolve().parents[2]
    runner_path = require_outside_repository(
        args.runner_package,
        repository_root,
        label="formal blind runner package",
    )
    envelope_path = require_outside_repository(
        args.launch_envelope,
        repository_root,
        label="formal blind launch envelope",
    )
    out_path = require_outside_repository(
        args.out,
        repository_root,
        label="formal blind ranking evidence",
    )
    if len({runner_path, envelope_path, out_path}) != 3:
        raise SystemExit(
            "runner, launch-envelope and ranking-evidence paths must be distinct"
        )

    runner_raw = json.loads(runner_path.read_text(encoding="utf-8-sig"))
    runner = runner_input_from_mapping(runner_raw)
    envelope = envelope_from_mapping(
        json.loads(envelope_path.read_text(encoding="utf-8-sig"))
    )
    if envelope.runner_sha256 != payload_sha256(runner_raw):
        raise SystemExit(
            "launch envelope does not match this blind runner package"
        )
    if (
        envelope.source_dataset_sha256 != runner.source_dataset_sha256
        or envelope.dataset_version != runner.version
    ):
        raise SystemExit(
            "launch envelope dataset identity does not match this blind runner"
        )

    # Do not trust a caller-supplied SHA. Resolve and verify the real checkout.
    identity = require_frozen_repository(
        repository_root, envelope.evaluator_git_commit
    )
    if args.git_commit is not None and args.git_commit.lower() != identity.head_sha:
        raise SystemExit("--git-commit does not match verified repository HEAD")
    if args.warm_repeats != envelope.expected_warm_repeats:
        raise SystemExit(
            "--warm-repeats does not match the frozen launch envelope"
        )

    if envelope.model_artifact_manifest_sha256 is not None:
        if args.model_artifact_manifest is None:
            raise SystemExit(
                "launch envelope requires --model-artifact-manifest"
            )
        artifact_path = require_outside_repository(
            args.model_artifact_manifest,
            repository_root,
            label="model artifact manifest",
        )
        if _file_sha256(artifact_path) != envelope.model_artifact_manifest_sha256:
            raise SystemExit(
                "model artifact manifest does not match launch envelope"
            )
    elif args.model_artifact_manifest is not None:
        raise SystemExit(
            "model artifact manifest was supplied but is not bound by the launch envelope"
        )

    query_template = _read_text(args.query_template_file, "{query}")
    document_template = _read_text(
        args.document_template_file, "{document}"
    )
    active_memory_count = sum(
        1 for memory in runner.memories if memory.active
    )
    if active_memory_count <= 0:
        raise SystemExit("formal blind runner has no active Memories")

    reranker_requested = any(
        value
        for value in (
            args.reranker_candidate_id,
            args.reranker_model_path,
            args.reranker_model_name,
            args.reranker_model_revision,
        )
    )
    reranker_instruction = None
    if reranker_requested:
        required = {
            "reranker_candidate_id": args.reranker_candidate_id,
            "reranker_model_path": args.reranker_model_path,
            "reranker_model_name": args.reranker_model_name,
            "reranker_model_revision": args.reranker_model_revision,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "missing reranker arguments: " + ", ".join(missing)
            )
        reranker_instruction = _read_text(
            args.reranker_instruction_file,
            "Given a personal memory retrieval query, identify passages that are relevant to the user's intended recollection.",
        )
        frozen_backend_params = rerank_backend_params(
            base_model_name=args.model_name,
            base_model_revision=args.model_revision,
            base_instruction_id=args.instruction_id,
            base_query_template=query_template,
            base_document_template=document_template,
            base_dimension=args.dimension,
            base_normalized=True,
            candidate_k=args.reranker_candidate_k,
        )
        frozen_config = retrieval_config_mapping(
            provider_label=RERANK_PROVIDER_LABEL,
            model_name=args.reranker_model_name,
            model_revision=args.reranker_model_revision,
            instruction_id=args.reranker_instruction_id,
            instruction_text=reranker_instruction,
            dimension=args.dimension,
            normalized=True,
            document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
            backend_label=RERANK_BACKEND_LABEL,
            backend_params=frozen_backend_params,
        )
    else:
        frozen_backend_params = dense_backend_params(
            query_template=query_template,
            document_template=document_template,
        )
        frozen_config = retrieval_config_mapping(
            provider_label=DENSE_PROVIDER_LABEL,
            model_name=args.model_name,
            model_revision=args.model_revision,
            instruction_id=args.instruction_id,
            instruction_text=query_template,
            dimension=args.dimension,
            normalized=True,
            document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
            backend_label=DENSE_BACKEND_LABEL,
            backend_params=frozen_backend_params,
        )

    # Critical invariant: reject any config drift before model load or blind queries.
    frozen_config_sha = retrieval_config_sha256(frozen_config)
    if frozen_config_sha != envelope.expected_retrieval_config_sha256:
        raise SystemExit(
            "requested retrieval configuration does not match frozen launch envelope"
        )

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
    dense, prep = prepare_dense_from_memories(
        runner.memories, dense_profile
    )
    if prep.vector_dimension != args.dimension:
        raise SystemExit(
            "runtime embedding dimension does not match frozen dimension"
        )

    dense_runtime_params = dense_backend_params(
        query_template=query_template,
        document_template=document_template,
        evaluation_k=envelope.evaluation_k,
        warm_repeats=args.warm_repeats,
        active_memory_count=active_memory_count,
    )
    if (
        prep.query_template_sha256
        != dense_runtime_params["query_template_sha256"]
        or prep.document_template_sha256
        != dense_runtime_params["document_template_sha256"]
    ):
        raise SystemExit(
            "runtime template hashes do not match frozen templates"
        )

    retriever = dense
    final_experiment_id = args.candidate_id
    provider_label = DENSE_PROVIDER_LABEL
    model_name = args.model_name
    model_revision = args.model_revision
    instruction_id = args.instruction_id
    instruction_text = query_template
    backend_label = DENSE_BACKEND_LABEL
    backend_params = dense_runtime_params
    extra = {"dense_preparation": asdict(prep)}

    if reranker_requested:
        assert reranker_instruction is not None
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
        final_experiment_id = (
            f"{args.candidate_id}+{args.reranker_candidate_id}"
        )
        provider_label = RERANK_PROVIDER_LABEL
        model_name = args.reranker_model_name
        model_revision = args.reranker_model_revision
        instruction_id = args.reranker_instruction_id
        instruction_text = reranker_instruction
        backend_label = RERANK_BACKEND_LABEL
        backend_params = rerank_backend_params(
            base_candidate_id=args.candidate_id,
            base_model_name=args.model_name,
            base_model_revision=args.model_revision,
            base_instruction_id=args.instruction_id,
            base_query_template=query_template,
            base_document_template=document_template,
            base_dimension=args.dimension,
            base_normalized=True,
            candidate_k=args.reranker_candidate_k,
            evaluation_k=envelope.evaluation_k,
            warm_repeats=args.warm_repeats,
            active_memory_count=active_memory_count,
        )
        extra["reranker_load"] = asdict(load_stats)

    manifest = build_blind_manifest(
        runner=runner,
        experiment_id=final_experiment_id,
        git_commit=identity.head_sha,
        provider_label=provider_label,
        model_name=model_name,
        model_revision=model_revision,
        instruction_id=instruction_id,
        instruction_text=instruction_text,
        dimension=args.dimension,
        normalized=True,
        document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
        backend_label=backend_label,
        backend_params=backend_params,
    )
    verify_manifest_against_envelope(manifest, envelope)

    evidence = run_blind_rankings(
        runner,
        retriever,
        manifest,
        k=envelope.evaluation_k,
        warm_repeats=args.warm_repeats,
    )
    evidence["launch_envelope_sha256"] = envelope_sha256(envelope)
    evidence["repository_identity"] = {
        "head_sha": identity.head_sha,
        "tracked_worktree_clean": identity.tracked_worktree_clean,
    }
    evidence.update(extra)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(evidence_json(evidence), encoding="utf-8")
    print(f"blind runner sha256: {runner.runner_sha256}")
    print(f"launch envelope sha256: {envelope_sha256(envelope)}")
    print(f"retrieval config sha256: {frozen_config_sha}")
    print(f"verified evaluator HEAD: {identity.head_sha}")
    print(f"experiment: {final_experiment_id}")
    print(f"ranking evidence: {out_path}")
    print(
        "quality metrics intentionally unavailable on the model-execution side"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
