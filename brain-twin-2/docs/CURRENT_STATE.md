# Brain Twin 2 — Current State

Last updated: 2026-08-29

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

Phase 4 completion is not production activation. A production embedding provider, ANN backend,
reranker acceptance, organizer-model selection, and Japanese semantic acceptance run remain open.

## Target second-brain architecture

The user explicitly selected the desired architecture on 2026-08-29. See
`docs/ADR_BRAIN_TWIN_TARGET_ARCHITECTURE.md`.

Target roles:

- automatic organization: separate replaceable local instruction-following LLM with schema output;
- exact/lexical recall: SQLite FTS / BM25;
- dense semantic recall: **Qwen3-Embedding-0.6B preferred target**, subject to evidence gates;
- post-retrieval relevance: **Qwen3-Reranker-0.6B preferred target**, measured OFF vs ON;
- associative recall: existing Entity / Link one-hop expansion;
- large-Vault ANN: FAISS HNSW preferred target, subject to PA3 Windows gates;
- persistent Memory SOT: Markdown / Obsidian Vault.

The architecture preference does not permit shipping a component that fails the predeclared gates.
The organizer LLM is still undecided.

## Production Vector Activation

Technical-selection design received review GO after
`c8012c6311bfac8f8f68fdc5a7790d0eeed0a6ac`.

Design documents:

- `docs/PRODUCTION_VECTOR_ACTIVATION_DESIGN.md`
- `docs/ADR_PRODUCTION_VECTOR_ACTIVATION.md`
- `docs/ADR_BRAIN_TWIN_TARGET_ARCHITECTURE.md`

## PA1 — Japanese Retrieval Evaluation

### Harness

Initial implementation:

- `0f93a92ef9186e6331cc5dce0de416914e488479`
- exact-SHA Actions `33173098200`: success
- 354 passed

Self-review hardening:

- `5a2851534f9385ff0e4cc90af89195de300f890f`
- exact-SHA Actions `33177339391`: success
- 370 passed

Hardening added warm-run latency statistics, RSS, open-vs-held-out judgement visibility,
blind-report redaction, dataset identity checks, deterministic confidence intervals, paired deltas,
stronger manifest secret rejection, and correct median/p95 behavior. Production `brain_twin/` was
not changed by that hardening.

### v1 seed

- 36 Memories
- 24 queries
- 15 dev / 9 blind-labelled
- committed/open judgements
- pipeline/regression seed only

### v2 open benchmark — GO for open development

Implementation:

- commit `c1a1d9a1b1879c4f8425739d891929159130e95c`
- exact-SHA Actions run `33219195386`: **success**
- result: **375 passed**

Shape:

- **360 synthetic Memories**
- **120 queries**
- **80 dev / 40 blind-labelled**
- 30 broad second-brain scenarios
- 300 same-domain/same-entity distractor Memories
- 10 explicit no-answer hard-negative queries
- 5 inactive distractors
- 5 long target Memories
- required spelling/transliteration, mixed-language, short-query, semantic, lexical and long-Memory slices

The v2 dataset is deterministic and fully synthetic. It is public/open by design. Its `blind` labels
exercise split handling only and are **not** formal held-out acceptance evidence.

### Local candidate runner — GO for evaluation scaffolding

Implementation:

- commit `36c364299b107f13125a02d5554d1920eb91c0ec`
- exact-SHA Actions run `33219538819`: **success**
- result: **383 passed**

The evaluation-only runtime loads embedding/reranker models only from existing local directories,
uses `local_files_only=True`, performs exact dense ranking so ANN approximation cannot confound model
quality, supports explicit dimension truncation, compares query-instruction variants, and can rerank
a frozen first-stage pool. It does not modify production `brain_twin/`, Vault, SQLite, or production
embedding config.

### Pinned Qwen acquisition — prepared, Windows execution pending

Acquisition helper:

- commit `49086fda15e938b8bf2808cbd355bf5ad8638d59`
- exact-SHA Actions run `33219863595`: **success**
- result: **387 passed**

Pinned PA1 starting revisions:

- Qwen3-Embedding-0.6B: `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`
- Qwen3-Reranker-0.6B: `e61197ed45024b0ed8a2d74b80b4d909f1255473`

The helper verifies the requested immutable revision before snapshot download and stores models outside
the repository. Normal Brain Twin runtime never invokes it. See `docs/PA1_QWEN_ACQUISITION.md`.

### One-command Qwen Windows matrix — GO for execution

Initial orchestration:

- commit `ae20f634f9a112817c3a835ed98665b1e5c0979c`
- exact-SHA Actions run `33223026401`: **success**
- result: **394 passed**

Evidence-isolation hardening:

- commit `af8f7186053f4e7df2d0219e880367cd9caf6e83`
- exact-SHA Actions run `33223233939`: **success**
- result: **396 passed**

`scripts/run_pa1_qwen_matrix.ps1` performs the open-development Windows sequence from one command:
environment setup, immutable model acquisition, English/Japanese/no-instruction comparison at 1024d,
winner-only 768/512/256 sweep, deterministic dense winner selection, and Qwen reranker OFF/ON
comparison on a frozen top-50 pool.

Evidence isolation is enforced:

- default output directory is unique by Git SHA prefix + UTC timestamp;
- non-empty custom output directories are rejected;
- matrix reports must have one dataset identity, split, judgement visibility, and Git commit;
- duplicate candidate IDs are rejected.

