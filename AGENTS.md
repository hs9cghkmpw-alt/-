# Shared Agent Working Agreement

This file is the repository-wide handoff protocol for **all development agents and humans** working in this repository, including Claude Code, Codex, ChatGPT reviewers, and human contributors.

## 1. Source of truth

Do not rely on chat history, model memory, or a previous agent's private context as the source of truth.

For Brain Twin 2, use these repository files and Git history:

1. `AGENTS.md` — shared operating rules
2. `brain-twin-2/README.md` — architecture, user-facing behavior, design decisions
3. `brain-twin-2/docs/CURRENT_STATE.md` — current phase, blockers, next task, last verified test/CI state
4. `brain-twin-2/docs/WORKLOG.md` — chronological handoff/work history
5. `git log` / `git diff` / tests — factual implementation history and current code state

If documentation conflicts with code or tests, **do not guess**. Inspect Git history, reconcile the discrepancy, and record the corrected state in `CURRENT_STATE.md` and `WORKLOG.md`.

## 2. Mandatory startup sequence

Before changing code, every agent must:

1. Confirm repository and branch.
2. `git fetch origin --prune`
3. Switch to the intended working branch. For the current Brain Twin workflow, use `brain-twin-dev` unless the user explicitly changes this rule.
4. `git pull --ff-only origin brain-twin-dev`
5. Run `git status` and do not overwrite unrelated local changes.
6. Read this `AGENTS.md`.
7. Read `brain-twin-2/README.md`.
8. Read `brain-twin-2/docs/CURRENT_STATE.md`.
9. Read the latest relevant entries in `brain-twin-2/docs/WORKLOG.md`.
10. Read recent Git history (`git log -5 --oneline` or more when needed).
11. Run the existing test suite before implementation when the environment permits it.

Do not begin from an old task prompt without first comparing it with `CURRENT_STATE.md` and the current HEAD.

## 3. Single-writer rule

Do not have Claude Code and Codex modify the same working branch at the same time.

Before starting, pull the latest `brain-twin-dev`. Before pushing, verify that the remote branch has not advanced unexpectedly. If another agent has pushed changes, inspect and integrate them deliberately; never overwrite them with a force push.

`git push --force` / `--force-with-lease` is prohibited unless the user explicitly authorizes it for a specific recovery operation.

## 4. Brain Twin 2 engineering rules

For `brain-twin-2/`:

- Markdown/Vault is the authoritative persistent memory source of truth.
- SQLite is a rebuildable search/index cache.
- Raw Log original text must not be destructively rewritten.
- `reindex` must remain able to reconstruct SQLite from Markdown.
- Do not reinterpret an already-established historical Memory outcome using a newer classifier during recovery.
- Preserve crash/retry idempotency and consistency between Markdown, Raw Log metadata, and SQLite.
- Prefer small, composable modules with clear responsibilities.
- Avoid spaghetti code, hidden global state, duplicated policy logic, and unnecessary cross-layer coupling.
- DB access belongs in the DB layer; retrieval/ranking policy belongs in retrieval/search logic; CLI should primarily parse arguments and present results.
- Tests must use isolated temporary Vault/DB locations and must never touch a real user Vault.
- Do not modify the old `brain-twin/` project unless the task explicitly requires it.
- Do not advance into a later phase merely because it is an obvious next step. Stop at the requested scope.

## 5. Security / privacy

Never put secrets into repository documentation, commit messages, or work logs, including:

- API keys
- access tokens
- passwords
- OAuth codes
- Supabase service-role secrets
- `.env` contents
- personal secrets or unnecessary sensitive user data

Record only the minimum operational information required for handoff.

## 6. Mandatory completion sequence

A task is not complete until the agent has:

1. Implemented only the agreed scope.
2. Added/updated tests for changed behavior.
3. Run the relevant local tests.
4. Run `git diff --check`.
5. Self-reviewed the diff for maintainability, regressions, and accidental unrelated edits.
6. Updated `brain-twin-2/docs/WORKLOG.md` with a concise factual entry.
7. Updated `brain-twin-2/docs/CURRENT_STATE.md` when phase/status/blockers/next-step/test-count/CI state changed.
8. Updated `brain-twin-2/README.md` when architecture, commands, user behavior, or durable design decisions changed.
9. Committed the changes with a meaningful commit message.
10. Pushed to the correct branch.
11. When GitHub CLI is available, verified GitHub Actions through `gh` and did not report completion while CI is failing.

Recommended CI flow on the current Windows development machine:

```powershell
gh run list --branch brain-twin-dev --limit 5
$RunId = gh run list --branch brain-twin-dev --limit 1 --json databaseId --jq '.[0].databaseId'
gh run watch $RunId --exit-status
# On failure:
gh run view $RunId --log-failed
```

If CI fails, diagnose, fix, retest, commit/push, and verify the new CI run before reporting completion.

## 7. WORKLOG entry format

Append a new chronological entry to `brain-twin-2/docs/WORKLOG.md`. Keep it concise and factual.

Suggested structure:

```markdown
## YYYY-MM-DD — Agent/Person — Short task name

- Branch: brain-twin-dev
- Base: <starting SHA>
- Scope: <what was requested>
- Changed: <important implementation changes>
- Tests: <local result>
- CI: <run ID and result, if available>
- Commit: <SHA, or "this commit" when self-referential>
- Known issues: <remaining limitations>
- Next: <the next authorized task, not extra work already performed>
```

Do not paste huge command transcripts into `WORKLOG.md`; summarize them.

## 8. CURRENT_STATE rules

`brain-twin-2/docs/CURRENT_STATE.md` is a snapshot, not a diary. Keep it short enough that a new agent can read it before every task.

It should always state:

- active repository/project/branch
- current phase and completion status
- last known good implementation commit
- last known test count/result
- last known CI result/run ID when available
- active blockers or review fixes
- next authorized task
- important invariants that must not be broken

When work changes any of those, update the file before the final commit.

## 9. Review behavior

A reviewer (including ChatGPT) must read the shared state files and inspect the actual GitHub commit/diff/tests/CI before issuing a GO/STOP decision when repository access is available.

A review must end with a concrete next action: either a fix instruction, a GO decision plus the next implementation instruction, or an explicit stop/blocker.
