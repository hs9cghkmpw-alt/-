# PA1 — Japanese Retrieval Evaluation Harness

Status: **focused evidence-integrity repair CI-green; independent re-review pending**

Date: 2026-08-29

Scope: Brain Twin-specific Japanese retrieval evaluation. Evaluation code remains isolated under
`brain_twin_eval/`; production `brain_twin/` must never depend on it.

## Purpose

Brain Twin must select retrieval components from evidence shaped like the actual product:

- vague Japanese recall ("あれ何だっけ");
- paraphrases and omitted context;
- proper nouns and project codes;
- katakana/Latin transliteration;
- kanji/hiragana spelling variation;
- Japanese/English mixed queries;
- exact lexical recall;
- long Memories;
- no-answer / hard-negative cases.

Published MTEB/MIRACL scores are screening evidence only. Production selection requires this harness,
Windows resource evidence, and a genuinely held-out acceptance set.

## Preserved invariants

- Markdown / Obsidian Vault is the persistent Memory SOT.
- SQLite embedding BLOBs remain the canonical derived embedding cache.
- ANN/reranker indexes are disposable accelerators, never SOT.
- Evaluation fixtures never touch a real user Vault/DB.
- Raw user text is never required in the committed benchmark.
- Reports live under `.evaluation-results/` and remain Git-ignored.
- Organizer LLM, embedder, reranker, and ANN backend remain independently replaceable.

## Dataset contract

Each Memory contains stable `memory_id`, `title`, `content`, `language_tags`, `length_bucket`, and
`active`. Each Query contains stable `query_id`, query `text`, `slice_tags`, graded relevance
`{0,1,2,3}`, optional `must_hit_ids`, `lexical_sufficient`, `adjudication_note`, and `split`.

Validation rejects duplicate IDs, broken references, invalid grades/splits, positive relevance to
inactive Memories, invalid must-hit references, and missing required slices. The canonical dataset
SHA-256 includes judgements and `judgement_visibility`.

One authoritative formal-blind predicate requires both `judgement_visibility = held_out` and the
evaluated `split = blind`. Held-out `dev` or all-split runs are not acceptance-blind-ready and must
not be routed as formal evidence.

## Dataset generations

### v1 seed

`fixtures/japanese_retrieval_v1.json`

- 36 synthetic Memories;
- 24 queries;
- 15 dev / 9 blind-labelled;
- committed/open judgements;
- contract and regression seed only.

### v2 open benchmark

`brain_twin_eval.open_gold_v2` generates the deterministic v2 development benchmark. Regenerate a
materialized JSON file when needed with:

```powershell
python scripts/generate_japanese_retrieval_v2.py
```

The default output is under `.evaluation-results/`, so generated experiment data is not committed.

Contract:

- **360 synthetic Memories**;
- **120 queries**;
- **80 dev / 40 blind-labelled**;
- `judgement_visibility = open`;
- 30 broad synthetic second-brain scenarios;
- 300 same-entity/domain distractor Memories;
- 10 explicit no-answer hard-negative queries;
- 5 inactive distractor Memories;
- 5 long target Memories;
- all required retrieval slices represented.

The v2 `blind` labels are generated from public code and therefore **must not** be called formal blind
acceptance. They exercise split handling and permit repeatable open model development only.

### Formal held-out acceptance

The final acceptance set must keep its blind judgements outside the tuning workspace/repository. A
metadata flag is not access control.

Target:

- roughly 300–500 Memories;
- roughly 120 queries;
- about 80 dev / 40 genuinely held-out blind;
- two-judge calibration/adjudication;
- tokenizer-aware near-512 / 2k / 8k cases;
- predeclared Windows CPU/RAM/latency budgets before blind outcomes are opened.

For `held_out` + `blind`, reports redact per-query rankings, failure details, and per-slice diagnostics.

## Required slices