Review handoff: `docs/reviews/PA1_QWEN_MATRIX_RUNNER_REVIEW_2026-08-29.md`.
Runbook: `docs/PA1_QWEN_MATRIX_RUNBOOK.md`.

### Formal blind acceptance protocol — GO for tooling; no formal run yet

Latest sealing implementation:

- commit `6d08616d58d187d65df104bcb82a8705d2fe74aa`
- exact-SHA Actions run `33227872937`: **success**
- exact job `99034999663`
- result: **447 passed**

The formal-blind tooling now provides:

- a shared **Formal Config Builder** that freezes behavior-changing retrieval settings before a blind
  runner/query package is introduced;
- a **Launch Envelope** binding cycle ID, runner SHA, private source dataset identity, policy SHA,
  retrieval-config SHA, exact evaluator Git SHA, evaluation `k`, expected warm-repeat count, and an
  optional model-artifact manifest SHA;
- an actual Git check before model load: the formal runner resolves `git rev-parse HEAD` itself and
  requires the tracked worktree to be clean; a caller-supplied SHA is not trusted as evidence;
- private **Critical Slice Gates** for per-slice Recall@5/MRR@10/nDCG@10/must-hit@5/false-positive@5;
  the public formal report exposes only critical-rule spec SHA, rule count, and aggregate PASS/FAIL —
  not slice names, thresholds, or held-out per-slice scores;
- model-side ranking and private-side scoring remain separated; the model side receives no judgement
  labels and emits ranking/timing/RSS evidence only;
- formal acceptance requires the same launch envelope, policy, dataset identity, evaluator SHA,
  retrieval-config SHA, runtime protocol, and critical-slice attestation.

Important identity split:

- **retrieval behavior SHA** includes model/revision, instruction and its hash, dimension,
  normalization, document/query template commitments, reranker/base-model contract, and candidate-k;
- measurement/data-shape fields such as `evaluation_k`, `warm_repeats`, `corpus_memory_count`, and
  label-only candidate IDs are intentionally excluded from retrieval-behavior identity;
- those measurement protocol fields are frozen independently in the acceptance policy and launch
  envelope. This allows the retrieval configuration to be fixed **before** blind query text enters
  the evaluation cycle.

See `docs/PA1_FORMAL_BLIND_ACCEPTANCE.md`.

**No genuine formal held-out run has occurred.** The tooling being CI-green does not constitute
formal evidence, does not complete PA1, and does not activate production Vector Search.

## Still required before choosing a production embedding/reranker profile

- **physical Windows execution of the prepared open-development Qwen matrix**;
- actual Windows Python/runtime dependency freeze and machine evidence;
- actual Qwen English/Japanese/no-instruction quality and latency results;
- actual allowed-dimension comparison;
- actual Qwen3-Reranker-0.6B OFF/ON comparison;
- genuinely held-out private corpus creation outside the tuning workspace;
- actual two-judge calibration/adjudication and frozen private dataset SHA;
- tokenizer-aware near-512 / 2k / 8k cases;
- measured, predeclared Windows CPU/RAM/latency acceptance budgets and warm-repeat protocol;
- pinned BGE-M3/E5/Nomic/GTE/MiniLM challenger runs;
- independent evidence review;
- only after the profile/budgets/held-out corpus are frozen: one sealed formal blind cycle using the
  launch-envelope protocol.

No production embedding or reranker has been activated.

## Last known good PA1 tooling

- implementation: `6d08616d58d187d65df104bcb82a8705d2fe74aa`
- exact-SHA Actions: `33227872937`, success
- job: `99034999663`
- tests: `447 passed`
- production `brain_twin/`: unchanged by the formal-blind sealing commit

## Last known good production retrieval core

- implementation: `68ac6e420332bf87feecb47eb32b67cd84bd4016`
- Windows tests: `321 passed, 1 skipped`
- exact-SHA Actions: `33033340980`, success
- Sprint 4D / Phase 4 Vector Retrieval Core: **GO / COMPLETE**

## Next authorized action

On the Windows evaluation machine, sync `brain-twin-dev` and run the prepared **open-development**
Qwen matrix:

```powershell
git switch brain-twin-dev
git pull --ff-only origin brain-twin-dev
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_qwen_matrix.ps1
```

After the run, review `matrix_summary.md`, per-slice reports, environment evidence, and failure cases.
If Qwen remains strong, run BGE-M3 / multilingual-e5 / Nomic / GTE challengers under the same harness
before freezing the production embedding profile.

Do **not** run the formal blind cycle yet. First freeze the selected retrieval profile, measured
Windows runtime budgets, expected warm-repeat protocol, and a genuinely private/adjudicated held-out
corpus. Do **not** silently declare Production Vector Search active.

Production provider/backend/reranker integration, PA3 FAISS production lifecycle, organizer-LLM
integration, `ask`, Contradiction Detection, Memory Consolidation, smartphone integration, and
Phase 5 still require their own evidence/review boundary.

## Core invariants

- Markdown/Vault is persistent Memory SOT.
- Raw captured text is preserved; AI-derived organization cannot destructively replace it.
- SQLite is rebuildable index/cache; canonical embedding BLOBs remain derived canonical cache.
- Vector/ANN sidecars are disposable and rebuildable from canonical BLOBs.
- Organizer LLM, embedding provider, reranker, and ANN backend are independently replaceable.
- Normal `reindex` remains provider/network-free.
- Tests/evaluation fixtures never touch a real user Vault.
- Production code must not depend on `brain_twin_eval`.
- Keep responsibilities separated and handoffs recorded.
