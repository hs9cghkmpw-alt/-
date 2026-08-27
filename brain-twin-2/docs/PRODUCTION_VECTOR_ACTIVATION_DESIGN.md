# Production Vector Search Activation — Technical Selection

Status: **DRAFT — external review pending**

Owner: Codex

Research snapshot: 2026-08-27

Scope: design/selection only. No implementation, dependency, schema, or production-config change.

## Decision summary

Production activation must pass two independent gates:

1. A Brain Twin-shaped Japanese gold evaluation selects a pinned embedding profile.
2. A Windows 1k/10k/100k spike selects and tunes an ANN backend using canonical SQLite BLOBs.

The provisional pair is:

- **Embedding:** direct `sentence-transformers` provider with pinned
  `Qwen/Qwen3-Embedding-0.6B`, a frozen Japanese retrieval instruction, normalized output, and
  initially 1024 dimensions.
- **Backend:** `faiss-cpu` HNSW, persisted as a disposable generation-stamped sidecar and rebuilt
  only from valid canonical SQLite embedding BLOBs.

This is not adoption. Qwen must beat the required challengers on Japanese quality and Windows
CPU/RAM. FAISS must pass ANN recall, CRUD/rebuild, crash, packaging, and resource gates.
`BAAI/bge-m3` is the long-Memory quality challenger; `nomic-embed-text-v2-moe` and
`gte-multilingual-base` are efficiency/context challengers. LanceDB is the backend challenger.
`ExactScanBackend` remains the reference/fallback/small-Vault backend.

## Requirements and invariants

- Japanese-first retrieval, Japanese/English mixed text, short queries, and long Memories.
- Fully offline after an explicit model acquisition step; no implicit runtime download.
- Windows x86-64 and Python 3.12 distribution without a user C++ toolchain.
- Pinned model revision/runtime/prompt/dimension/normalization and reproducible results.
- Interactive 1k/10k and a credible 100k path; latency, peak RSS, and disk must be measured.
- Delete/update, inactive/stale exclusion, interrupted rebuild, and corruption recovery.
- Provider and backend remain independently replaceable.

```text
Markdown / Obsidian Vault       persistent Memory source of truth
            │
            ▼
SQLite canonical embedding BLOB derived canonical cache
            │
            ▼
ANN/exact backend index         disposable, rebuildable acceleration
```

- Backend identity is absent from `profile_fingerprint`.
- Normal `reindex` remains provider/model/network-free.
- Backend rebuild consumes valid canonical BLOBs and never calls the provider.
- Backend loss disables Vector/Hybrid clearly; lexical search and Markdown remain intact.

Published MIRACL/MTEB scores are screening evidence, not Brain Twin acceptance evidence. CPU
latency/RAM is marked for measurement rather than estimated. No packages/models were installed
during this design task.

## Embedding comparison

| Candidate | Japanese / mixed outlook | Short query / long Memory | Size / output / context | Windows, offline, license, revision | Decision |
|---|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | 100+ language candidate; Japanese gold test required | Custom retrieval instruction; 32k context | 0.6B; up to 1024, selectable dimensions; 32k | Direct ST/Transformers, local after prefetch; Apache-2.0; pin HF commit and runtime | **Provisional primary.** Best recent quality/context/size balance; CPU speed is the main risk |
| **BAAI/bge-m3** | Mature 100+ language candidate with Japanese benchmark coverage | Dense mode needs no query instruction; 8192 tokens | 568M; 1024; 8192 | ST/FlagEmbedding local path; MIT; pin commit/adapter | **Quality and long-text challenger.** Higher vector/CPU cost; sparse/ColBERT output is out of scope |
| **multilingual-e5-large-instruct** | Established 94-language Japanese baseline | Explicit query instruction; 512-token long-Memory risk | ~560M; 1024; 512 | Standard local ST path; MIT; pin commit | **Quality baseline**, not primary due context/CPU cost |
| **multilingual-e5-base** | Established lower-cost multilingual baseline | Query/document prefix contract; 512 tokens | ~278M; 768; 512 | Standard local ST path; MIT; pin commit | **Required efficiency baseline** |
| **nomic-embed-text-v2-moe** | Model card includes Japanese; strong multilingual claims | Required query/document prefixes; only 512 tokens | 475M total/305M active; 768 or 256; 512 | ST requires `trust_remote_code=True`, or Ollama; Apache-2.0; pin model and custom code | **CPU/storage challenger.** 256-d is attractive; custom code and context are risks |
| **gte-multilingual-base** | 75 languages and strong published Japanese MLDR result | 8192-token input | ~305M; 768; 8192 | Local ST with `trust_remote_code=True`; Apache-2.0; pin/audit code | **Efficiency/context challenger** |
| **paraphrase-multilingual-MiniLM-L12-v2** | Japanese-capable sentence similarity, not modern IR specialist | Lightweight; 128-token ceiling | ~118M; 384; 128 | Mature local ST path; Apache-2.0; pin commit | **Control only**; long Memory unsuitable |
| **Ollama + Qwen/BGE/Nomic** | Same underlying model quality | HTTP isolation is simple; tag/quantization changes contract | Model-dependent | Good Windows UX; adds daemon/model store; Ollama MIT plus model license; pin digest/epoch, never `latest` | **Optional provider transport**, not default |

