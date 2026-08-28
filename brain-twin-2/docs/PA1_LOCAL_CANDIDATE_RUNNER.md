# PA1 — Local Candidate Runner

Status: evaluation-only scaffolding; no production integration.

## Purpose

Run embedding candidates and an optional reranker on the deterministic PA1 open benchmark without
allowing an implicit network/model download.

The runner is deliberately outside production `brain_twin/`. It reuses the production canonical
Memory embedding document (`title: ...\ncontent: ...`) but does not change SQLite, the Vault,
embedding configuration, or the production provider/backend.

## Offline boundary

`--model-path` and `--reranker-model-path` must point to existing local directories. The loader:

- rejects a missing directory before importing the ML runtime;
- uses Sentence Transformers with `local_files_only=True`;
- never stores the local path in result metadata;
- records model name + immutable revision supplied by the operator;
- records instruction/template hashes rather than raw instruction text.

Model acquisition is a separate explicit step and is not implemented by this runner.

## Dense candidate

`brain_twin_eval.candidate_runtime.DenseCandidateRetriever`:

1. embeds every active v2 Memory once using the production canonical document template;
2. embeds the query at search time;
3. performs exact cosine ranking over the 360-Memory development corpus;
4. feeds logical Memory IDs into the existing PA1 evaluator.

This exact in-memory ranking intentionally measures embedding quality without confounding the result
with FAISS ANN approximation. ANN evaluation remains PA3.

Dimension truncation, when requested, occurs before normalization and becomes an explicit candidate
setting. A requested dimension larger than native output is rejected.

## Qwen3 Embedding instruction profiles

Committed open-development templates:

- `evaluation_profiles/qwen3_embedding_en.txt`
- `evaluation_profiles/qwen3_embedding_ja.txt`
- `evaluation_profiles/qwen3_embedding_none.txt`

The English/Japanese variants preserve Qwen's documented `Instruct: ...\nQuery:` wrapper while
changing the task-description language. The no-instruction variant is the raw query. Documents are
not given a query instruction.

These files are experiment inputs, not production defaults. PA1 evidence decides the winner.

## Reranker OFF / ON

`RerankingRetriever` takes a frozen first-stage retriever, requests `candidate_k` results (default
50), scores only those documents, and reorders that same pool. It cannot manufacture recall for a
relevant Memory that the first stage failed to retrieve.

The optional local CrossEncoder path uses Sentence Transformers' `CrossEncoder` with
`local_files_only=True`. Qwen3-Reranker-0.6B is the preferred target and supports the CrossEncoder
path; the committed task instruction is:

- `evaluation_profiles/qwen3_reranker_brain_twin.txt`

Reranker ties preserve base rank and then Memory ID for deterministic output.

## Windows run shape

After an embedding model has been explicitly acquired into a local directory and its immutable
revision recorded:

```powershell
cd "$HOME\Documents\brain-twin-dev\brain-twin-2"

python scripts/run_local_candidate_pipeline.py `
  --candidate-id qwen3-06b-en-1024 `
  --model-path "D:\Models\Qwen3-Embedding-0.6B" `
  --model-name "Qwen/Qwen3-Embedding-0.6B" `
  --model-revision "<FULL_PINNED_REVISION>" `
  --instruction-id brain-twin-en-v1 `
  --query-template-file evaluation_profiles/qwen3_embedding_en.txt `
  --dimension 1024 `
  --git-commit "$(git rev-parse HEAD)" `
  --out-dir .evaluation-results/qwen3-06b-en-1024
```

For open screening, the script defaults to 3 warm repeats/query to keep expensive CPU model runs
bounded. Finalists should use a separately predeclared higher repeat count on the Windows acceptance
machine.

Add reranking to the same frozen dense candidate:

```powershell
  --reranker-candidate-id qwen3-reranker-06b `
  --reranker-model-path "D:\Models\Qwen3-Reranker-0.6B" `
  --reranker-model-name "Qwen/Qwen3-Reranker-0.6B" `
  --reranker-model-revision "<FULL_PINNED_REVISION>" `
  --reranker-instruction-file evaluation_profiles/qwen3_reranker_brain_twin.txt
```

The reranker output includes paired candidate-minus-baseline deltas for Recall@5, MRR@10,
nDCG@10, must-hit@5 and false-positive@5 when available.

## Outputs

All files stay under the operator-selected result directory (normally `.evaluation-results/`):

- dense preparation timing/identity;
- dense manifest;
- dense JSON/Markdown evaluation;
- optional reranker load timing/identity;
- reranker manifest;
- reranked JSON/Markdown evaluation;
- paired reranker delta JSON.

No local model path, credential, raw Vault text, or production DB is written to the manifest.

## Remaining evidence boundary

The runner makes real local experiments possible, but does not itself prove production readiness.
Still required:

- pinned local model acquisition/runtime validation on Windows;
- the Qwen English/Japanese/no-instruction sweep;
- dimension sweep where supported;
- BGE-M3/E5/Nomic/GTE/MiniLM challenger runs;
- Qwen reranker OFF/ON measurement;
- genuinely held-out blind acceptance;
- predeclared CPU/RAM/latency gates;
- independent evidence review before PA2/production activation.
