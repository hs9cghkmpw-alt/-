# Brain Twin 2 — Current State

Last updated: 2026-08-28

## Active development context

- Repository: `hs9cghkmpw-alt/-`
- Project: `brain-twin-2/`
- Branch: `brain-twin-dev`
- Legacy `brain-twin/`: out of scope unless explicitly requested

## Phase status

- Phase 1 — Memory Foundation: **COMPLETE**
- Phase 2 — Automatic Memory Worker / Entity Extraction / Link generation: **COMPLETE**
- Phase 3 — Retrieval: **COMPLETE**
- Phase 4 — Vector Retrieval Core (4A–4D): **GO / COMPLETE**
- Production Vector Search activation: **PENDING**

Phase 4 core completion is not a production-ready Vector Search declaration. A production embedding provider, production ANN backend, and Japanese semantic acceptance run are still pending.

## Production Vector Activation

The technical-selection design received review GO after `c8012c6311bfac8f8f68fdc5a7790d0eeed0a6ac`. The provisional pair remains pinned Qwen3-Embedding-0.6B via direct Sentence Transformers plus a rebuildable FAISS HNSW sidecar, subject to PA1 Japanese quality evidence and PA3 Windows ANN gates.

Design documents:

- `docs/PRODUCTION_VECTOR_ACTIVATION_DESIGN.md`
- `docs/ADR_PRODUCTION_VECTOR_ACTIVATION.md`

## PA1 — Japanese Retrieval Evaluation Harness

Status: **self-review hardening GO for harness code; independent external review pending**.

Initial implementation:

- commit `0f93a92ef9186e6331cc5dce0de416914e488479`
- exact-SHA Actions run `33173098200`: **success**, `354 passed`
- handoff/CI metadata commit `1d4d70fdc26751538788729484aac1cdcc7dc528`
- exact-SHA Actions run `33173303966`: **success**

Self-review hardening implementation:

- implementation commit `5a2851534f9385ff0e4cc90af89195de300f890f`
- exact-SHA Actions run `33177339391`: **success**
- CI environment: Ubuntu 24.04, Python 3.11.16, pytest 9.1.1
- result: **370 passed in 25.25s**
- review record: `docs/reviews/PA1_SELF_REVIEW_2026-08-28.md`

Hardening fixed harness-level gaps without changing production `brain_twin/` code:

1. first-call + 30 warm repeats/query by default, mathematical median/p95/max, rank-drift telemetry, and best-effort process peak RSS;
2. explicit `open` vs `held_out` judgement visibility so committed blind-labelled data cannot be mistaken for formal blind evidence; held-out blind reports redact query/slice/failure diagnostics;
3. canonical dataset hash/split/query-ID checks for ExactScan-vs-ANN oracle comparison;
4. manifest/run dataset identity checks before reporting;
5. deterministic 95% bootstrap CIs and paired candidate-minus-baseline query deltas;
6. broader manifest secret-shape rejection while keeping instruction text hash-only;
7. corrected even-count latency median and added nearest-rank p95.

The committed seed remains intentionally small and synthetic: 36 Memories / 24 queries (15 dev / 9 blind-labelled). Because its judgements are in the repository, its blind-labelled subset is pipeline-test data only, not acceptance-blind data.

PA1 documentation: `docs/JAPANESE_RETRIEVAL_EVALUATION.md`.

### Still required before choosing a model

- expand to roughly 300–500 Memories / 120 queries;
- create a genuinely held-out blind set outside the tuning workspace;
- two-judge calibration/adjudication;
- tokenizer-aware near-512 / 2k / 8k cases;
- predeclare Windows CPU/RAM/latency acceptance budgets;
- run pinned Qwen/BGE-M3/E5/Nomic/GTE/MiniLM candidates and required Qwen instruction/dimension comparisons.

No production model has been downloaded or evaluated yet.

## Last known good production retrieval core

- implementation commit: `68ac6e420332bf87feecb47eb32b67cd84bd4016`
- Windows tests: `321 passed, 1 skipped` (expected POSIX-only resource skip)
- exact-SHA Actions run: `33033340980`, **success**
- Sprint 4D / Phase 4 Vector Retrieval Core: **GO / COMPLETE**

## Next authorized action

**Independent external review of PA1 hardening.** Stop here. Do **not** begin PA2, PA3, PA4, `ask`, Contradiction Detection, Memory Consolidation, smartphone integration, or Phase 5 without explicit authorization.

## Core invariants

- Markdown/Vault is the persistent Memory SOT.
- SQLite is rebuildable index/cache; canonical embedding BLOBs remain derived canonical cache.
- Vector/ANN sidecars remain disposable and rebuildable from canonical BLOBs.
- Normal `reindex` remains provider/network-free.
- Raw Log original text is preserved.
- Tests/evaluation fixtures never touch a real user Vault.
- Production code must not depend on `brain_twin_eval`.
- Keep responsibilities separated and handoffs recorded in repository documentation.
