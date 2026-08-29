# PA1 Formal Blind Acceptance Contract

Status: design + tooling prepared; no formal blind run has occurred.

## Purpose

The committed v2 benchmark is intentionally open and is useful for development only. It cannot be used as final production acceptance evidence because its relevance judgements are visible in the repository.

Formal blind acceptance therefore uses two physically separate packages:

1. **runner package** — safe to give to the evaluation machine/agent; contains Memory text, query text, IDs and split only;
2. **private judgement package** — contains slice tags, graded relevance, must-hit IDs, lexical-sufficient labels and adjudication notes. It must remain outside the repository and outside the tuning workspace.

`brain_twin_eval.blind` creates and verifies these packages. `scripts/build_pa1_blind_packages.py` refuses to write the private judgement package anywhere under the repository root.

The public runner package deliberately excludes:

- `slice_tags`
- `relevance`
- `must_hit_ids`
- `lexical_sufficient`
- `adjudication_note`

A SHA-256 commitment binds the public runner package to the private judgements and to the original full held-out dataset. Tampering or package mismatch fails closed.

## Acceptance policy

Formal acceptance is not "pick the best-looking report". A policy must be frozen **before** held-out results are viewed.

`brain_twin_eval.acceptance` requires the policy to pin:

- policy ID;
- held-out dataset version and SHA-256 commitment;
- exact evaluator Git commit;
- minimum query count;
- minimum Recall@5;
- minimum MRR@10;
- minimum nDCG@10;
- minimum must-hit@5;
- maximum false-positive@5;
- maximum warm p95 latency;
- maximum peak RSS;
- maximum warm ranking drift count.

For a formal decision, runtime ceilings may not be left `null`. A draft policy with incomplete Windows budgets returns `blocked`, never `pass`.

The report must also prove:

- `judgement_visibility == held_out`;
- `split == blind`;
- per-query details are redacted;
- dataset hash matches the policy;
- evaluator commit matches the policy.

Use `scripts/evaluate_pa1_acceptance.py` to apply a frozen policy. A failed or blocked policy returns a non-zero exit code.

## Two-judge policy

Before the private held-out dataset is frozen, two independent relevance judgements should be collected for the blind queries. Disagreements on positive relevance, must-hit membership, or hard-negative classification must be adjudicated before the dataset SHA-256 and acceptance policy are frozen.

The adjudicated private source is the only source from which the public/private blind packages should be built.

## Anti-leakage rules

- Never commit the private judgement package.
- Never copy private judgements into the model-selection workspace.
- Never tune instructions, dimensions, candidate-k, hybrid weights, or reranker settings after seeing held-out per-query outcomes.
- Open-benchmark diagnostics may be used for iteration; held-out acceptance may only produce the redacted formal report and gate decision.
- A new tuning decision requires a new held-out set or an explicit new evaluation cycle; do not silently recycle the same blind set as development data.

## Current blocker

The Windows machine class and real Qwen runtime evidence are not available yet, so final latency/RSS ceilings are intentionally not invented. They must be frozen after the machine is characterized and **before** the formal held-out run.
