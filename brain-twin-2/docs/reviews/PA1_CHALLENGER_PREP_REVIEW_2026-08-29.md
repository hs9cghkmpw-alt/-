# PA1 Challenger Preparation Review — 2026-08-29

Verdict: **GO for PC-free challenger preparation; STOP before claiming model selection or production activation.**

Review type: implementation-side/self-review and evidence audit. This is not the required independent final evidence review.

## Scope reviewed

- `evaluation_profiles/challenger_catalog_v1.json`
- generic candidate acquisition/planning
- Qwen + standard challenger Windows orchestration
- combined open-development summary path
- custom-code dependency pinning for Nomic/GTE
- isolated offline remote-code smoke path
- formal retrieval identity binding for custom-code revisions
- exact-SHA CI evidence

Production `brain_twin/`, real Vault data and production embedding configuration were out of scope and were not changed by this preparation series.

## Findings

### GO — immutable candidate identity

All catalogued models have explicit 40-character immutable revisions. BGE-M3, E5-base, E5-large-instruct and MiniLM are marked ready for the reviewed standard local Sentence Transformers path.

Nomic and GTE also pin the separate repositories/revisions that provide their custom implementation code. Their catalog state is intentionally `requires_remote_code_smoke`, so they cannot silently enter normal evaluation.

### GO — fail-closed remote-code path

The remote-code smoke is separated from normal model comparison. It requires pinned local artifacts/code revision, runs offline, checks basic encode output/dimension/normalization evidence, and does not mutate the candidate catalog or grant formal/production acceptance.

A successful smoke is evidence for explicit review only.

### GO — comparison isolation

The Windows orchestration keeps Qwen-specific instruction/dimension/reranker experiments distinct while allowing standard challengers to run under the same open benchmark and evaluator Git identity. The final open-development summary rejects mixed dataset/Git identities and duplicate candidate IDs.

### GO — formal identity coverage

For a future formal cycle, behavior-changing custom-code dependencies can be incorporated into the frozen retrieval configuration identity. This closes the gap where model weights could be pinned while executable custom code remained mutable.

### Corrected issue — RSS API call

Commit `52a11a882a381952234582f5ead97aa823ed0755` failed CI during collection because the new smoke helper imported a non-existent RSS helper name. The repository already exposes `peak_rss_reading()`.

The correction at `731fab69d24086330b5c9514a0ddd1e8da44b59f` uses `peak_rss_reading().bytes` and the exact-SHA CI passed.

This was an evaluation-tooling integration error, not a production retrieval defect.

## Evidence

Challenger orchestration:

- commit: `a5f1448490586cff7579b11c69aa5f0d3b0f0960`
- Actions run: `33229610378`
- result: success
- tests: **466 passed**

Remote-code isolation initial attempt:

- commit: `52a11a882a381952234582f5ead97aa823ed0755`
- Actions run: `33229774485`
- result: failure during test collection
- cause: RSS helper naming mismatch

Corrective commit:

- commit: `731fab69d24086330b5c9514a0ddd1e8da44b59f`
- Actions run: `33229832697`
- job: `99040554640`
- exact checked-out SHA matched commit
- result: success
- tests: **473 passed in 42.39s**

## Remaining blockers

1. No real embedding/reranker model has been executed on the target Windows machine yet.
2. Windows dependency/runtime freeze and real CPU/RAM/latency/disk measurements remain missing.
3. Nomic/GTE custom-code smoke has not run on Windows.
4. Open-development results do not select a production profile by themselves.
5. Genuine private held-out dataset, independent judging/adjudication, predeclared resource budgets and a sealed formal blind cycle remain required.
6. Independent final evidence review remains required before PA1 COMPLETE.

## Next action

When Windows is available, use a clean checkout and run:

```powershell
git switch brain-twin-dev
git pull --ff-only origin brain-twin-dev
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_full_open_matrix.ps1
```

Review the combined summary and raw evidence before any model/profile freeze. Run Nomic/GTE only through the separate isolated smoke first.

Do not start production provider/reranker/ANN activation solely from this GO.
