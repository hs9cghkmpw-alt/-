# Claude Code Entry Point

Claude Code must treat the repository-wide `AGENTS.md` as the authoritative shared working agreement.

Before doing any implementation work in this repository:

1. Read `AGENTS.md`.
2. Read `brain-twin-2/README.md`.
3. Read `brain-twin-2/docs/CURRENT_STATE.md`.
4. Read the latest relevant entries in `brain-twin-2/docs/WORKLOG.md`.
5. Inspect `git status`, current branch, and recent Git history.
6. Pull the latest `brain-twin-dev` unless the user explicitly selects a different branch.
7. Run the existing tests before changing behavior when the environment permits it.

Do not rely on prior Claude conversation context as the project record. GitHub files and Git history are the shared handoff mechanism between Claude Code, Codex, ChatGPT, and humans.

`CURRENT_STATE.md`/`WORKLOG.md` can lag one commit behind a decision made directly in conversation (an external review GO, a completed-Sprint declaration, a scope change). Follow `AGENTS.md` Section 2 ("Authority and stale handoff documents"): when the current user's explicit instruction clearly authorizes proceeding, do not stop merely because those two files still show an older "pending review" / "do not begin next Sprint" status — treat that as a stale handoff-document lag, not a live blocker, and synchronize the docs as part of the normal end-of-task update instead of pausing to ask. The exceptions listed in that section (ambiguous instructions, repo/branch/scope mismatches, destructive operations, failing tests/CI, safety-rule conflicts, or genuine uncertainty about authorization) still apply — stop and ask in those cases.

At the end of every task, follow the completion protocol in `AGENTS.md`, including updating `WORKLOG.md` and `CURRENT_STATE.md`, running tests and `git diff --check`, committing/pushing, and verifying GitHub Actions when `gh` is available.

Do not modify the legacy `brain-twin/` project unless explicitly instructed.
