# Worklog — PA1 Challenger Preparation — 2026-08-29

## Goal

Finish the PC-free preparation needed to compare Qwen against Brain Twin retrieval challengers without silently changing model/code revisions or mixing evidence across runs.

## Implemented

### Candidate catalog hardening

`evaluation_profiles/challenger_catalog_v1.json` moved to schema 2 and now records:

- immutable model revision;
- loader type;
- native/allowed dimensions;
- maximum sequence length;
- committed query/document template files;
- `trust_remote_code` requirement;
- optional pinned custom-code dependency;
- explicit runtime status.

Ready standard candidates: Qwen embedding/reranker, BGE-M3, multilingual E5 base/large instruct, MiniLM control.

Nomic/GTE remain fail-closed pending isolated Windows custom-code smoke.

### Acquisition / planning / orchestration

Added/updated evaluation-only helpers so model acquisition is explicit while actual evaluation remains local-files-only.

Windows orchestration now supports:

- dedicated Qwen instruction/dimension/reranker matrix;
- standard challenger matrix;
- combined `run_pa1_full_open_matrix.ps1` path producing one open-development summary under a common Git/dataset identity.

### Custom-code isolation

For Nomic/GTE, both model weights and external implementation-code repositories are pinned by full revision.

An isolated offline smoke path checks the exact local artifacts/code revision before any normal evaluation promotion. Smoke output is evidence only and cannot update catalog status automatically.

Formal retrieval identity can bind custom-code revisions so a future sealed run cannot keep model weights fixed while changing executable model code.

## CI sequence

1. `a5f1448490586cff7579b11c69aa5f0d3b0f0960` — `brain-twin-2: pin and orchestrate PA1 challengers`
   - Actions `33229610378`
   - success
   - **466 passed**

2. `52a11a882a381952234582f5ead97aa823ed0755` — `brain-twin-2: isolate PA1 remote-code candidate smoke`
   - Actions `33229774485`
   - failed at test collection
   - cause: the new smoke module referenced a non-existent RSS helper name

3. `731fab69d24086330b5c9514a0ddd1e8da44b59f` — `brain-twin-2: fix PA1 remote-code RSS telemetry call`
   - Actions `33229832697`
   - Job `99040554640`
   - exact checkout SHA matched
   - success
   - **473 passed in 42.39s**

The fix uses the repository's existing `peak_rss_reading().bytes` API.

## Safety / scope

- No real Vault used.
- No production model download/runtime activated.
- No production `brain_twin/` behavior changed by this challenger-preparation series.
- No formal blind run performed.
- No model winner declared.
- No PA2/PA3/production activation implied.

## Handoff

PC-free challenger preparation verdict: **GO**.

Next machine-dependent step:

```powershell
git switch brain-twin-dev
git pull --ff-only origin brain-twin-dev
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_full_open_matrix.ps1
```

After standard matrix evidence is reviewed, run Nomic/GTE through their isolated offline custom-code smoke before considering any explicit catalog/runtime promotion.

Then select a provisional retrieval profile using Japanese retrieval quality plus Windows CPU/RAM/latency/disk evidence, build/freeze the private held-out corpus and budgets, and only then execute one sealed formal blind cycle.
