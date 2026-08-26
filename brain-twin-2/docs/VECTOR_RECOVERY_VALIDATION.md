# Vector Search Recovery / Migration / Corruption Validation

Status: implemented; **external review pending**. Do not treat this document as an
external-review GO.

This document records Sprint 4D's failure/recovery/migration/corruption validation (task
items 6-9). Coverage is split between:

- **Pre-existing focused unit tests** (already in the 306-test baseline before this round),
  which test individual mechanics in isolation.
- **New end-to-end integration tests** added this round (`tests/test_recovery_validation.py`,
  `tests/test_legacy_migration_combined.py`), which chain several of those mechanics together
  through the actual public APIs (`vector_search()`, `hybrid_search()`,
  `retrieval.retrieve_from_primary()`, `pipeline.reindex()`) to validate the full recovery
  story, not just internal repository state.

Every scenario below was executed as a real `pytest` test against a real (temporary, isolated)
SQLite database — not simulated or asserted from documentation alone.

## 6. Failure / recovery validation

### A. Provider partial failure -> resume

**Covered by (pre-existing):** `tests/test_embedding_service.py::test_partial_progress_is_resumed_without_reembedding_success`

Scenario executed: 5 Memories, a provider that fails on its 2nd batch call. `sync()` raises;
inspecting `memory_embeddings` afterward shows exactly the 2 already-committed rows (the
active profile is untouched, since profile switch only happens after full completion). A
second `sync()` with a working provider embeds only the 3 remaining Memories (skips the 2
already done) and reaches full `ready` state. Matches the task's "1000→一部成功→failure→
committed batch保持→再実行→残件resume→最終ready" shape exactly (at a smaller N for test speed;
size does not change the mechanism, which operates in fixed-size commit chunks regardless of
total dataset size).

### B. Profile switch failure -> old active profile/backend preserved, retry succeeds

**Covered by (pre-existing):**
`tests/test_embedding_service.py::test_profile_switch_occurs_only_after_successful_build`,
`tests/test_embedding_service.py::test_partial_new_profile_failure_keeps_old_active_and_resumes`

Scenario executed: an old profile is active and fully synced. Switching to a new profile with
a backend whose `build()` raises (or a provider that fails partway through the new profile's
embedding) leaves `active_profile_fingerprint` pointing at the **old** profile the entire
time — new-profile rows are written to the canonical cache (so they aren't recomputed on
retry) but the active pointer and backend `build_status` never move until a subsequent
`sync()` completes cleanly, at which point the switch happens.

### C. Backend index / bookkeeping loss -> Vector Search unavailable -> `rebuild_backend()` -> recovered

**Covered by (pre-existing, mechanics only):**
`tests/test_embedding_service.py::test_backend_only_rebuild_never_calls_provider`,
`tests/test_embedding_service.py::test_backend_only_rebuild_rejects_incomplete_canonical_cache`

**New end-to-end test:**
`tests/test_recovery_validation.py::test_backend_index_loss_recovers_via_backend_only_rebuild_without_provider`

Scenario executed: sync a Memory to a ready state, confirm `vector_search()` works, then
delete the `vector_backend_state` row directly (simulating lost backend bookkeeping/index
while canonical embedding BLOBs remain intact). `vector_search()` now raises
`VectorSearchUnavailableError` as designed (no silent fallback). Calling
`EmbeddingService.rebuild_backend()` with a provider stub that raises `AssertionError` if
ever called succeeds and restores `vector_search()` to working order — proving the recovery
path truly never calls the provider, only rebuilds the derived backend index from the
still-intact canonical cache.

### D. Stale Memory (title/content changed) -> excluded from Vector-only, still reachable via Hybrid's lexical channel, restored after resync

**New end-to-end test:**
`tests/test_recovery_validation.py::test_stale_memory_excluded_from_vector_but_reachable_via_hybrid_lexical_until_resync`

Scenario executed: sync a Memory, confirm Vector Search finds it. Change its title/content
(the existing `memories_embedding_invalidate_au` trigger marks the cached vector `is_valid=0`
immediately and independently of any later transaction). `vector_search()` on the new content
now correctly returns nothing (a stale vector is never served as valid). `hybrid_search()` on
the same new content **does** still find the Memory — its `lexical_rank` is set and
`vector_rank` is `None`, confirming Hybrid's BM25 channel is unaffected by embedding
staleness. A subsequent `sync()` re-embeds the changed content and `vector_search()` finds it
again.

