#!/usr/bin/env python3
"""Fail-closed preflight for the Windows organizer evaluation environment."""
from __future__ import annotations

from importlib import metadata
import platform
import sys


EXPECTED = {
    "torch": "2.13.0",
    "torchvision": "0.28.0",
    "transformers": "5.16.1",
    "huggingface-hub": "1.28.0",
    "Pillow": "12.3.0",
}


def main() -> int:
    failures: list[str] = []
    if platform.system() != "Windows":
        failures.append(f"expected Windows, got {platform.system()}")
    if sys.version_info[:2] != (3, 12):
        failures.append(f"expected Python 3.12, got {platform.python_version()}")
    machine = platform.machine().lower()
    if machine not in {"amd64", "x86_64"}:
        failures.append(f"expected x86-64/AMD64, got {platform.machine()}")

    versions: dict[str, str] = {}
    for package, expected in EXPECTED.items():
        try:
            actual = metadata.version(package)
        except metadata.PackageNotFoundError:
            failures.append(f"missing package: {package}=={expected}")
            continue
        versions[package] = actual
        if actual != expected:
            failures.append(f"version mismatch: {package} expected {expected}, got {actual}")

    try:
        import torch
        import transformers
        from transformers import AutoModelForMultimodalLM, AutoProcessor
    except Exception as exc:
        failures.append(f"organizer runtime imports failed: {type(exc).__name__}: {exc}")
    else:
        if not hasattr(torch, "inference_mode"):
            failures.append("torch.inference_mode is unavailable")
        if AutoProcessor is None or AutoModelForMultimodalLM is None:
            failures.append("Qwen3.5 official AutoProcessor/AutoModelForMultimodalLM API is unavailable")
        if getattr(transformers, "__version__", None) != EXPECTED["transformers"]:
            failures.append("transformers module version does not match frozen environment")

    print(f"platform={platform.platform()}")
    print(f"python={platform.python_version()}")
    for package in sorted(versions):
        print(f"{package}={versions[package]}")

    if failures:
        for failure in failures:
            print(f"[NG] {failure}", file=sys.stderr)
        return 2
    print("[OK] organizer Windows evaluation environment is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
