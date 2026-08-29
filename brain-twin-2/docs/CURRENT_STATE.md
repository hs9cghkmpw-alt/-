# Brain Twin 2 — Current State

Last updated: 2026-08-29

## Active development context

- Repository: `hs9cghkmpw-alt/-`
- Project: `brain-twin-2/`
- Branch: `brain-twin-dev`
- Legacy `brain-twin/`: out of scope unless explicitly requested
- Markdown / Obsidian Vault: persistent Memory Source of Truth
- SQLite / embedding cache / ANN sidecars: rebuildable derived state

## Phase status

- Phase 1 — Memory Foundation: **COMPLETE**
- Phase 2 — Automatic Memory Worker / Entity / Link generation: **COMPLETE**
- Phase 3 — Retrieval: **COMPLETE**
- Phase 4 — Vector Retrieval Core (4A–4D): **GO / COMPLETE**
- PA1 — Japanese retrieval/model acceptance: **TOOLING GO; REAL WINDOWS EVIDENCE PENDING**
- Production Vector Search activation: **PENDING**

Phase 4 completion is not production activation. No production embedding provider, reranker, or ANN backend has been activated.

## Target second-brain architecture

See `docs/ADR_BRAIN_TWIN_TARGET_ARCHITECTURE.md`.

- automatic organization: replaceable local instruction-following LLM with schema-constrained output;
- lexical recall: SQLite FTS / BM25;
- semantic recall: **Qwen3-Embedding-0.6B preferred target**, subject to evidence gates;
- post-retrieval relevance: **Qwen3-Reranker-0.6B preferred target**, measured OFF vs ON;
- associative recall: existing Entity / Link one-hop expansion;
- large-Vault ANN: FAISS HNSW preferred target, subject to PA3 Windows/recovery gates;
- persistent Memory SOT: Markdown / Obsidian Vault.

The organizer LLM remains undecided. Architecture preference never overrides a failed quality/resource gate.

## PA1 evaluation foundation

### Open benchmark

`brain_twin_eval/open_gold_v2.py` generates a deterministic, privacy-safe open-development benchmark:

- 360 synthetic Memories;
- 120 queries;
- 80 dev / 40 blind-labelled pipeline-test queries;
- semantic, paraphrase, spelling/transliteration, proper-noun, mixed JP/EN, hard-negative, short-query and long-Memory slices.

The committed `blind` label is **not** formal held-out evidence. Formal held-out data must stay outside the repository/tuning workspace.

### Formal blind tooling

The formal-blind protocol is implemented and CI-green. It separates model execution from private scoring and provides:

- held-out/public package separation;
- two-judge comparison/adjudication support;
- frozen retrieval-config SHA;
- Launch Envelope binding dataset/policy/config/evaluator/runtime identities;
- clean exact Git HEAD verification before model load;
- critical-slice aggregate gates without leaking held-out slice scores;
- private scoring and redacted final acceptance evidence.

No genuine formal blind run has occurred yet.

## PA1 candidate matrix — current state

Catalog: `evaluation_profiles/challenger_catalog_v1.json` (schema 2)

All listed model revisions are immutable full commit SHAs.

### Ready for normal open-development execution

- Qwen3-Embedding-0.6B — `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3`
- Qwen3-Reranker-0.6B — `e61197ed45024b0ed8a2d74b80b4d909f1255473`
- BGE-M3 — `9a0624b896d81da7492a910ffa53731274b6cf3d`
- multilingual-e5-base — `d128750597153bb5987e10b1c3493a34e5a4502a`
- multilingual-e5-large-instruct — `274baa43b0e13e37fafa6428dbc7938e62e5c439`
- paraphrase-multilingual-MiniLM-L12-v2 control — `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`

Candidate-specific query/document formatting and allowed dimensions are committed in the catalog/profile files and become part of evaluation evidence.

### Pinned but fail-closed pending Windows custom-code smoke

