# PA1 — Qwen Windows Matrix Runner

Status: one-command Windows open-benchmark runner prepared; real Windows execution pending.

Date: 2026-08-29

## Purpose

This runner converts the PA1 preparation work into one reproducible Windows CPU experiment. It is
**development evidence only**: the committed v2 benchmark has open judgements, so its winner must not
be treated as formal blind acceptance or Production Vector Search activation.

Entry point:

```text
scripts/run_pa1_qwen_matrix.ps1
```

## What one run does

1. refuses to run with tracked working-tree changes;
2. records the exact Git commit;
3. creates/reuses `.venv-pa1-eval` with Python 3.12;
4. installs the reviewed evaluation-only runtime (`torch==2.13.0`,
   `sentence-transformers==5.4.1`, `huggingface-hub==1.28.0`);
5. explicitly acquires the pinned Qwen embedding and reranker snapshots unless `-SkipAcquire` is
   supplied;
6. records non-identifying machine/runtime evidence and `pip freeze` under ignored
   `.evaluation-results/`;
7. compares Qwen3-Embedding-0.6B at 1024 dimensions with:
   - Brain Twin task-specific English instruction;
   - equivalent Japanese instruction;
   - no instruction;
8. advances only the winning instruction to 768 / 512 / 256 dimensions;
9. selects the open-development dense winner deterministically;
10. compares Qwen3-Reranker-0.6B OFF vs ON using that exact dense profile and a frozen top-50
    candidate pool;
11. produces machine-readable and human-readable matrix summaries.

## Selection rule

The open-development ordering is deliberately deterministic:

1. nDCG@10;
2. must-hit@5;
3. MRR@10;
4. Recall@5;
5. lower false-positive@5;
6. lower warm p95 latency;
7. candidate ID as a final deterministic tie-break.

This rule is for deciding what to test next. It is **not** a production acceptance gate.

## Run from a Windows checkout

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_qwen_matrix.ps1
```

The script locates `brain-twin-2` from its own path, so it does not depend on a particular Windows
username or checkout directory.

Useful repeat-run options:

```powershell
# Reuse already installed packages and already acquired model snapshots.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_qwen_matrix.ps1 -SkipInstall -SkipAcquire

# Reduce repeated timing work while debugging.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_qwen_matrix.ps1 -WarmRepeats 0
```

## Output

Default output root:

```text
brain-twin-2/.evaluation-results/pa1-qwen-matrix/
```

Important files:

- `environment/environment.json` — Git SHA, Python/Windows/CPU/RAM summary and pinned model IDs;
- `environment/pip-freeze.txt` — actual transitive runtime lock evidence;
- each candidate directory — preparation stats, manifest, JSON report, Markdown report;
- `best-dense-plus-reranker/reranked_report.*` — reranker ON evidence;
- `matrix_summary.json` — deterministic machine-readable comparison;
- `matrix_summary.md` — human-readable comparison and open-development winner.

The output root is Git-ignored. Model files remain outside the repository under
`%LOCALAPPDATA%\BrainTwin\models`.

## Safety / reproducibility boundaries

- Normal Brain Twin startup/search/reindex never downloads a model.
- Candidate evaluation uses local model paths and `local_files_only=True`.
- Full immutable Hugging Face revisions are recorded; `main` / `latest` are not accepted evidence.
- No real user Vault is read.
- The run stops on tracked source changes, dependency-install failure, model-acquisition failure,
  missing pins, candidate failure, or summary inconsistency.
- The open v2 benchmark can guide iteration but cannot certify production.

## After this run

Review `matrix_summary.md` plus the per-slice reports. Then:

1. decide whether Qwen embedding merits advancing against BGE-M3 / multilingual-e5 / Nomic / GTE
   challengers;
2. predeclare Windows RAM/latency budgets before the formal blind run;
3. construct/secure the genuinely held-out judgement set;
4. only after those evidence gates consider PA2 production-provider integration.
