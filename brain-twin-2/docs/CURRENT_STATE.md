# Brain Twin 2 — Current State

Last updated: 2026-08-25

## Active development context

- Repository: `hs9cghkmpw-alt/-`
- Project: `brain-twin-2/`
- Working branch: `brain-twin-dev`
- Legacy project `brain-twin/`: out of scope unless explicitly requested

## Current phase

- Phase 1 — Memory Foundation: **complete**
- Phase 2 — Automatic Memory Worker / Entity Extraction / Link generation: **complete**
- Phase 3 — Retrieval:
  - Associative Retrieval (1-hop outgoing + incoming links): **implemented**
  - Timeline Search (`event_date` range filtering): **implemented**
  - Final hardening review: **pending 2 fixes before Phase 3 is declared complete**

## Last known good implementation

- Implementation commit: `bfc679d8c13d549a637319af672a118d271f2f79`
- Commit title: `brain-twin-2: Phase 3 associative retrieval and timeline search`
- Local/CI test count: **117 passed**
- GitHub Actions run: `32797928602`
- GitHub Actions result: **success**

## Active review fixes — do these before Vector Search

### 1. Persist real link strength through Retrieval

Phase 2 computes a real `LinkSuggestion.strength`, including entity-confidence-aware strength. Phase 3 currently reconstructs ranking from fixed relation-type weights, which can accidentally make a low-confidence `same_entity` stronger than `same_topic` and reintroduce a problem already fixed in Phase 2.

Required direction:

- persist `strength` in Markdown `link_details`
- persist the same value in SQLite `links`
- restore it faithfully through process / reindex / reconcile / crash recovery
- provide a conservative backward-compatible fallback for old link details without strength
- Retrieval ranking must use persisted strength rather than fixed relation-type priority

### 2. Avoid loading every related Memory body before applying `related_limit`

Current associative retrieval can materialize every candidate Related Memory including `content`, then rank/dedupe and keep only the top N.

Required direction:

- obtain lightweight candidate/link signals first
- rank/dedupe candidates
- determine top `related_limit` IDs
- fetch full Memory details only for selected IDs
- preserve outgoing/incoming behavior, dedupe, inactive filtering, 1-hop limit, and deterministic ordering

## Next authorized task

**Phase 3 Retrieval hardening: implement the two review fixes above.**

Do **not** begin Vector Search, LLM integration, `ask`, Contradiction Detection, Memory Consolidation, or smartphone integration until these two fixes are reviewed and Phase 3 is explicitly marked complete.

## Core invariants

- Markdown/Vault is the persistent source of truth.
- SQLite is a rebuildable index/cache.
- Raw Log original text is preserved.
- `reindex` must reconstruct derived SQLite state from Markdown.
- Recovery must not reclassify an already-established historical Memory outcome with a newer classifier.
- Crash/retry behavior must remain idempotent and consistent.
- Keep modules maintainable, responsibilities separated, and tests isolated from real user data.
- Do not modify `brain-twin/` without explicit instruction.
- Work on `brain-twin-dev` unless the user explicitly changes the branch policy.

## Shared handoff protocol

All agents must follow repository-root `AGENTS.md`.
Claude Code also has repository-root `CLAUDE.md` as its entry point.
Every completed task must append to `docs/WORKLOG.md` and update this file if the state above changed.
