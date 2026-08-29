# PA1 Challenger Matrix

Status: **PC-free preparation GO; Windows model execution pending.**

## Goal

Compare Brain Twin retrieval candidates under one reproducible evaluation contract rather than choosing from vendor benchmark rank alone.

Catalog: `evaluation_profiles/challenger_catalog_v1.json`

Validation: `brain_twin_eval.candidate_catalog`

Primary Windows orchestrators:

- Qwen-only matrix: `scripts/run_pa1_qwen_matrix.ps1`
- standard challenger matrix: `scripts/run_pa1_challenger_matrix.ps1`
- combined open-development run: `scripts/run_pa1_full_open_matrix.ps1`

## Runnable-candidate contract

A normal open-development candidate is runnable only when:

- it is enabled;
- model name is explicit;
- model revision is a full immutable 40-character commit SHA;
- mutable aliases such as `main`, `master`, `latest`, or `head` are rejected;
- its catalog `runtime_status` permits execution;
- required query/document formatting is committed;
- requested dimension is one of the reviewed allowed dimensions;
- any required custom-code dependency has its own immutable repository/revision commitment.

No evaluation runner may silently download a model. Acquisition is an explicit step; evaluation is local-files-only.

## Current catalog

| Candidate | Role | Revision | Context | Dimensions | Runtime |
|---|---|---|---:|---|---|
| Qwen3-Embedding-0.6B | embedding | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | 32768 | 1024/768/512/256 | ready |
| Qwen3-Reranker-0.6B | reranker | `e61197ed45024b0ed8a2d74b80b4d909f1255473` | 32768 | n/a | ready |
| BGE-M3 | embedding | `9a0624b896d81da7492a910ffa53731274b6cf3d` | 8192 | 1024 | ready |
| multilingual-e5-base | embedding | `d128750597153bb5987e10b1c3493a34e5a4502a` | 512 | 768 | ready |
| multilingual-e5-large-instruct | embedding | `274baa43b0e13e37fafa6428dbc7938e62e5c439` | 512 | 1024 | ready |
| Nomic Embed v2 MoE | embedding | `e89d1c9283c98dbd18f5003dc625394293978922` | 512 | 768/256 | **requires remote-code smoke** |
| GTE multilingual base | embedding | `9bbca17d9273fd0d03d5725c7a4b0f6b45142062` | 8192 | 768 | **requires remote-code smoke** |
| multilingual MiniLM control | embedding | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` | 128 | 384 | ready |

### Custom-code commitments

Nomic:

- model: `nomic-ai/nomic-embed-text-v2-moe@e89d1c9283c98dbd18f5003dc625394293978922`
- code dependency: `nomic-ai/nomic-bert-2048@7710840340a098cfb869c4f65e87cf2b1b70caca`

GTE:

- model: `Alibaba-NLP/gte-multilingual-base@9bbca17d9273fd0d03d5725c7a4b0f6b45142062`
- code dependency: `Alibaba-NLP/new-impl@40ced75c3017eb27626c9d4ea981bde21a2662f4`

These two remain fail-closed. Acquisition may populate pinned local artifacts/code cache, but they do not enter normal comparison until an isolated offline Windows smoke succeeds and the result is explicitly reviewed. Smoke success does not mutate/promote the catalog automatically.

## Candidate-specific retrieval contracts

- Qwen: dedicated English task instruction vs equivalent Japanese instruction vs no instruction at 1024d, then allowed-dimension sweep for the open-development winner.
- Qwen reranker: OFF/ON comparison on the same frozen first-stage candidate pool.
- BGE-M3: dense-only raw-query/raw-document baseline.
- E5 base: committed `query:` / `passage:` prefixes.
- E5 large instruct: committed `Instruct:` / `Query:` query format; documents remain unprefixed.
- Nomic: committed search-query/search-document formatting plus pinned custom code; smoke required first.
- GTE: raw-query/raw-document baseline plus pinned custom code; smoke required first.
- MiniLM: lightweight short-context control, not a presumed production target.

The query/document formatting files are part of evaluation evidence. A candidate is not allowed to receive an ad-hoc prompt during the run.

## Comparison order

1. Run Qwen 1024d instruction matrix.
2. Sweep Qwen 768/512/256 only from the open-development winning instruction.
3. Compare Qwen reranker OFF/ON on the same top-50 first-stage pool.
4. Run BGE-M3, E5 base, E5 large instruct and MiniLM control under the same Git/dataset identity.
5. Produce one combined open-development summary.
6. Run Nomic/GTE isolated offline custom-code smoke separately.
7. Only after explicit review may a remote-code candidate join the normal matrix.
8. Surviving candidates are judged by Japanese retrieval quality **and** Windows latency/RSS/disk.
9. Only the provisional winner proceeds to a genuine private held-out acceptance cycle.

## Fairness and anti-tuning constraints

- Exact dense ranking is used for embedding-quality comparison so ANN approximation cannot confound model quality.
- Do not tune on formal held-out data.
- Do not combine reports from different dataset hashes, split/judgement visibility, or evaluator Git commits.
- Duplicate candidate IDs are rejected.
- Reused/non-empty evidence directories are rejected by the orchestration layer.
- Reranker comparison preserves the first-stage pool.
- Production ANN choice is PA3 and is evaluated separately against the winning canonical vectors.
- Formal Blind freezes behavior-changing retrieval configuration before blind query text enters the cycle.
- For custom-code models, code dependency repository/revision is also part of frozen retrieval identity.

## Current evidence

Challenger orchestration:

- implementation `a5f1448490586cff7579b11c69aa5f0d3b0f0960`
- exact-SHA Actions `33229610378`: success
- **466 passed**

Remote-code isolation initially exposed one evaluation-only RSS API naming error at `52a11a882a381952234582f5ead97aa823ed0755` / run `33229774485`.

Corrective implementation:

- `731fab69d24086330b5c9514a0ddd1e8da44b59f`
- exact-SHA Actions `33229832697`: success
- job `99040554640`
- **473 passed in 42.39s**

No real candidate model has been executed on Windows yet, and this document does not claim any model has won.