The evaluator requires coverage for `japanese_to_japanese`, `paraphrase`, `synonym`,
`omission_context`, `proper_noun`, `katakana_transliteration`, `kanji_hiragana_variation`,
`japanese_english_mixed`, `semantic_only`, `lexical_sufficient`, `hard_negative`, `short_query`, and
`long_memory`. v2 also adds scenario/domain tags for analysis.

## Metrics

Quality:

- Recall@1/3/5/10
- MRR@10
- graded nDCG@10 (`2^grade - 1`)
- must-hit@5
- explicit-hard-negative false-positive@5
- macro and per-slice aggregation
- ANN-vs-Exact Recall@K

Statistics:

- deterministic non-parametric 95% bootstrap confidence intervals;
- paired candidate-minus-baseline query deltas;
- dataset/split/query-ID identity checks before paired comparison.

Unannotated Memories are not silently counted as negatives.

## Timing and resources

`evaluate_retriever()` records first call, 30 warm repeats/query by default, true median,
nearest-rank p95, max, warm ranking-order drift count, and best-effort process peak RSS/growth.
Windows peak RSS uses `GetProcessMemoryInfo`; POSIX uses `getrusage`. Missing RSS telemetry never
invalidates a quality run.

Any non-zero warm logical-ID ranking drift makes the run `reproducible = false` and
`selection_eligible = false`. The first-call quality metrics and exact drift count remain available
for diagnosis, but matrix winner selection, critical-slice acceptance, formal acceptance, and
paired candidate / ANN-vs-Exact selection comparisons reject the run. Formal policies cannot permit a non-zero drift
budget.

## Runner and adapters

`EvaluationRetriever` remains:

```text
search(query, k) -> ranked logical Memory IDs (+ optional score)
```

Supported paths are precomputed rankings, live retrievers, existing lexical search, existing
Vector/ExactScan, and existing Hybrid. Duplicate, unknown, or inactive returned IDs are hard failures.

## Experiment manifest

Every experiment records experiment ID/UTC timestamp, dataset version/hash/visibility, exact Git
commit, provider/model/revision, instruction ID and SHA-256 of instruction text (never raw
instruction text), dimension/normalization, document-template version, backend label/parameters,
Python/platform, and random seed. Secret-like keys/value shapes are rejected before serialization.

## Preferred target experiment

The user-selected target architecture is:

```text
SQLite FTS/BM25
       +
Qwen3-Embedding-0.6B
       ↓
Hybrid candidate pool
       ↓
Qwen3-Reranker-0.6B (OFF/ON comparison)
       ↓
existing Entity / Link one-hop expansion
```

Qwen remains the preferred target, not an evidence exemption.

### Embedding comparison

At minimum compare Qwen3-Embedding-0.6B, BGE-M3, multilingual-E5 baseline(s), Nomic Embed v2 MoE,
GTE multilingual, and a MiniLM control.

For Qwen, keep unrelated variables fixed and compare:

1. Brain Twin task-specific English instruction;
2. equivalent Japanese instruction;
3. no instruction;
4. shipped/default prompt only as an optional extra baseline.

Also compare dimensions where the model contract allows it.

### Reranker comparison

On a frozen candidate pool, compare Qwen3-Reranker-0.6B OFF vs ON. Measure quality deltas,
false-positive changes, per-slice wins/regressions, Windows latency/RAM, and failure behavior. The
reranker must not hide weak first-stage recall: if a relevant Memory never enters the candidate pool,
reranking cannot recover it.

## Remaining before production selection

- independent Critical/Major=0 review of focused-repair commit
  `f9cb9652afc3f4b1838074091fbad3e510821c76` (exact-SHA Actions run `33798627068`: success, 571 passed);
- genuinely held-out blind judgements;
- two-judge calibration/adjudication;
- tokenizer-aware boundary cases;
- predeclared Windows budgets;
- pinned local candidate model runs;
- Qwen instruction/dimension comparison;
- Qwen reranker OFF/ON comparison;
- independent review of the resulting evidence.

No production provider/backend/reranker integration is implied by the open benchmark itself.
