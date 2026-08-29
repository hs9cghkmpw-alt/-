# PA2 / PA3 Pre-implementation Boundary

Status: design preparation only. No production provider or ANN backend is activated by this document.

## PA2 — production embedding provider

PA2 may start only after PA1 identifies an evidence-backed embedding profile.

Required implementation boundary:

- production package implements a provider conforming to the existing `EmbeddingProvider` contract;
- provider identity, model revision, instruction contract, dimension, normalization, and document-template version remain fingerprinted profile inputs;
- backend identity remains excluded from the embedding fingerprint;
- model acquisition/install is explicit and separate from normal Brain Twin execution;
- normal `reindex` remains provider/network-free;
- the provider may not make Markdown or ANN storage authoritative;
- staging profile activation remains atomic: failed embedding/build work must preserve the previous active profile;
- title/content races must continue to revalidate under the write transaction before marking vectors valid;
- secrets and local model paths must not leak into portable Memory or experiment metadata.

PA2 must prove at least:

- exact pinned model load on Windows;
- batch document/query embedding;
- deterministic profile identity;
- dimension/normalization validation;
- retry/error classification;
- profile switch and rollback behavior;
- full existing test suite;
- recovery without the provider for backend-only rebuild/reindex paths.

## PA3 — production ANN backend

Preferred spike target remains FAISS HNSW, subject to Windows distribution and lifecycle evidence.

The ANN remains a disposable acceleration sidecar. Canonical float32 embedding BLOBs in SQLite remain the rebuild source.

### Physical identity

Logical `memory_id` must not be reused as the only physical ANN entry identity when stale entries can coexist during update/rebuild.

Use a generation/content-specific physical identity such as:

`ann_entry_id = hash(profile_fingerprint, memory_id, content_hash, generation)`

or an equivalent design with the same safety property.

Every ANN hit must be canonically validated before it can become a search result:

- active Memory still exists;
- embedding row is valid;
- active profile fingerprint matches;
- content hash/generation matches the current canonical row;
- duplicate logical Memory IDs collapse deterministically;
- stale physical entries never leak into results.

### HNSW deletion/update constraint

Do not assume arbitrary in-place removal is available. PA3 must explicitly choose and test one of:

1. generation-specific physical IDs + overfetch + canonical validation + periodic rebuild; or
2. rebuild-on-update policy where stale entries cannot become visible.

Ambiguous physical-ID reuse is forbidden.

### Overfetch exhaustion

Canonical filtering may leave fewer than K valid logical results. That is acceptable and must be represented honestly. Do not fabricate/fallback silently merely to fill K.

Test cases must include:

- stale physical entries;
- inactive Memory entries;
- duplicate logical IDs across generations;
- profile switch remnants;
- overfetch exhaustion returning fewer than K;
- crash during build;
- missing/corrupt ANN sidecar;
- canonical cache rebuild followed by ANN rebuild;
- backend-only rebuild with provider unavailable.

## Existing deferred lifecycle watches

Two Phase-4 ExactScan-safe areas require explicit review when a mutable real backend is introduced:

- `delete_cached_embedding()` currently synchronizes backend deletion without an active/ready profile gate;
- `rebuild_backend()` builds the configured provider profile and updates backend state without switching the active pointer.

ExactScan masks these concerns because its mutation methods are effectively no-op over canonical storage. PA3 must not carry that assumption into a stateful ANN backend.

## Windows evidence

PA3 must compare the reviewed Windows installation/distribution paths and record:

- Python version;
- package provenance/version;
- CPU architecture;
- build/load time;
- query warm median/p95/max;
- peak RSS;
- index disk size;
- ANN-vs-Exact Recall@10.

The proposed ANN quality gate remains `Recall@10 >= 0.98` against ExactScan using the identical canonical vectors, but final production activation still requires the full frozen acceptance record and independent review.
