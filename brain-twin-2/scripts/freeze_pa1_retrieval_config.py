'''Freeze a PA1 retrieval-configuration hash before any formal blind runner is introduced.'''
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain_twin.embedding_document import DOCUMENT_TEMPLATE_VERSION  # noqa: E402
from brain_twin_eval.acceptance import retrieval_config_sha256  # noqa: E402
from brain_twin_eval.formal_config import (  # noqa: E402
    DENSE_BACKEND_LABEL,
    DENSE_PROVIDER_LABEL,
    RERANK_BACKEND_LABEL,
    RERANK_PROVIDER_LABEL,
    retrieval_config_mapping,
)
from brain_twin_eval.formal_config_code_pin import (  # noqa: E402
    dense_backend_params_with_code_pin,
    rerank_backend_params_with_code_pins,
)
from brain_twin_eval.privacy_paths import require_outside_repository  # noqa: E402


def _read_text(path: str | None, default: str) -> str:
    if path is None:
        return default
    return Path(path).read_text(encoding="utf-8").rstrip("\r\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--model-code-repo-id")
    parser.add_argument("--model-code-revision")
    parser.add_argument("--instruction-id", required=True)
    parser.add_argument("--query-template-file")
    parser.add_argument("--document-template-file")
    parser.add_argument("--dimension", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)

    parser.add_argument("--reranker-model-name")
    parser.add_argument("--reranker-model-revision")
    parser.add_argument("--reranker-code-repo-id")
    parser.add_argument("--reranker-code-revision")
    parser.add_argument(
        "--reranker-instruction-id",
        default="brain-twin-memory-relevance-v1",
    )
    parser.add_argument("--reranker-instruction-file")
    parser.add_argument("--reranker-candidate-k", type=int, default=50)
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[2]
    out_path = require_outside_repository(
        args.out,
        repository_root,
        label="frozen retrieval configuration",
    )

    query_template = _read_text(args.query_template_file, "{query}")
    document_template = _read_text(args.document_template_file, "{document}")

    reranker_requested = any((args.reranker_model_name, args.reranker_model_revision))
    if reranker_requested:
        if not args.reranker_model_name or not args.reranker_model_revision:
            raise SystemExit("reranker model name and revision must be supplied together")
        reranker_instruction = _read_text(
            args.reranker_instruction_file,
            "Given a personal memory retrieval query, identify passages that are relevant to the user's intended recollection.",
        )
        backend_params = rerank_backend_params_with_code_pins(
            base_model_name=args.model_name,
            base_model_revision=args.model_revision,
            base_instruction_id=args.instruction_id,
            base_query_template=query_template,
            base_document_template=document_template,
            base_dimension=args.dimension,
            base_normalized=True,
            candidate_k=args.reranker_candidate_k,
            base_code_repo_id=args.model_code_repo_id,
            base_code_revision=args.model_code_revision,
            reranker_code_repo_id=args.reranker_code_repo_id,
            reranker_code_revision=args.reranker_code_revision,
        )
        config = retrieval_config_mapping(
            provider_label=RERANK_PROVIDER_LABEL,
            model_name=args.reranker_model_name,
            model_revision=args.reranker_model_revision,
            instruction_id=args.reranker_instruction_id,
            instruction_text=reranker_instruction,
            dimension=args.dimension,
            normalized=True,
            document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
            backend_label=RERANK_BACKEND_LABEL,
            backend_params=backend_params,
        )
        kind = "dense_plus_reranker"
    else:
        if args.reranker_code_repo_id or args.reranker_code_revision:
            raise SystemExit("reranker code pin supplied without a reranker model")
        backend_params = dense_backend_params_with_code_pin(
            query_template=query_template,
            document_template=document_template,
            code_repo_id=args.model_code_repo_id,
            code_revision=args.model_code_revision,
        )
        config = retrieval_config_mapping(
            provider_label=DENSE_PROVIDER_LABEL,
            model_name=args.model_name,
            model_revision=args.model_revision,
            instruction_id=args.instruction_id,
            instruction_text=query_template,
            dimension=args.dimension,
            normalized=True,
            document_template_version=str(DOCUMENT_TEMPLATE_VERSION),
            backend_label=DENSE_BACKEND_LABEL,
            backend_params=backend_params,
        )
        kind = "dense"

    config_sha = retrieval_config_sha256(config)
    payload = {
        "schema": 2,
        "kind": kind,
        "retrieval_config_sha256": config_sha,
        "configuration": config,
        "contains_blind_query_text": False,
        "contains_model_local_path": False,
        "implementation_dependency_bound": any(
            key.endswith("implementation_dependency") for key in backend_params
        ),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"retrieval config sha256: {config_sha}")
    print(f"frozen config: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
