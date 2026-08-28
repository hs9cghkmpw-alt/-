# Brain Twin 2 — Work Log

See Git history and `docs/CURRENT_STATE.md` for current status.

## 2026-08-29 — ChatGPT — PA1 open benchmark expansion

- Branch: `brain-twin-dev`
- Base: `cac8e44a7cb8c08578d74c17601580c27861a2ac`
- Scope: continue PA1 evidence preparation after explicit user authorization; no production provider/backend/reranker integration.
- Changed: added deterministic `brain_twin_eval.open_gold_v2` generator for 360 synthetic Memories / 120 queries (80 dev / 40 blind-labelled), generation script, contract tests, and updated PA1 docs/current state. The public `blind` labels remain pipeline-only and are not formal held-out evidence.
- Known issues: formal held-out blind set, two-judge adjudication, tokenizer-aware 512/2k/8k cases, Windows budgets, real candidate model runs, and Qwen reranker OFF/ON measurements remain pending.
- Next: exact-SHA CI review, then candidate-evaluation scaffolding and real local model runs when an appropriate machine/runtime is available.
