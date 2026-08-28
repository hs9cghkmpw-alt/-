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

### v2 open benchmark

The user explicitly authorized continued progress on 2026-08-29.

The next PA1 data round expands the open benchmark to:

- **360 synthetic Memories**
- **120 queries**
- **80 dev / 40 blind-labelled**
- 30 broad second-brain scenarios
- 300 same-domain/same-entity distractor Memories
- 10 explicit no-answer hard-negative queries
- long-Memory, spelling/transliteration, mixed-language, short-query, semantic and lexical slices

Files:

- `brain_twin_eval/open_gold_v2.py`
- `scripts/generate_japanese_retrieval_v2.py`
- `tests/test_japanese_retrieval_gold_v2.py`
- `docs/JAPANESE_RETRIEVAL_EVALUATION.md`
- `docs/PA1_OPEN_GOLD_V2.md`

The v2 dataset is generated deterministically from committed synthetic source and materialized under
`.evaluation-results/` when needed. It is public/open by design. Its `blind` labels are **not**
formal held-out evidence.

## Still required before choosing a production embedding/reranker profile

- genuinely held-out blind set outside the tuning workspace;
- two-judge calibration/adjudication;
- tokenizer-aware near-512 / 2k / 8k cases;
- predeclared Windows CPU/RAM/latency acceptance budgets;
- pinned Qwen/BGE-M3/E5/Nomic/GTE/MiniLM candidate runs;
- Qwen English/Japanese/no-instruction comparison;
- allowed-dimension comparison;
- Qwen3-Reranker-0.6B OFF/ON comparison on the same frozen candidate pool.

No production embedding or reranker model has yet been downloaded/evaluated by this repository work.

## Last known good production retrieval core

- implementation: `68ac6e420332bf87feecb47eb32b67cd84bd4016`
- Windows tests: `321 passed, 1 skipped`
- exact-SHA Actions: `33033340980`, success
- Sprint 4D / Phase 4 Vector Retrieval Core: **GO / COMPLETE**

## Next authorized action

Continue PA1 evidence preparation and candidate-evaluation scaffolding under the target architecture.
It is authorized to prepare/open-evaluate candidate embeddings and reranker experiments while
preserving local/offline and reproducibility requirements.

Do **not** silently declare Production Vector Search active. Production provider/backend/reranker
integration, PA3 FAISS production lifecycle, organizer-LLM integration, `ask`, Contradiction
Detection, Memory Consolidation, smartphone integration, and Phase 5 still require their own
evidence/review boundary.

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