### E. Inactive / deleted Memory exclusion

**Covered by (pre-existing):**
`tests/test_vector_search.py::test_vector_search_excludes_inactive_memory`,
`tests/test_vector_storage.py::test_exact_scan_excludes_inactive_memory`,
`tests/test_vector_storage.py::test_memory_delete_cascades_embedding`,
`tests/test_retrieval.py::test_inactive_related_memory_is_excluded`,
`tests/test_search.py::test_search_lexical_candidates_excludes_inactive`,
`tests/test_search.py::test_memory_ranking_signals_excludes_body_and_inactive`,
`tests/test_embedding_service.py::test_archived_memory_is_excluded`,
`tests/test_embedding_service.py::test_delete_cache_then_sync_regenerates_and_explicit_delete_syncs_backend`

An inactive (`archived`) Memory is excluded from Vector Search, Hybrid's lexical candidates,
lightweight ranking signals, and Associative Retrieval's related-Memory expansion alike.
Deleting a Memory's row cascades its cached embedding; `EmbeddingService.delete_cached_embedding()`
explicitly applies the canonical deletion before syncing the backend-specific index, keeping
the two in the correct order.

## 7. Full SQLite deletion -> reindex -> resync (most important scenario)

**New end-to-end test:**
`tests/test_recovery_validation.py::test_full_sqlite_delete_recovery_restores_lexical_link_and_vector_search`

This is the single most important recovery path: SQLite is documented as a rebuildable
index/cache, Markdown is the source of truth. Scenario executed, using the real
`pipeline.add_capture()` / `pipeline.process_all()` flow (not direct DB inserts) so this test
exercises the same Markdown-authoritative path a real crash-recovery would:

1. Build a small Vault with two related Memories (a real auto-generated Link between them via
   the existing classifier/linking pipeline).
2. Sync embeddings; confirm Vector Search works.
3. Snapshot the byte content of every `*.md` file under the Vault (Memory, Daily Log, and Raw
   Log files alike).
4. **Delete the SQLite file entirely** (`config.db_path.unlink()`).
5. Run `pipeline.reindex(config)`.
6. Confirm:
   - Every Markdown file's bytes are **unchanged** (`markdown_after == markdown_before`) —
     Raw Log text is never rewritten by reindex.
   - Memory count and Link count are restored (`counts["memories"] == 2`,
     `counts["links"] >= 1`).
   - Plain lexical search returns the same result as before deletion.
   - Associative Retrieval's related-Memory result (Link + restored `strength`) is identical
     to before deletion.
7. Confirm Vector Search is correctly `VectorSearchUnavailableError` immediately after the
   rebuild (embeddings are derived state and correctly do **not** survive a SQLite wipe).
8. Run `EmbeddingService.sync()` with the offline fake provider again; confirm it re-embeds
   exactly `counts["memories"]` items, and that Vector Search, Hybrid Search, and Hybrid +
   Related 1-hop expansion all work again afterward (using a `limit=1` Hybrid Primary call to
   force the linked Memory out of `primary` so the related-expansion path is actually
   exercised, not skipped because both Memories already appear in Primary at a larger limit).

Result: **full recovery confirmed** — Markdown/Raw Log untouched, Memory metadata + FTS + Link
+ strength restored from Markdown alone, and Vector/Hybrid/Associative Retrieval all resume
working after an embedding resync, with no manual intervention beyond running `reindex` and
`embeddings sync`.

## 8. Legacy migration validation

**Covered by (pre-existing, one gap at a time):**
`tests/test_vector_storage.py::test_legacy_database_gets_non_destructive_embedding_migration`,
`tests/test_vector_storage.py::test_connect_recreates_all_dropped_embedding_cache_tables`,
`tests/test_vector_storage.py::test_connect_self_heals_embedding_cache_missing_validity_column`,
`tests/test_db_entities_links.py::test_connect_self_heals_pre_phase2_links_table_missing_reason_column`,
`tests/test_db_entities_links.py::test_connect_self_heals_pre_review_memory_entities_missing_confidence_columns`,
`tests/test_db_entities_links.py::test_connect_self_heals_links_table_missing_strength_column`,
`tests/test_retrieval_strength.py::test_legacy_link_details_without_strength_reindex_with_conservative_fallback`

