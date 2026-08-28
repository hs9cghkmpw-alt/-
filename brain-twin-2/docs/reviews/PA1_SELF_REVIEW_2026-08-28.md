# PA1 Self-Review — Japanese Retrieval Evaluation Harness

Date: 2026-08-28
Reviewer/implementer: ChatGPT
Branch: `brain-twin-dev`
Base before hardening: `1d4d70fdc26751538788729484aac1cdcc7dc528`
Hardened implementation: `5a2851534f9385ff0e4cc90af89195de300f890f`
Exact-SHA Actions run: `33177339391`
Result: **success — 370 passed**

## Verdict

**GO for the PA1 harness code, with independent external review still required.**

This is not a GO for model selection, production Vector Search activation, PA2, PA3, PA4, or Phase 5. No real candidate embedding model has been evaluated yet.

## Findings fixed

1. **Latency contract was incomplete.** The initial live runner measured one call per query and the report used an upper-middle element as the even-count median. The hardened runner records the first call plus 30 warm repeats/query by default, uses the mathematical median, nearest-rank p95 and max, records the first selected query separately, and detects ranking drift across warm repeats.
2. **RSS was specified but not implemented.** Added best-effort process peak RSS telemetry: Windows `GetProcessMemoryInfo(...).PeakWorkingSetSize`; POSIX `getrusage`. Telemetry failure does not fail quality evaluation.
3. **The committed `blind` split was not actually blind.** Its judgements live in the repository, so it can only test split plumbing. Added `judgement_visibility=open|held_out`, included it in canonical dataset identity, and redacted per-query/per-slice/failure diagnostics for held-out blind reports. A formal blind file must stay outside the tuning workspace.
4. **ANN oracle pairing was too weak.** Added run-level ExactScan-vs-ANN comparison requiring identical canonical dataset SHA, split, and query IDs.
5. **Manifest/report identity could be mixed.** Report generation now rejects a manifest whose dataset version/hash/judgement visibility does not exactly match the evaluation run.
6. **Uncertainty/comparison evidence was missing.** Added deterministic non-parametric 95% bootstrap CIs and paired candidate-minus-baseline query deltas.
7. **Manifest secret screening was narrow.** Broadened recursive key/value-shape rejection while continuing to store only the SHA-256 of instruction text.

## Architecture review

The comparison from `1d4d70f...` to `5a285153...` changes only:

- `brain_twin_eval/` evaluation package;
- PA1 evaluation tests;
- PA1/CURRENT_STATE documentation.

No production `brain_twin/` module, DB schema, provider runtime, vector backend, Vault behavior, or reindex behavior was modified. Production code still does not depend on `brain_twin_eval`.

## CI evidence

GitHub Actions checked out exact SHA `5a2851534f9385ff0e4cc90af89195de300f890f` on Ubuntu 24.04 / Python 3.11.16 and collected 370 tests. Result: `370 passed in 25.25s`.

## Remaining PA1 work

The harness is ready for an independent review, but semantic evaluation is not complete. Before selecting the production embedding profile, PA1 still needs:

- roughly 300–500 synthetic/privacy-safe Memories and about 120 adjudicated queries;
- a genuinely held-out blind judgement file outside the tuning workspace;
- two-judge calibration/adjudication;
- tokenizer-aware near-512 / 2k / 8k cases;
- predeclared Windows CPU/RAM/latency acceptance budgets;
- pinned candidate runs for Qwen/BGE-M3/E5/Nomic/GTE/MiniLM as authorized;
- Qwen English task instruction vs equivalent Japanese vs no-instruction comparison, with other variables fixed.

## Next action

Stop here for independent external review. Do not begin PA2/PA3/PA4 or Phase 5 from this self-review alone.
