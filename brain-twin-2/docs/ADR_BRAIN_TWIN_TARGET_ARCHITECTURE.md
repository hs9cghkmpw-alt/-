# ADR — Brain Twin Target Architecture

- Status: **Target architecture authorized; component acceptance remains gated**
- Date: 2026-08-29
- Decision owner: User
- Implementation status: **Not authorized by this ADR**

## Context

Brain Twin is intended to behave as a second brain rather than a manually maintained note database.
The user should be able to capture thoughts with minimal structure, while the system automatically
organizes them and later retrieves the right memories even when the user does not remember the
original words, labels, or folder.

The architecture therefore must optimize the whole memory lifecycle rather than selecting one
model to perform every task.

## Decision

Adopt the following as the target architecture.

```text
unstructured capture
        |
        v
schema-constrained organizer LLM
  - type / labels / topics
  - entities
  - importance / confidence
  - link suggestions
        |
        v
Markdown / Obsidian Memory SOT
        |
        +--------------------+
        |                    |
        v                    v
SQLite FTS / BM25       Qwen3-Embedding-0.6B
        |                    |
        +------ Hybrid ------+
                 |
                 v
        Qwen3-Reranker-0.6B
                 |
                 v
          primary Memories
                 |
                 v
       existing Entity / Link
         one-hop expansion
                 |
                 v
      answer / recall / insight
```

For larger Vaults, the dense-vector acceleration target remains a rebuildable FAISS HNSW sidecar,
subject to the existing PA3 gates. ExactScan remains the reference/fallback/small-Vault backend.

## Role separation

### 1. Organizer LLM

Use a separate, replaceable instruction-following local LLM for automatic organization.
Its job is structured interpretation, not vector similarity.

It may produce schema-constrained fields such as:

- memory type;
- labels/tags;
- topics;
- entities;
- importance/confidence;
- link suggestions;
- other explicitly versioned derived metadata.

The organizer model itself is **not selected by this ADR**. It must remain replaceable and must not
become the source of truth. The original captured text is preserved.

### 2. Lexical retrieval

Keep SQLite FTS/BM25 as an independent exact/lexical channel. It remains useful for names, product
codes, exact phrases, dates, and other cases where literal matching is stronger than semantic
similarity.

### 3. Dense semantic retrieval

Make pinned `Qwen/Qwen3-Embedding-0.6B` the **target dense embedding model**, subject to the existing
PA1 empirical acceptance gates. This changes its status from merely a provisional screening
favorite to the preferred target for the intended Brain Twin experience, but it does not waive
quality, latency, RAM, reproducibility, instruction, dimension, or Windows acceptance requirements.

PA1 must still compare the required challengers and Qwen instruction variants. If Qwen fails a
predeclared hard gate or is materially inferior on Brain Twin-shaped evidence, the decision must be
reopened rather than shipping a known-worse model.

### 4. Reranking

Add pinned `Qwen/Qwen3-Reranker-0.6B` as the **target post-retrieval reranker**.

The intended position is after lexical/vector candidate fusion and before the final primary result
set. Reranking must be optional and capability-gated so lexical/vector retrieval still works when
the reranker is unavailable.

Before production activation, an evaluation must compare reranker-off versus reranker-on using the
same candidate pool and report at least retrieval quality deltas plus Windows latency/RAM impact.
The reranker must not silently compensate for a broken embedding or ANN configuration.

### 5. Entity / Link graph

Preserve the existing deterministic Entity/Link one-hop associative expansion after primary
retrieval. The graph complements BM25/embeddings/reranking; it is not replaced by them.

Do not add an entity candidate channel to primary ranking without separate evidence and review,
because that would change the established retrieval semantics.

### 6. Vector backend

The production ANN target remains FAISS HNSW as a disposable sidecar, rebuilt only from canonical
SQLite embedding BLOBs and subject to the existing PA3 packaging, lifecycle, recall, Windows,
crash-recovery, and resource gates.

## Non-negotiable invariants

- Markdown / Obsidian Vault is the persistent Memory source of truth.
- Raw captured text is preserved; AI-derived organization cannot destructively replace it.
- SQLite metadata/FTS/embedding BLOBs are rebuildable derived state.
- ANN indexes are disposable acceleration, never the source of truth.
- Provider, organizer LLM, reranker, and vector backend remain independently replaceable.
- Normal reindex remains provider/network-free.
- No runtime component may require cloud access for normal offline operation.
- Tests/evaluation fixtures must never use the production Vault.
- Model failure must degrade explicitly; no silent substitution that changes retrieval semantics.

## Why this architecture

A second-brain workload contains several different problems:

- classification and labeling require structured reasoning;
- exact names/codes benefit from lexical search;
- vague recollection needs dense semantic retrieval;
- a broad candidate set benefits from a relevance reranker;
- forgotten relationships benefit from the explicit Entity/Link graph.

Using one model for all of these responsibilities would couple unrelated failure modes and make
future model replacement harder. The selected target keeps each responsibility independently
measurable and replaceable while preserving the user's original Memory as the durable asset.

## Acceptance and sequencing

This ADR records the desired end-state architecture; it does not authorize skipping the current
review gates.

Current sequence remains:

1. independent external review of PA1 hardening;
2. expand and freeze the Brain Twin-shaped gold/held-out evaluation;
3. run the embedding candidates, with Qwen3-Embedding-0.6B as the preferred target;
4. evaluate Qwen3-Reranker-0.6B off/on using an identical candidate pool and predeclared resource
   budgets;
5. only then authorize production provider/reranker/backend implementation stages as appropriate;
6. keep Production Vector Search activation **PENDING** until all required gates pass.

A future organizer-LLM selection is a separate decision and must be evaluated for schema accuracy,
consistency, Japanese handling, latency/RAM, offline packaging, and non-destructive behavior.