English-only BGE variants, `all-MiniLM-L6-v2`, and `mxbai-embed-large` are excluded because
Japanese-first quality is mandatory. Qwen 4B/8B are excluded from the general Windows CPU
default because model/RAM/latency and 2560/4096-d index costs are disproportionate; they remain
possible GPU profiles. Nomic and GTE were added because their dimension/context trade-offs are
material. Ollama is a transport, not a separate model family.

### EmbeddingProfile compatibility

The adapter owns query/document prompts, tokenization/truncation, pooling, and normalization.
Freeze these as follows:

| Contract item | Requirement |
|---|---|
| `provider_id` | Explicit `sentence_transformers` or `ollama` |
| `model_name` | Repository/model identity, not friendly alias alone |
| `model_revision` | Full HF commit or exposed immutable Ollama digest |
| `profile_epoch` | Mandatory when immutable revision cannot be guaranteed |
| contract version | Increment for prompt, truncation, pooling, adapter, or quantization changes |
| dimension | Explicit; Matryoshka truncation creates a different profile |
| normalized | `true`, validated for finite values and L2 norm |
| document template | Existing versioned `title` + `content` canonical document |

BGE-M3 must emit one dense vector only. E5/Nomic asymmetric prefixes and Qwen instruction are
profile behavior. Long-input truncation is explicit; future chunking is a new document-template
contract, not part of this activation.

## Vector backend comparison

| Backend | Windows / Python 3.12 / install | Scale and ANN | Filter / update-delete | Recovery / canonical-BLOB fit | Decision |
|---|---|---|---|---|---|
| **FAISS CPU 1.15.0** | Official Windows x86-64 CPython 3.12 PyPI wheel (~16 MB); MIT | Mature exact/HNSW/IVF; credible 100k+ path | Integer IDs; semantics vary by index, so HNSW adapter needs tombstones + rebuild | Save disposable sidecar; build by streaming valid BLOBs; SQLite owns metadata | **Provisional primary spike.** Strongest current ANN maturity + official wheel; adapter lifecycle must be proven |
| **LanceDB OSS 0.37.1** | Apache-2.0; official cp310-abi3 Windows wheel (~71 MB); PyPI labels Alpha | HNSW/IVF-PQ plus exact bypass; credible 100k | Native filters/update/delete and stable-row-ID option | Embedded durable dataset/index, rebuildable but duplicates storage/lifecycle | **Challenger** if FAISS adapter risk is excessive |
| **sqlite-vec 0.1.9** | MIT/Apache-2.0; Windows `py3-none` wheel; prior Windows load/CRUD/KNN spike passed | Fast exact `vec0`; official project is pre-v1; do not assume ANN/100k interactive | Metadata/aux/partition; tested update is delete+insert | Excellent same-SQLite rebuild fit | **Exact/mid-scale candidate, not current ANN primary** |
| **hnswlib 0.8.0** | Apache-2.0; official PyPI latest (2023) is source-only | Focused HNSW, good 10k/100k algorithmic fit | Mark-delete/replacement/update; no metadata engine | Simple save/load sidecar, rebuildable | **Not selected:** unacceptable Windows compiler/release risk |
| **Qdrant local/server** | Apache-2.0 Python 3.12 client; local mode exists; server adds binary/container/process | HNSW, payload indexes, WAL, 100k+ | First-class filters/CRUD | Rebuildable, but duplicate durable store; official docs warn about Windows Docker/WSL mounts | **Future service/mobile split**, not desktop default; local mode is documented for dev/prototyping/testing |
| **USearch 2.26.0** | Apache-2.0; small official Windows CPython 3.12 wheel | Fast ANN and sidecar persistence | Python binding lacks native filter predicates; lifecycle needs spike | Strong rebuildable-sidecar fit | **Secondary fallback spike**, lower priority than FAISS |
| **ExactScanBackend** | Existing, no optional dependency | Correct at 1k; Windows 10k/384 and 10k/768 too slow for primary | Existing valid/active filtering | Simplest, reads canonical cache | **Keep unchanged** as reference/fallback/small-Vault |

