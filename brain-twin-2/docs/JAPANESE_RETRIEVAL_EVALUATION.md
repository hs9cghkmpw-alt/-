# PA1 — Japanese Retrieval Evaluation Harness

Status: **implemented + self-review hardening; external independent review pending**

Date: 2026-08-28

Scope: model/backend-independent evaluation infrastructure only. No production model/backend is installed or selected here, and Production Vector Search remains PENDING.

## Purpose

Brain Twin must choose an embedding profile from Brain-Twin-shaped Japanese retrieval evidence rather than published benchmark scores alone. PA1 provides a deterministic, privacy-safe harness for lexical, vector, and Hybrid rankings, plus an ExactScan-vs-ANN oracle contract for PA3.

Evaluation code lives under `brain_twin_eval/`. Production `brain_twin/` never imports the evaluation package. Evaluation-side adapters may import existing production search APIs, preserving one-way dependency.

## Preserved invariants

- Markdown / Obsidian Vault remains the persistent Memory SOT.
- SQLite embedding BLOB remains the canonical derived embedding cache.
- No production provider/backend or model download is introduced.
- Tests do not open a real user Vault/DB.
- Generated reports remain under `.evaluation-results/` and are Git-ignored.

## Dataset contract

The seed fixture is `fixtures/japanese_retrieval_v1.json` with 36 synthetic Memories and 24 queries (15 dev / 9 blind-labelled). It covers all required Japanese/mixed-language, paraphrase, synonym, omission, proper-noun, spelling-variation, semantic-only, lexical-sufficient, hard-negative, short-query, and long-Memory slices.

Each query carries graded relevance `{0,1,2,3}`, optional must-hit IDs, slice tags, lexical-sufficient flag, adjudication note, and split. Each Memory carries a stable ID, title/content, language tags, length bucket, and active state. Validation rejects malformed IDs/references/grades/splits, duplicate IDs, invalid must-hit references, positive relevance to inactive Memories, and missing required slices.

The canonical dataset SHA-256 includes both judgements and `judgement_visibility`, preventing an open tuning set and a held-out acceptance set from accidentally sharing the same experiment identity.

### Blind-judgement visibility

`judgement_visibility` is either:

- `open`: judgements are visible in the tuning workspace/repository. This is the default for the committed seed fixture. Its `blind` labels are useful only for exercising the split pipeline; they are **not** valid formal acceptance-blind evidence.
- `held_out`: declares that blind judgements are stored outside the tuning workspace and supplied only to the acceptance evaluator. A metadata flag is not access control: the actual held-out file must remain outside the shared repo/tuning context.

For a `held_out` + `blind` report, per-query rankings, failure cases, and per-slice diagnostics are redacted automatically; only aggregate quality plus timing/resource evidence is emitted. This reduces accidental repeated tuning against blind outcomes.

The final quality corpus remains a separate PA1 data round: approximately 300–500 Memories / 120 queries, roughly 80 dev / 40 genuinely held-out blind, with two-judge calibration/adjudication.

## Metrics and statistical comparison

The harness implements Recall@1/3/5/10, MRR@10, graded nDCG@10 (`2^grade - 1`), must-hit@5, explicit-hard-negative false-positive@5, macro/per-slice aggregation, and ANN-vs-Exact Recall@K.

Unannotated Memories are not silently treated as negatives. `false-positive@5` counts only explicitly adjudicated grade-0 hard negatives in returned top-5 results.

Overall reports include deterministic 95% non-parametric bootstrap confidence intervals. `paired_metric_delta()` computes candidate-minus-baseline paired query deltas with a deterministic bootstrap CI, while requiring the same canonical dataset hash, split, and query IDs. This is the comparison primitive for lexical/E5-base baselines and candidate profiles.

`evaluate_ann_recall()` likewise compares two runs only when their canonical dataset hashes, splits, and query IDs match. This prevents ANN results from being compared with an ExactScan run built from a merely same-named but different gold set.

## Live-run timing and RSS

`evaluate_retriever()` records:

- first call for each query;
- **30 warm repeats per query by default** (configurable for tests/spikes);
- true median, nearest-rank p95, and max warm latency;
- first selected query timing separately;
- warm ranking-order drift count;
- process peak RSS before/after the run and peak growth.

Windows peak RSS uses `GetProcessMemoryInfo(...).PeakWorkingSetSize` through `ctypes`; POSIX uses `getrusage`. RSS telemetry is best-effort and never makes a quality run fail if the platform cannot expose it. The report intentionally says “first call” rather than pretending every query is globally cold; model-load/acquisition time remains a separate candidate-runtime measurement.

Precomputed-ranking runs keep timing/RSS unavailable rather than inventing values.

## Runner and adapters

`EvaluationRetriever` remains:

```text
search(query, k) -> ranked logical Memory IDs (+ optional score)
```

Supported paths:

- precomputed rankings via `evaluate_rankings()`;
- live retrievers via `evaluate_retriever()`;
- existing lexical search via `LexicalRetriever`;
- existing Vector Primary / ExactScan when supplied via `VectorRetriever`;
- existing Weighted-RRF Hybrid via `HybridRetriever`.

Duplicate, unknown, or inactive returned logical IDs are hard evaluation failures. Production search code remains unchanged.

## Experiment manifest

Each run records experiment ID, UTC timestamp, dataset version/hash/judgement visibility, exact Git commit, provider/model/revision, instruction ID plus SHA-256 of instruction text (never raw text), dimension, normalization, document-template version, backend label/parameters, Python/platform, and seed.

Secret-like keys are rejected recursively. Common credential value shapes are rejected before serialization. Report generation also verifies that the manifest dataset version/hash/visibility exactly matches the evaluated run.

## Reports

JSON and Markdown reports contain overall metrics with 95% bootstrap CIs, timing/resource telemetry, and—when not held-out blind—per-slice metrics, failed must-hit cases, explicit false-positive cases, and per-query rankings.

The original implementation selected the upper middle latency value for even sample counts and exposed an open committed `blind` split as if it could serve formal blind acceptance. Self-review hardening corrected both: mathematical median + p95 are now explicit, and formal blind evidence requires held-out judgements outside the tuning workspace with diagnostic redaction.

## Qwen comparison requirement

When candidate-model evaluation is explicitly authorized, Qwen3-Embedding-0.6B must compare otherwise-identical profiles for task-specific English instruction, equivalent Japanese instruction, and no instruction. A shipped/default query prompt may be a fourth baseline. Model revision, document template, normalization, dimension, dataset, and unrelated variables must remain fixed.

## Remaining PA1 work before model selection

The harness code is ready for independent review, but Japanese semantic quality evaluation has not yet been performed. The remaining data/evaluation round must expand/adjudicate the corpus, add tokenizer-aware near-512/2k/8k cases, predeclare Windows CPU/RAM/latency gates before opening held-out blind results, and run pinned Qwen/BGE-M3/E5/Nomic/GTE/MiniLM candidates plus required instruction/dimension variants.

No PA2 provider implementation, PA3 ANN implementation, or Phase 5 work is authorized by this harness change.
