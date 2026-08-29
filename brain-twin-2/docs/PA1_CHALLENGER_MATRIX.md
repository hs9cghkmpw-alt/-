# PA1 Challenger Matrix

Status: catalog prepared; challenger revisions other than Qwen are intentionally unresolved until reviewed.

## Goal

Compare candidate embedding/reranking components under one reproducible Brain Twin evaluation contract rather than relying on vendor benchmark rank.

Catalog: `evaluation_profiles/challenger_catalog_v1.json`

Validation: `brain_twin_eval.candidate_catalog`

A candidate is runnable only when:

- it is enabled;
- its model name is explicit;
- its revision is a full immutable 40-character commit SHA;
- the revision is not a mutable alias such as `main`, `master`, `latest`, or `head`.

## Current catalog

Preferred targets already pinned:

- `Qwen/Qwen3-Embedding-0.6B`
- `Qwen/Qwen3-Reranker-0.6B`

Embedding challengers queued for immutable-revision review:

- `BAAI/bge-m3`
- `intfloat/multilingual-e5-base`
- `intfloat/multilingual-e5-large-instruct`
- `nomic-ai/nomic-embed-text-v2-moe`
- `Alibaba-NLP/gte-multilingual-base`
- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` as a lightweight control

`null` revision means **not runnable**, not "use latest". This prevents a future comparison from silently changing model weights between runs.

## Comparison order

1. Complete Qwen instruction comparison at fixed 1024d.
2. Sweep allowed Qwen dimensions using only the open-development winner.
3. Compare Qwen reranker OFF/ON on the same frozen first-stage candidate pool.
4. Review and pin challenger revisions.
5. Run challengers through the same open benchmark, keeping dataset/evaluator revision fixed.
6. Only candidates surviving open-development quality + Windows resource sanity proceed to the genuine held-out acceptance cycle.

## Fairness constraints

- Exact dense ranking is used for embedding-quality comparison so ANN approximation does not confound model quality.
- Candidate-specific required query/document formatting is part of the candidate profile and is hashed in evidence.
- Do not tune a challenger on the held-out set.
- Do not compare reports from different dataset hashes or evaluator Git commits in the same decision table.
- Reranker comparisons must preserve the same first-stage candidate pool.
- Production ANN choice is evaluated separately in PA3 against the winning canonical vectors.

## Why unresolved pins are useful now

The catalog makes the future work explicit without pretending that mutable upstream state has already been reviewed. The PC-free phase can therefore finish the comparison contract now, while exact challenger revisions and local artifacts are pinned immediately before acquisition.