Raw float32 payload, excluding SQLite/HNSW/ID/alignment overhead:

| Count | 384 d | 768 d | 1024 d |
|---:|---:|---:|---:|
| 1k | 1.5 MiB | 2.9 MiB | 3.9 MiB |
| 10k | 14.6 MiB | 29.3 MiB | 39.1 MiB |
| 100k | 146.5 MiB | 293.0 MiB | 390.6 MiB |

PA3 measures full disk amplification and peak RSS, including atomic-rebuild headroom.

## Recommended architecture

```text
explicit pinned model acquisition
        ▼
SentenceTransformersProvider (provisional Qwen3-Embedding-0.6B)
        ▼
EmbeddingService
        ├── SQLite canonical BLOB/hash/profile/is_valid  ← canonical derived cache
        └── FaissHnswBackend generation sidecar         ← disposable ANN
                      ▼
 top IDs → SQLite active/valid filter → Hybrid RRF → existing 1-hop expansion
```

FAISS initially stores only ID/vector plus a manifest. SQLite owns active/profile validity.
Search uses bounded ANN overfetch, filters candidate IDs in SQLite, and increases overfetch to a
fixed cap. It returns fewer than K rather than leak stale/inactive rows. Future complex ACL/filter
requirements should trigger LanceDB/Qdrant reconsideration, not an ad-hoc duplicate metadata DB.

HNSW `M`, construction/search `ef`, threads, and candidate overfetch are not guessed here; PA3
tunes them against Recall@K, latency, memory, and disk. Backend/build parameters belong to
backend state/manifest, not `EmbeddingProfile`.

## Fallback architecture

- If no model passes Japanese quality + CPU/RAM: keep production activation pending; retain
  lexical and ExactScan diagnostic/small-Vault behavior. Do not ship a weak model for schedule.
- If FAISS fails packaging/recovery/recall: spike LanceDB on the same BLOB fixture, then USearch.
  Embeddings/profile are unchanged.
- Missing/corrupt/stale ANN produces a typed unavailable error and rebuild guidance. ExactScan is
  not silently used for a large Vault.
- Ollama may replace direct ST for users already standardizing on it, but must pass the identical
  contract and gold dataset with digest/quantization/profile identity.

## Migration, update, and recovery

1. Validate config, immutable model revision/epoch, local availability, runtime, instruction,
   dimension, normalization, and license notice without changing active state.
2. Create the profile; stream active Memories and resumably generate missing/stale BLOBs.
3. Verify every active row has a finite normalized dimension-correct valid BLOB.
4. Build ANN into a new sidecar generation without calling the provider.
5. Verify profile/dimension/count, sampled ANN-vs-Exact recall, and search smoke cases.
6. Atomically activate only after both stages pass; retain the prior ready generation for bounded
   rollback and explicit cleanup.

Canonical cache remains write-first under existing invalidation transactions. Treat HNSW deletion
conservatively: logical tombstones + bounded overfetch, with periodic full rebuild at a measured
ratio. Update is tombstone-old + add-new. Sidecar writes use a same-filesystem temporary file and
atomic replace. Manifest includes backend/version/build parameters/profile fingerprint/dimension/
count/canonical snapshot marker and checksum where practical.