**New combined test:**
`tests/test_legacy_migration_combined.py::test_connect_self_heals_a_fully_legacy_database_without_touching_unrelated_data`

The new test builds one SQLite fixture combining every legacy gap at once — the kind of
database that would exist if a Vault had been running since before Phase 2/Sprint 4A: `links`
missing both `reason` and `strength`, `memory_entities` missing `confidence`/`method`,
`memory_embeddings` missing `is_valid`, and `embedding_profiles` /
`active_embedding_state` / `vector_backend_state` **entirely absent** — plus an unrelated
`operator_notes` table with data that must survive untouched. Confirmed in one `db.connect()`
call:

- The unrelated table and its row are untouched.
- All previously-absent embedding tables are created.
- The legacy embedding row self-heals to `is_valid = 0` (safe side: invalid, not silently
  trusted as valid).
- `links`/`memory_entities` self-heal their missing columns.
- The legacy link's `strength` restores to the conservative fallback
  (`db.LEGACY_LINK_STRENGTH`), not an invented high-confidence value.
- `memories_fts` is present and queryable after self-heal.
- A subsequent `pipeline.reindex()` on this self-healed database still completes cleanly.

Markdown is never touched by any of this (self-heal is a SQLite-only operation), and no
migration path in this codebase writes SQLite-derived values back into the user's
`config.toml` — `embedding_config.py` only ever *reads* the user config; `db.py`'s self-heal
and `embedding_service.py`'s sync/rebuild never write to it.

## 9. Corruption / malformed cache

**Covered by (pre-existing):**
`tests/test_embedding_vector.py::test_dimension_mismatch_is_rejected`,
`tests/test_embedding_vector.py::test_malformed_blob_is_rejected`,
`tests/test_vector_search.py::test_vector_search_rejects_indexed_profile_mismatch`,
`tests/test_vector_search.py::test_vector_search_rejects_query_dimension_mismatch`,
`tests/test_vector_storage.py::test_exact_scan_rejects_query_dimension_mismatch`,
`tests/test_embedding_service.py::test_malformed_provider_batch_is_not_saved` (empty output,
wrong dimension, NaN, Infinity, and zero-vector provider outputs are all rejected before being
persisted).

All of these fail closed with a typed `EmbeddingError` subclass (`EmbeddingDimensionError`,
`EmbeddingValidationError`, or `VectorSearchUnavailableError`) rather than either crashing
uncontrolled or silently returning wrong results. None of them touch Markdown or the plain
lexical search path — `db.search()` / `search.search()` remain usable throughout every one of
these failure scenarios, since lexical search never reads `memory_embeddings` at all.

## Summary

| Item | Result |
|---|---|
| 6A provider partial failure resume | PASS (pre-existing coverage) |
| 6B profile switch failure preserves old active | PASS (pre-existing coverage) |
| 6C backend index loss -> `rebuild_backend()` recovery | PASS (new end-to-end test) |
| 6D stale Memory: Vector excludes, Hybrid lexical still finds, resync restores | PASS (new end-to-end test) |
| 6E inactive/delete exclusion | PASS (pre-existing coverage, many tests) |
| 7 full SQLite delete -> reindex -> resync | PASS (new end-to-end test) |
| 8 legacy migration (combined fixture) | PASS (new combined test + pre-existing per-gap tests) |
| 9 corruption/malformed cache | PASS (pre-existing coverage) |

## Known limitations

- All of the above ran against synthetic/small fixtures on this session's Linux environment,
  not a real user Vault (as required) and not the Windows dev machine.
- This validation exercises `ExactScanBackend` only; a future `SqliteVecBackend` production
  adapter will need its own equivalent recovery validation (index rebuild semantics for a real
  ANN index differ from `ExactScanBackend`'s "no separate index" design).
- No chaos/fault-injection at the OS/filesystem level (e.g. killing the process mid-`fsync`)
  was performed — the failure scenarios above are induced at the Python/provider/backend
  level, not via actual process kills or disk-level corruption.
