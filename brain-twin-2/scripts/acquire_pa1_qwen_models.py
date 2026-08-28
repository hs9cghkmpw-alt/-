"""Explicitly acquire the pinned PA1 Qwen models into a local model store.

This is the only PA1 helper that may access Hugging Face. Runtime evaluation remains
local-files-only. The caller must invoke this script deliberately; nothing imports or
runs it during normal Brain Twin startup/search/reindex.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

QWEN3_EMBEDDING_REPO = "Qwen/Qwen3-Embedding-0.6B"
QWEN3_EMBEDDING_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
QWEN3_RERANKER_REPO = "Qwen/Qwen3-Reranker-0.6B"
QWEN3_RERANKER_REVISION = "e61197ed45024b0ed8a2d74b80b4d909f1255473"


@dataclass(frozen=True)
class ModelPin:
    role: str
    repo_id: str
    revision: str
    directory_name: str


PINS = (
    ModelPin(
        role="embedding",
        repo_id=QWEN3_EMBEDDING_REPO,
        revision=QWEN3_EMBEDDING_REVISION,
        directory_name="Qwen3-Embedding-0.6B_97b0c614",
    ),
    ModelPin(
        role="reranker",
        repo_id=QWEN3_RERANKER_REPO,
        revision=QWEN3_RERANKER_REVISION,
        directory_name="Qwen3-Reranker-0.6B_e61197ed",
    ),
)


def default_model_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "BrainTwin" / "models"
    return Path.home() / ".local" / "share" / "brain-twin" / "models"


def _validate_revision(value: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"revision must be a full lowercase 40-char commit SHA: {value!r}")


def acquire_one(
    pin: ModelPin,
    root: Path,
    *,
    repo_info_fn: Callable[..., object],
    snapshot_download_fn: Callable[..., str],
) -> Path:
    _validate_revision(pin.revision)
    target = root / pin.directory_name
    target.mkdir(parents=True, exist_ok=True)

    info = repo_info_fn(repo_id=pin.repo_id, revision=pin.revision)
    resolved = getattr(info, "sha", None)
    if resolved != pin.revision:
        raise RuntimeError(
            f"Hugging Face resolved {pin.repo_id}@{pin.revision} to unexpected SHA {resolved!r}"
        )

    downloaded = Path(
        snapshot_download_fn(
            repo_id=pin.repo_id,
            revision=pin.revision,
            local_dir=str(target),
        )
    ).resolve()
    if downloaded != target.resolve():
        raise RuntimeError(
            f"snapshot_download returned unexpected destination {downloaded}; expected {target.resolve()}"
        )

    manifest = {
        "schema": 1,
        "role": pin.role,
        "repo_id": pin.repo_id,
        "revision": pin.revision,
        "acquired_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_policy": "evaluation loads with local_files_only=True",
    }
    (target / "brain_twin_model_pin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _selected_pins(role: str) -> tuple[ModelPin, ...]:
    if role == "both":
        return PINS
    return tuple(pin for pin in PINS if pin.role == role)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=default_model_root(),
        help="local model root; defaults to %%LOCALAPPDATA%%\\BrainTwin\\models on Windows",
    )
    parser.add_argument(
        "--role",
        choices=("embedding", "reranker", "both"),
        default="both",
        help="which pinned model(s) to acquire",
    )
    args = parser.parse_args()

    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        print(
            "[NG] huggingface-hub is not installed. Create an isolated acquisition/evaluation "
            "environment and install the reviewed version before running this explicit download.",
            file=sys.stderr,
        )
        return 2

    api = HfApi()
    args.root.mkdir(parents=True, exist_ok=True)
    print(f"model root: {args.root.resolve()}")
    for pin in _selected_pins(args.role):
        print(f"acquiring {pin.repo_id}@{pin.revision}")
        path = acquire_one(
            pin,
            args.root,
            repo_info_fn=api.model_info,
            snapshot_download_fn=snapshot_download,
        )
        print(f"[OK] {pin.role}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
