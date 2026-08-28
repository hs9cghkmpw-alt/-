# PA1 — Japanese Retrieval Evaluation Harness

Status: **implemented; external review pending**

Date: 2026-08-28

Scope: model/backend-independent evaluation infrastructure only. This PA1 work does **not** install or select a production model/backend and does not activate Production Vector Search.

## Purpose

Brain Twin must choose an embedding profile from evidence on Brain-Twin-shaped Japanese retrieval, not from published benchmark scores alone. PA1 provides a deterministic, privacy-safe harness that can compare lexical, vector, and Hybrid rankings with the same gold judgements and later measure ANN recall against ExactScan using the same canonical vectors.

The evaluation code lives in a separate `brain_twin_eval/` package. Production `brain_twin/` does not import it. Thin evaluation-side adapters may import existing production search APIs; the dependency never points in the opposite direction.

## Invariants preserved

- Markdown / Obsidian Vault remains the persistent Memory SOT.
- SQLite embedding BLOB remains the canonical derived embedding cache.
- No production provider/backend was added.
- No model is downloaded by the harness.
- The committed fixture is synthetic; no real Vault or personal Memory is used.
- Tests never open a production Vault/DB.
- Generated reports belong under `.evaluation-results/`, which is Git-ignored.

## Dataset format

The seed fixture is `fixtures/japanese_retrieval_v1.json`.

### Memory

Each Memory has:

- `memory_id`
- `title`
- `content`
- `language_tags`
- `length_bucket`
- `active`

### Query

Each query has:

- `query_id`
- `text`
- `slice_tags`
- `relevance`: mapping of Memory ID to graded relevance `{0,1,2,3}`
- `must_hit_ids`: optional critical relevant IDs
- `lexical_sufficient`
- `adjudication_note`
- `split`: `dev` or `blind`

Validation rejects duplicate Memory/query IDs, empty required fields, invalid grades/splits, relevance references to missing Memories, positive relevance to inactive Memories, invalid must-hit references, and missing required evaluation slices.

The dataset hash is SHA-256 over a canonical UTF-8 JSON representation so experiment reports can identify the exact gold set independently of file formatting.

## Required slices

The schema requires coverage for:

1. Japanese query → Japanese Memory
2. paraphrase
3. synonym
4. omission/context-dependent phrasing
5. proper noun / project code
6. katakana/transliteration variation
7. kanji/hiragana variation
8. Japanese + English mixed text
9. semantic-only match with little lexical overlap
10. lexical-sufficient exact names/IDs/terms
11. unrelated/hard-negative query
12. short query
13. long Memory

## Current seed fixture

The first implementation intentionally establishes the contract with a small, reviewable synthetic set rather than pretending the final gold dataset is already adjudicated:

- **36 synthetic Memories**
- **24 queries**
- **15 dev / 9 blind**
- all required slice tags represented
- one inactive Memory used to verify leakage rejection
- explicit grade-0 hard negatives for the hard-negative slice

This seed is **not** the final PA1 quality corpus. The design target remains approximately **300–500 Memories / 120 queries**, with the planned roughly **80 dev / 40 blind** split and independent judgement/adjudication before model acceptance.

## Metrics

Pure metric functions implement:

- Recall@1/3/5/10
- MRR@10
- nDCG@10 using graded relevance and gain `2^grade - 1`
- must-hit@5
- false-positive@5
- macro aggregation
- per-slice aggregation
- dev/blind separation
- ANN-vs-Exact Recall@K

### False-positive definition

The seed gold set is sparse, so an unannotated retrieved Memory is **not** silently treated as a judged negative. `false-positive@5` currently means the fraction of returned top-5 occupied by **explicitly adjudicated grade-0 hard negatives**. As gold coverage expands, the annotation policy must expand with it rather than changing the metric implicitly.

### ANN oracle metric

`ann_recall_at_k(exact_ranked_ids, ann_ranked_ids, k)` compares an ANN top-K to ExactScan top-K for the same canonical vectors. PA1 does not install FAISS or any other ANN backend; this is the metric contract PA3 can reuse.

## Runner and adapters

`EvaluationRetriever` is the evaluation-side protocol:

```text
search(query, k) -> ranked logical Memory IDs (+ optional score)
```

The harness supports:

- precomputed rankings via `evaluate_rankings()`
- live retrievers via `evaluate_retriever()`
- `LexicalRetriever` over existing `brain_twin.search.search`
- `VectorRetriever` over existing `brain_twin.vector_search.vector_search` (including ExactScan when supplied as the backend)
- `HybridRetriever` over existing `brain_twin.hybrid_search.hybrid_search`

Returned rankings are rejected if they contain duplicate logical IDs, unknown IDs, or inactive Memories. This makes stale/inactive leakage a hard evaluation failure rather than merely a poor score.

Production code does not import these adapters; they are evaluation-only glue.

## Experiment manifest

Every run can record:

- experiment ID
- UTC timestamp
- dataset version + SHA-256
- git commit
- provider label
- model name + revision
- instruction ID
- SHA-256 of instruction text (not the raw instruction)
- dimension
- normalization flag
- document-template version
- backend label + non-secret backend parameters
- Python/platform
- random seed

Secret-like keys/values are rejected recursively before serialization. Credentials, API keys, tokens, passwords, and raw secrets must never appear in evaluation reports.

## Reports

The harness emits:

- machine-readable JSON
- human-readable Markdown

Reports contain overall metrics, per-slice metrics, failed must-hit queries, explicit false-positive cases, query rankings, experiment metadata, and latency when a live adapter is used.

Precomputed-ranking reports intentionally show latency as unavailable rather than inventing timing data.

## Dev / blind policy

- `dev`: may be used while choosing prompts/instructions/dimensions and debugging the evaluation setup.
- `blind`: must not be inspected/tuned against repeatedly during candidate optimization.

The final 120-query dataset should keep the planned 80/40 split. Before a real acceptance run, two judges should calibrate a subset, resolve disagreements, and freeze the blind judgements.

## Qwen instruction comparison

When real-model evaluation is explicitly authorized, Qwen3-Embedding-0.6B must at minimum compare otherwise-identical profiles for:

1. Brain Twin task-specific English instruction
2. equivalent Japanese task-specific instruction
3. no instruction

The model's shipped/default query prompt may be an additional baseline. No instruction is preselected by this harness.

Model revision, document template, normalization, dimension, dataset version, and all unrelated variables must remain fixed when comparing instruction variants.

## How to run the model-independent evaluator

The CLI consumes a rankings JSON keyed by query ID plus a non-secret manifest-input JSON:

```powershell
python scripts/evaluate_retrieval.py `
  --dataset fixtures/japanese_retrieval_v1.json `
  --rankings path\to\rankings.json `
  --manifest path\to\manifest-input.json `
  --split dev `
  --out-json .evaluation-results\run.json `
  --out-md .evaluation-results\run.md
```

A future candidate runner may produce the same ranking contract through the live adapters without changing metric/report policy.

## Privacy

- The committed seed fixture is synthetic and intentionally contains no real user's Vault contents.
- Do not copy a real Vault into `fixtures/`.
- A future anonymized corpus must be explicitly reviewed before commit.
- Generated local result files are not committed by default.
- Experiment manifests store only an instruction hash, not instruction text, and reject secret-like backend parameters.

## Tests

Focused PA1 tests cover:

- valid dataset loading and required slices
- deterministic dataset hash
- malformed/duplicate IDs
- broken relevance references
- invalid grades / empty queries
- must-hit validity
- known-answer Recall/MRR/nDCG/must-hit/false-positive behavior
- ANN-vs-Exact Recall known answer
- macro/per-slice aggregation
- deterministic rankings/report structure
- dev/blind separation
- duplicate/unknown/inactive returned IDs
- live retriever protocol latency
- existing lexical/vector/hybrid adapter wiring
- required manifest fields
- instruction hashing without raw instruction persistence
- recursive secret-like manifest rejection
- synthetic/no-Vault fixture guard

## Deferred PA1 work

The harness implementation is ready for review, but **Japanese semantic quality evaluation itself has not been performed**. Before selecting a model, PA1 still needs an explicitly authorized data/evaluation round to:

1. expand the gold set toward 300–500 Memories / 120 queries;
2. perform two-judge calibration and adjudication;
3. add tokenizer-aware near-512 / 2k / 8k long-Memory cases;
4. predeclare Windows CPU/RAM/latency acceptance budgets before the blind run;
5. run pinned candidate models/instruction/dimension variants without tuning on blind results.

No Qwen/BGE/E5/Nomic/GTE model was downloaded or run in this implementation. PA2 (production provider) and PA3 (production ANN backend) remain separate and unauthorized by this PA1 implementation.
