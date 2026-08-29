# Organizer Windows Bootstrap & First Smoke

Status: **evaluation-only**. This does not authorize production Organizer integration.

## Why this exists

Qwen3.5 uses the current Transformers multimodal processor/model family even when Brain Twin supplies text-only organizer inputs. The Windows evaluation environment is therefore isolated from Brain Twin production dependencies and frozen before model evidence is collected.

The runtime follows the official Qwen3.5 direct chat-template tokenization path:

- `AutoProcessor`
- `AutoModelForMultimodalLM`
- `apply_chat_template(..., tokenize=True, return_dict=True, return_tensors="pt")`

Brain Twin additionally fixes `enable_thinking=false` and greedy `do_sample=false` for deterministic metadata evaluation. This deterministic policy is part of the Organizer config hash and must not be silently changed after acceptance policy freeze.

## Frozen Windows evaluation packages

`evaluation_profiles/organizer_windows_requirements_v1.txt` currently pins:

- torch 2.13.0
- torchvision 0.28.0
- transformers 5.16.1
- huggingface-hub 1.28.0
- Pillow 12.3.0

These packages are intentionally **not** added to production `requirements.txt`.

## First command on the Windows evaluation PC

From `brain-twin-2`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_organizer_eval_windows.ps1
```

The setup script:

1. refuses the wrong branch;
2. refuses a dirty worktree;
3. performs `git pull --ff-only` unless `-SkipPull` is explicitly supplied;
4. requires Python 3.12;
5. creates `.venv-organizer`;
6. installs only the frozen evaluation requirements;
7. runs a fail-closed API/version preflight.

No model is downloaded by the setup script.

## First model smoke: only Qwen3.5-0.8B

```powershell
.\scripts\smoke_organizer_qwen08_windows.ps1
```

This intentionally downloads only the pinned Qwen3.5-0.8B snapshot, then runs an 8-sample open smoke with determinism checks. Model execution is forced offline/local-files-only after acquisition.

Do **not** download 2B/4B models merely because the environment installation succeeded. First inspect whether 0.8B actually loads, generates strict JSON, stays deterministic, and produces plausible latency/RSS evidence.

## After a clean 0.8B smoke

Only then acquire 2B and run the core comparison:

```powershell
.\.venv-organizer\Scripts\python.exe scripts\acquire_organizer_models.py --candidate-id qwen3.5-2b
.\.venv-organizer\Scripts\python.exe scripts\run_organizer_open_matrix.py --tier core
```

The full core run uses all 192 open-v2 synthetic organizer samples. It is development evidence, not formal blind acceptance.

## Stop conditions

Stop rather than improvising if any of these occur:

- exact model SHA mismatch;
- package/API preflight failure;
- unexpected remote-code request;
- non-local model access during execution;
- loader crash;
- repeated invalid JSON / Markdown-fenced output that prevents meaningful scoring;
- nondeterministic repeat output under the frozen greedy settings;
- memory/RAM pressure severe enough to destabilize the PC.

Capture the error/output and review it before changing versions, prompts, generation settings or model code. Any such change affects experiment identity and must be deliberate.
