# ADR Draft — Production Vector Search Provider and Backend

- Status: **Proposed / external review pending**
- Date: 2026-08-27
- Author: Codex
- Detail: `docs/PRODUCTION_VECTOR_ACTIVATION_DESIGN.md`

## Context

Phase 4 is complete, but Production Vector Search is pending. Windows measurement established
that ExactScan is a reference/fallback/small-Vault backend, not a 10k production primary.
Markdown remains persistent SOT, SQLite BLOBs the canonical derived embedding cache, and every
ANN index disposable. Provider and backend decisions stay independent; backend identity is not
part of the embedding fingerprint.

## Proposed decision

Subject to PA1/PA3 gates:

1. Use direct `sentence-transformers` with pinned `Qwen/Qwen3-Embedding-0.6B`.
2. PA1 compares a Brain Twin task-specific English instruction, equivalent Japanese instruction,
   and no instruction with other variables fixed; the shipped/default query prompt is optional as
   a separate baseline. Freeze the winning instruction only after gold evaluation, together with
   tokenizer/truncation, normalized output, and initially 1024 dimensions. A smaller dimension may
   win only through blind evaluation.
3. Use `faiss-cpu` HNSW as a disposable, generation-stamped sidecar rebuilt from valid BLOBs.
4. Keep ExactScan as reference/fallback/small-Vault and LanceDB as nominated backend fallback.

This is a provisional selection, not formal adoption or implementation authorization.

## Why

Qwen 0.6B combines current multilingual scope, 32k context, configurable IR instruction,
Apache-2.0 licensing, and a size plausibly usable on Windows CPU. It still must beat BGE-M3,
multilingual E5, Nomic v2, GTE multilingual, and a MiniLM control on Brain Twin Japanese data.

FAISS is the first ANN spike because a community-maintained `faiss-cpu` PyPI distribution currently
has a Windows x86-64 CPython 3.12 wheel, while upstream documents conda/Pixi as the supported binary
path for Windows x86-64. PA3 compares both installation paths. Mature HNSW/IVF and a thin sidecar
can preserve SQLite metadata authority and provider-free rebuild. This better matches 100k ANN than
treating stable sqlite-vec 0.1.9 exact `vec0` search as ANN.

## Why not the alternatives

- **BGE-M3:** strong long/multilingual challenger, but 1024-d/CPU cost and unused sparse/ColBERT.
- **E5:** stable baseline, but 512-token context and large-model CPU cost.
- **Nomic/GTE:** valuable efficiency/context challengers; `trust_remote_code` needs pin/audit.
- **Ollama:** good optional transport, but adds daemon/store and tag/quantization identity risk.
- **sqlite-vec:** stable 0.1.9 remains a useful pre-v1 SQLite/Windows exact backend. Experimental
  DiskANN/rescore/IVF work exists in 0.1.10-alpha pre-releases, but its maturity/stability is
  insufficient for the current production default.
- **hnswlib:** good algorithm, but stale source-only official PyPI release burdens Windows users.
- **LanceDB:** credible fallback with native lifecycle/filtering, but large Alpha dependency and a
  second storage lifecycle.
- **Qdrant:** excellent service/WAL/filtering; excessive server/container complexity for current
  desktop design and official Windows mount cautions.
- **USearch:** compact and packaged, but Python filtering/lifecycle requires more adapter work.

## Consequences and acceptance

Benefits are Japanese evidence before adoption, independent model/backend replacement, credible
100k ANN, and offline sidecar recovery. Costs are a heavy ML runtime, 1024-d footprint, and a
custom FAISS physical-ID/tombstone-or-rebuild/atomic-rebuild lifecycle.

FAISS HNSW cannot remove vectors. PA3 must either prove generation/content-specific physical
`ann_entry_id` values mapped to logical Memory/profile/content generation and rejected through
canonical SQLite validation when stale, or forbid incremental replacement and use a bounded
rebuild-on-update strategy. Reusing one physical HNSW ID for multiple embedding generations is
forbidden. Acceptance proves no old/inactive leakage, no duplicate logical Memories from old/new
entries, and fewer-than-K output when bounded overfetch cannot find enough valid unique results.

Accept this ADR only after PA1 selects the exact revision/instruction/dimension within Japanese
quality/determinism/CPU/RAM gates; PA2 proves clean Windows offline provider operation; PA3 compares
community PyPI and upstream conda/Pixi installation for clean Windows/Python 3.12, compiler-free
operation, reproducible pins/hashes, cadence, supply-chain/maintenance risk, and application
distribution complexity, and proves the physical-ID/update lifecycle, 1k/10k/100k performance,
zero invalid leakage, crash-safe recovery, and sampled ANN-vs-Exact `Recall@10 >= 0.98`; and
external review gives GO. Until then activation remains **PENDING**.