- Nomic Embed v2 MoE — model `e89d1c9283c98dbd18f5003dc625394293978922`; custom-code dependency `nomic-ai/nomic-bert-2048@7710840340a098cfb869c4f65e87cf2b1b70caca`
- GTE multilingual base — model `9bbca17d9273fd0d03d5725c7a4b0f6b45142062`; custom-code dependency `Alibaba-NLP/new-impl@40ced75c3017eb27626c9d4ea981bde21a2662f4`

For these two candidates, acquisition is allowed but normal evaluation/formal use stays blocked until the exact pinned `code_revision` path passes the isolated offline Windows smoke. A successful smoke does **not** auto-promote catalog status.

## Latest PA1 challenger-preparation evidence

Challenger orchestration implementation:

- commit `a5f1448490586cff7579b11c69aa5f0d3b0f0960`
- exact-SHA Actions run `33229610378`: **success**
- result: **466 passed**

Remote-code isolation implementation:

- commit `52a11a882a381952234582f5ead97aa823ed0755`
- exact-SHA run `33229774485`: **failed during collection** because the new smoke helper called the existing RSS API by the wrong name
- failure was limited to evaluation tooling; no production runtime change

Corrective commit:

- commit `731fab69d24086330b5c9514a0ddd1e8da44b59f`
- exact-SHA Actions run `33229832697`: **success**
- job `99040554640`
- result: **473 passed in 42.39s**

The correction uses the existing `peak_rss_reading().bytes` API. Production `brain_twin/`, the real Vault, and production embedding configuration were not changed by the challenger-preparation series.

Review: `docs/reviews/PA1_CHALLENGER_PREP_REVIEW_2026-08-29.md`
Worklog: `docs/worklogs/2026-08-29-pa1-challenger-prep.md`
Matrix contract: `docs/PA1_CHALLENGER_MATRIX.md`

## Next authorized action

When a Windows evaluation PC is available, use one clean checkout and run the full open-development matrix:

```powershell
git switch brain-twin-dev
git pull --ff-only origin brain-twin-dev
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\brain-twin-2\scripts\run_pa1_full_open_matrix.ps1
```

That orchestrates the prepared Qwen matrix and the reviewed standard challengers under one Git/dataset identity and produces a combined open-development summary.

Separately, Nomic/GTE must first use `scripts/smoke_pa1_remote_code_candidate.py` against their pinned local artifacts. Do not add them to normal comparison merely because acquisition succeeded.

## Gates after Windows open-development execution

1. Review Qwen English/Japanese/no-instruction results.
2. Review Qwen allowed-dimension sweep.
3. Review Qwen reranker OFF/ON on the same first-stage pool.
4. Compare BGE-M3, E5-base, E5-large-instruct and MiniLM control on the same dataset/evaluator Git SHA.
5. Run/inspect isolated Nomic/GTE custom-code smoke; explicitly review before any promotion.
6. Select provisional winner using Japanese retrieval quality plus Windows latency/RSS/disk, not leaderboard rank alone.
7. Create genuinely private held-out corpus outside the repo, perform independent judging/adjudication, and freeze its SHA.
8. Predeclare Windows CPU/RAM/latency budgets and warm-repeat protocol.
9. Freeze selected retrieval configuration and model/custom-code revisions.
10. Run one sealed formal blind cycle.
11. Require independent evidence review before PA1 COMPLETE / production profile selection.

## After PA1

- PA2: production embedding provider and accepted reranker integration.
- PA3: production ANN lifecycle (FAISS HNSW preferred target), stale/update/delete safety, rebuild/recovery, ANN-vs-Exact recall and Windows scale benchmarks.
- Only after those evidence gates: Production Vector Search activation.
- Organizer LLM selection/integration remains a separate benchmark problem.
- `ask`, contradiction detection, memory consolidation, smartphone capture/sync, and later Phase 5 remain future work.

## Core invariants

- Raw captured input is preserved; AI organization cannot destructively replace it.
- Markdown/Vault is persistent Memory SOT.
- SQLite/vector/ANN state is derived and rebuildable.
- Organizer LLM, embedding provider, reranker and ANN backend remain independently replaceable.
- Normal `reindex` stays provider/network-free.
- Tests/evaluation fixtures never touch a real user Vault.
- Production code must not depend on `brain_twin_eval`.
- Do not silently declare Production Vector Search active.
