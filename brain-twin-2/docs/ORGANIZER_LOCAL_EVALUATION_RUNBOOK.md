# Organizer Local Evaluation Runbook

Status: **evaluation-only; production organizer integration remains unauthorized**

This runbook executes the already-reviewed organizer benchmark against immutable local model snapshots. It does not read or write the production Vault.

## Matrix

The committed matrix is `evaluation_profiles/organizer_model_matrix_v1.json`.

- Core: `qwen3.5-0.8b`, `qwen3.5-2b`
- Extended: `qwen3.5-4b`, `qwen3-4b-instruct-2507`
- Blocked from direct automation: `phi-4-mini-instruct`, `gemma-3-4b-it`

The core tier is intentionally small. Measure whether 0.8B/2B is sufficient before paying the download, RAM and latency cost of 4B models.

## Security and reproducibility boundaries

Acquisition and execution are separate steps.

Acquisition:

- resolves the exact catalog commit SHA against Hugging Face;
- refuses a resolved SHA mismatch before download;
- stores snapshots in the user-local Brain Twin model directory;
- writes `brain_twin_organizer_pin.json` with candidate/revision/runtime policy;
- refuses gated, research-only and remote-code candidates.

Execution:

- sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`;
- loads only an acquired local path with `local_files_only=True`;
- requires `trust_remote_code=False` for direct runs;
- verifies the pin manifest before loading;
- forces CPU evaluation for the Windows resource comparison;
- uses deterministic generation (`temperature=0`, `do_sample=false`, `enable_thinking=false`);
- records the tokenizer/processor chat-template SHA, prompt SHA, schema SHA, exact model revision, runtime versions and generation parameters in the organizer config hash;
- retains the model's raw generated text. Markdown fences or explanatory prose are not repaired; the strict evaluator must count them as schema failures.

## Isolated evaluation environment

Do not add heavyweight model packages to Brain Twin production requirements merely to run this benchmark. Use a dedicated virtual environment with compatible pinned versions of:

- `torch`
- `transformers`
- `huggingface-hub`

The exact installed runtime versions are recorded in run evidence. Freeze final versions before formal blind execution.

## 1. Sync and verify the repository

```powershell
git checkout brain-twin-dev
git pull --ff-only
git status --short
git rev-parse HEAD
```

Do not run a formal comparison from a dirty or unexpected checkout.

## 2. Acquire only the core tier

Network is allowed only in this explicit acquisition step:

```powershell
python scripts/acquire_organizer_models.py --tier core
```

Default Windows location:

```text
%LOCALAPPDATA%\BrainTwin\models
```

Expected first-stage downloads are the 0.8B and 2B Qwen3.5 snapshots only. The 4B models are not fetched unless `--tier extended` or `--tier all` is explicitly requested.

## 3. Optional short smoke

Execution is offline/local-only:

```powershell
python scripts/run_organizer_open_matrix.py --tier core --sample-limit 8 --determinism-samples 2
```

A sample-limited run is marked as smoke evidence and must not be used to choose a model or freeze acceptance gates.

## 4. Full open-v2 comparison

```powershell
python scripts/run_organizer_open_matrix.py --tier core
```

Default result location:

```text
%LOCALAPPDATA%\BrainTwin\evaluation\organizer\organizer-open-v2\
```

Each candidate emits:

- `predictions.jsonl`
- `quality_report.json`
- `runtime_evidence.json`
- `organizer_run_config.json`

The run directory also emits `matrix_summary.json`.

## 5. Review before extended models

Do not pick a winner from aggregate F1 alone. Review, in order:

1. schema-valid rate;
2. entity hallucination rate;
3. fabricated/wrong date behavior;
4. memory-worthy and Memory Type correctness;
5. entity/topic/link quality;
6. deterministic repeat behavior;
7. Windows p95 latency;
8. peak RSS and model disk size.

A smaller model is preferred only if it clears the same safety/quality gates. A larger model is justified only by material organizer-quality gains.

## 6. Extended tier only if justified

```powershell
python scripts/acquire_organizer_models.py --tier extended
python scripts/run_organizer_open_matrix.py --tier extended
```

`phi-4-mini-instruct` remains outside this direct path because its reviewed catalog status requires an isolated remote-code smoke. `gemma-3-4b-it` remains gated/research-only.

## Formal blind remains separate

Open-v2 is development evidence. After candidate configuration and Windows budgets are frozen, use the Organizer Formal Blind protocol. Never tune against held-out gold and never place private blind artifacts inside the repository.

Production `brain_twin/` must remain unchanged until independent review and explicit production integration authorization.
