# PA1 — Pinned Qwen Model Acquisition

Status: explicit acquisition helper prepared; Windows execution pending.

Date: 2026-08-29

## Fixed model revisions

PA1 open development will start from these immutable Hugging Face revisions:

| Role | Model | Full revision |
|---|---|---|
| embedding | `Qwen/Qwen3-Embedding-0.6B` | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` |
| reranker | `Qwen/Qwen3-Reranker-0.6B` | `e61197ed45024b0ed8a2d74b80b4d909f1255473` |

The revisions are intentionally full commit SHAs. Do not substitute `main`, `latest`, or a mutable
Ollama tag for a recorded experiment.

## Explicit acquisition boundary

`scripts/acquire_pa1_qwen_models.py` is a deliberate setup command. It may access Hugging Face only
when the operator invokes it. Normal Brain Twin startup, capture, search, reindex, tests, and the
local candidate runner do not import or call it.

The acquisition helper:

1. validates every configured revision as a full 40-character SHA;
2. asks Hugging Face to resolve that exact revision;
3. refuses to download if the resolved SHA differs;
4. downloads the exact snapshot to a repo-external local model directory;
5. writes a small local `brain_twin_model_pin.json` containing only role/repo/revision/time/runtime
   policy; no token and no local path are persisted in that manifest.

Windows default store:

```text
%LOCALAPPDATA%\BrainTwin\models
```

## Windows preparation

Use a dedicated evaluation environment rather than adding ML dependencies to production
`requirements.txt` before the experiment is accepted.

The initial compatibility target is Windows x86-64 / Python 3.12. Sentence Transformers 5.4.1 is a
conservative first runtime for the Qwen3 CrossEncoder path; PyTorch 2.13.0 has a Windows CPython 3.12
wheel. This top-level choice is still a **smoke-test target**, not the final transitive lock. After a
clean Windows install and model-load smoke test succeeds, record the full `pip freeze`/platform and
freeze the accepted evaluation runtime before comparing quality/latency.

Example isolated setup shape (execute on the Windows evaluation machine, not in production):

```powershell
cd "$HOME\Documents\brain-twin-dev\brain-twin-2"
py -3.12 -m venv .venv-pa1-eval
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv-pa1-eval\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install "torch==2.13.0" "sentence-transformers==5.4.1" "huggingface-hub==1.28.0"
```

If dependency resolution or Qwen loading fails, stop and record the failure rather than silently
changing versions mid-comparison.

## Acquire

```powershell
python scripts/acquire_pa1_qwen_models.py --role both
```

After successful acquisition, run the local-only pipeline using the printed directories and the
same full revisions. The evaluator itself loads with `local_files_only=True`.

## Evidence required before the first quality sweep

Record:

- Windows version / architecture;
- Python version;
- CPU and logical core count;
- available RAM;
- `pip freeze`;
- exact model revisions;
- model-load success/failure;
- model directory disk sizes;
- whether any `trust_remote_code` opt-in was required.

Only after that environment is frozen should the Qwen English/Japanese/no-instruction comparison
begin.