Missing/malformed manifest, load failure, count/profile/dimension mismatch, or impossible ID makes
the backend unavailable. Backend rebuild streams BLOBs fully offline and never rewrites Markdown.
SQLite loss still requires Vault reindex, explicit provider-backed embedding regeneration, then
provider-free ANN build; normal `reindex` itself remains provider-free.

## Windows considerations

- Record/pin Windows architecture, Python, NumPy, Torch, Transformers, Sentence-Transformers,
  tokenizer, model commit, FAISS, and CPU feature set.
- Prove a clean Python 3.12 wheel-only install. Optional native dependencies are lazy imports.
- Model acquisition is explicit and shows size/license/checksum/destination; runtime uses
  local-files-only mode.
- Never use mutable model/Ollama `latest`; record digest, quantization, Ollama version, dimension,
  and epoch.
- Sidecars live in derived data, not the Vault; test antivirus/file-lock behavior around replace.
- LanceDB’s x86-64 Haswell-targeted wheel requires an older-CPU compatibility check.
- Qdrant server is not zero-ops: official docs flag Windows Docker/WSL mount concerns.

## Japanese retrieval evaluation plan

### Gold dataset

Create a versioned, privacy-safe set of **120 queries over 300–500 synthetic or explicitly
anonymized Memories**, with graded relevant IDs and at least 100 hard negatives. Never commit a
real Vault. Use about ten queries for each required slice:

1. Japanese query → Japanese Memory.
2. Paraphrase.
3. Synonyms.
4. Omission/context-dependent phrasing.
5. Proper nouns and project codes.
6. Katakana/transliteration (`サーバー`/`サーバ`, `GitHub`/`ギットハブ`).
7. Kanji/hiragana variation (`取扱い`/`取り扱い`, `出来る`/`できる`).
8. Japanese + English mixed/cross-lingual text.
9. Semantic match with little lexical overlap.
10. Lexical-sufficient exact names/IDs/dates.
11. Unrelated queries and hard false-positive cases.
12. 1–3 token queries and Memories near 512, 2k, and 8k tokenizer lengths.

Each query has stable ID, text, slice tags, graded relevance `{0,1,2,3}`, optional must-hit ID,
lexical-sufficient flag, and adjudication note. Each Memory has stable synthetic ID, title/content,
language tags, length bucket, and active state. Two judges calibrate 30 queries and resolve
disagreements. Separate development/blind subsets (80/40) prevent prompt/RRF overfitting.

### Runs and metrics

For every pinned profile run lexical-only, vector-only, and existing Hybrid at K=1/3/5/10; record
cold first query and 30 warm repeats on the same Windows machine. Separate short/long slices and
native/explicit Matryoshka dimensions. Use ExactScan as quality truth, then ANN to isolate index
recall loss. Freeze document template and truncation; each instruction variant is a named profile.

Report macro/per-slice Recall@K, MRR@10, nDCG@10, must-hit@5, false-positive@5, latency median/p95/
max, embedding throughput, peak RSS, model disk, canonical disk, and index disk. Include 95%
bootstrap confidence intervals and paired query deltas against lexical and E5-base.

Before the blind run, external review fixes numeric model latency/RAM gates. The winner must improve
semantic/paraphrase hits without material proper-noun/lexical regression, avoid unexplained critical
slice collapse, meet Windows CPU/RAM, and reproduce vectors within documented tolerance across two
clean runs. ANN acceptance additionally requires sampled ANN-vs-Exact `Recall@10 >= 0.98`, zero
inactive/stale leakage, and pre-agreed 10k/100k latency/rebuild/RSS gates. Tune Hybrid weights only
after model selection so model and ranker changes are not confounded.

## Risks, alternatives, unresolved questions

| Risk | Mitigation |
|---|---|
| Benchmarks do not predict personal Japanese Memory | Blind Brain Twin gold set and per-slice results |
| Qwen 0.6B is too slow | E5-base, Nomic 256/768, and GTE challengers; predeclare CPU/RAM gate |
| Long Memory truncates silently | Token-length buckets/logging; BGE/GTE challenger; chunking is later versioned contract |
| Native wheel regression | Hash/version pin, clean Windows install, optional dependency isolation |
| HNSW tombstone growth | Measured rebuild threshold and bounded overfetch |
| ANN diverges/corrupts | Manifest/generation checks, atomic replace, provider-free rebuild |
| Backend becomes accidental SOT | Only canonical SQLite BLOB is valid build input; never reverse-import |
| `trust_remote_code` supply chain | Prefer plain model; otherwise immutable commit and code audit |
| Ollama tag/quantization drift | Digest + quantization + version + epoch contract |

