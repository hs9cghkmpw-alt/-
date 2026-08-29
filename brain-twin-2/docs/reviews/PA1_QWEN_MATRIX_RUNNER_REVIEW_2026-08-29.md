# PA1 Qwen Matrix Runner — External/Self Review Handoff

Date: 2026-08-29

## Verdict

**GO for Windows open-development execution.**

This is not PA1 production-model acceptance and does not activate Production Vector Search.

## Evidence

Initial one-command matrix runner:

- commit: `ae20f634f9a112817c3a835ed98665b1e5c0979c`
- Actions run: `33223026401`
- job: `99020926400`
- exact-SHA checkout confirmed
- result: `394 passed in 8.54s`

Evidence-isolation hardening:

- commit: `af8f7186053f4e7df2d0219e880367cd9caf6e83`
- Actions run: `33223233939`
- job: `99021558363`
- exact-SHA checkout confirmed
- result: `396 passed in 8.50s`

Non-blocking CI warning: GitHub Actions reports Node 20 deprecation for the current action versions and
runs them on Node 24. This does not affect the Python test result.

## What is ready

`scripts/run_pa1_qwen_matrix.ps1` now performs, on the Windows evaluation machine:

1. clean tracked-worktree guard;
2. exact Git SHA capture;
3. isolated Python 3.12 evaluation environment;
4. reviewed evaluation dependency install;
5. explicit immutable Qwen snapshot acquisition;
6. fresh per-run evidence directory;
7. 1024d English/Japanese/no-instruction comparison;
8. 768/512/256 sweep for only the winning instruction;
9. deterministic dense winner selection;
10. Qwen3-Reranker-0.6B OFF/ON comparison on a frozen top-50 candidate pool;
11. JSON/Markdown matrix summary.

The summarizer rejects mixed dataset identity, mixed Git commits, and duplicate candidate IDs.
A non-empty custom output directory is rejected, and the default output is unique by Git SHA prefix
plus UTC timestamp. This prevents prior-run evidence from leaking into a new winner decision.

## Safety boundary

- evaluation only;
- no real user Vault access;
- no production provider/backend/reranker activation;
- normal Brain Twin runtime/reindex remains network-free;
- model acquisition is an explicit operator-only command path;
- models remain outside the repository;
- committed open judgements are development evidence only, never formal blind acceptance.

## Next action

On the Windows evaluation machine, sync `brain-twin-dev` and run:

```powershell
git switch brain-twin-dev
git pull --ff-only origin brain-twin-dev
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_qwen_matrix.ps1
```

After completion, review the generated `matrix_summary.md`, per-slice reports, environment evidence,
and failures before deciding whether Qwen advances against BGE-M3 / multilingual-e5 / Nomic / GTE
challengers.
