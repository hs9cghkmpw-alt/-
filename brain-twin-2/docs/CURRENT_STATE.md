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
  - Final hardening review: **complete**

## Last known good implementation

- Implementation commit: `e199bb2` (see Git history for full SHA)
- Commit title: `brain-twin-2: preserve link strength in retrieval`
- Local test count: **123 passed**
- GitHub Actions run: `32801919294`
- GitHub Actions result: **success**

## Completed review fixes — verify before Vector Search

### 1. Persist real link strength through Retrieval

Phase 2の実 `LinkSuggestion.strength` をMarkdown `link_details`とSQLiteへ保存し、
Retrievalも固定relation weightではなく保存値の合計でrankingする。legacy Linkは
relation種別によらない保守的なstrength `0.25`へ非破壊migration/reindexする。

- process / reindex / reconcile / crash recoveryで同じstrengthを復元
- strength列の無い既存DBはconnect時に非破壊self-heal

### 2. Avoid loading every related Memory body before applying `related_limit`

ranking前は本文を含まない軽量candidateだけを取得し、dedupe/ranking後の
`related_limit` IDに限ってtitle/content/type/event_dateを取得する。
outgoing/incoming、inactive除外、1-hop、決定的順序は維持する。

## Next authorized task

**Vector Search design review fixes implemented; external review pending.**

Do **not** begin Vector Search implementation until this design is reviewed and explicitly approved.
LLM integration, `ask`, Contradiction Detection, Memory Consolidation, and smartphone integration remain out of scope.

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