Alternatives: select BGE-M3 if long-Japanese quality justifies cost; select GTE/Nomic if smaller
vectors retain quality; select LanceDB if native lifecycle/filtering outweighs dependency/storage
cost; select Qdrant only with a future desktop/mobile service split.

Unresolved before formal ADR acceptance:

1. Minimum Windows CPU/RAM and numeric cold/warm latency budget.
2. Exact Qwen instruction and 1024 versus smaller output dimension.
3. Long-Memory truncation acceptance versus a later chunking design.
4. FAISS ID map, tombstone threshold, thread policy, sidecar/manifest format.
5. Numeric 100k rebuild/RSS/index-size gates.
6. One default model versus quality/lightweight profiles.
7. Redistribution versus user download and license-notice UX.
8. ExactScan warning threshold between measured 1k and 10k.

## Implementation Sprint proposal

No Sprint below is authorized by this draft.

### PA1 — Japanese retrieval evaluation harness

Add privacy-safe gold fixtures/schema, experiment manifest, lexical/vector/hybrid runner, metrics,
latency/RSS, and ExactScan oracle. Evaluate Qwen, BGE-M3, E5 base/large, Nomic, GTE, and MiniLM.
Gate: external review chooses an exact profile or stops activation.

### PA2 — Production embedding provider

Implement only the selected direct ST provider and explicit acquisition/offline verification.
Test revision, prompt, truncation, dimension, normalization, determinism, failures, resume, and no
implicit network. Ollama is separate optional scope. Gate: clean Windows install and review.

### PA3 — Production ANN backend

Spike FAISS HNSW, LanceDB, and optionally USearch against identical precomputed BLOBs at
1k/10k/100k and the selected dimension. Measure exact recall, CRUD/tombstones, filtering, rebuild,
atomic replace, corruption, RSS/disk, latency, and wheel install. Implement one backend only after
the spike decision.

### PA4 — Integration/recovery/production benchmark

Integrate selected provider/backend through existing contracts. Validate profile switching, full
loss, interrupted rebuild, invalid/inactive exclusion, lexical availability, Hybrid + Related,
rollback/cleanup, then rerun blind Japanese and Windows 1k/10k/100k acceptance. Gate: external
production-activation GO; no Phase 5.

Dependencies: PA1 selects the profile before PA2. PA3 may start with frozen vectors, but final
parameters require PA1’s dimension. PA4 depends on PA2 and PA3.

## Official sources consulted

- [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [BGE-M3](https://huggingface.co/BAAI/bge-m3)
- [multilingual-e5-large-instruct](https://huggingface.co/intfloat/multilingual-e5-large-instruct)
- [Nomic Embed v2 MoE](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe)
- [GTE multilingual base](https://huggingface.co/Alibaba-NLP/gte-multilingual-base)
- [Sentence Transformers API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
- [Ollama embeddings](https://docs.ollama.com/capabilities/embeddings)
- [FAISS install](https://github.com/facebookresearch/faiss/blob/main/INSTALL.md) and
  [PyPI files](https://pypi.org/project/faiss-cpu/)
- [sqlite-vec repository](https://github.com/asg017/sqlite-vec) and
  [PyPI files](https://pypi.org/project/sqlite-vec/)
- [hnswlib repository](https://github.com/nmslib/hnswlib) and
  [PyPI files](https://pypi.org/project/hnswlib/)
- [LanceDB API](https://lancedb.github.io/lancedb/python/python/),
  [vector search](https://docs.lancedb.com/search/vector-search), and
  [PyPI files](https://pypi.org/project/lancedb/)
- [Qdrant local quickstart](https://qdrant.tech/documentation/quick-start/),
  [storage/WAL](https://qdrant.tech/documentation/manage-data/storage/), and
  [installation](https://qdrant.tech/documentation/installation/)
- [USearch repository](https://github.com/nomic-ai/usearch) and
  [PyPI files](https://pypi.org/project/usearch/)
