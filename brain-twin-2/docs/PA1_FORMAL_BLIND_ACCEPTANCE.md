# PA1 Formal Blind Acceptance Contract

Status: tooling prepared; **no formal blind run has occurred**.

## Isolation model

The committed v2 benchmark is open-development evidence only. Formal acceptance uses a private held-out source that is never committed to the repository or exposed to the tuning workspace.

Formal artifacts are physically separated:

1. **private held-out source** — Memory/query text plus all judgements;
2. **blind runner package** — Memory/query text and IDs only; no labels;
3. **private judgement package** — slice tags, graded relevance, must-hit IDs, lexical-sufficient labels and adjudication notes;
4. **ranking evidence** — model output IDs plus timing/RSS, but no query text or judgements;
5. **redacted formal report** — aggregate metrics only; per-query/slice/failure details are hidden.

For a genuine blind cycle, source, runner, private judgements, judge files, ranking evidence and private scoring outputs all remain **outside the Git repository**. `scripts/build_pa1_blind_packages.py`, `scripts/compare_pa1_judges.py`, `scripts/run_pa1_blind_candidate.py`, and `scripts/score_pa1_blind_evidence.py` enforce this boundary.

The model-execution script never accepts a private judgement file. Conversely, scoring happens only after ranking evidence has been sealed and transferred to the private adjudication environment.

## Public runner contents

The runner package deliberately excludes:

- `slice_tags`
- `relevance`
- `must_hit_ids`
- `lexical_sufficient`
- `adjudication_note`

The ranking evidence deliberately excludes both those fields **and query text**. A SHA-256 commitment binds runner, private judgements, ranking evidence and original held-out source together. Package mismatch/tampering fails closed.

## Two-judge adjudication

Before the held-out source is frozen, two independent relevance judgement packages must target the identical runner SHA-256.

`brain_twin_eval.adjudication` / `scripts/compare_pa1_judges.py` detect:

- relevance-grade disagreements;
- must-hit disagreements;
- hard-negative disagreements;
- mismatched query sets;
- mismatched runner commitments.

A non-hard-negative query must contain at least one positive relevance judgement. A hard-negative query may not contain positive relevance. Disagreements are adjudicated before the private source dataset SHA is frozen.

## Frozen retrieval configuration

Formal acceptance must not only pin the dataset and evaluator commit. It also pins an `expected_retrieval_config_sha256` computed from the retrieval configuration recorded in the experiment manifest:

- provider label;
- model name;
- immutable 40-character model revision;
- instruction ID;
- instruction-text SHA-256;
- dimension;
- normalization contract;
- document-template version;
- backend/reranker label;
- backend parameters, including any base embedding model revision/configuration.

Changing the model, revision, instruction, dimension, candidate-k, base model or other retrieval configuration after the policy is frozen causes the acceptance gate to fail.

## Acceptance policy

`brain_twin_eval.acceptance` requires the policy to pin:

- policy ID;
- held-out dataset version and SHA-256;
- exact evaluator Git commit;
- expected retrieval-config SHA-256;
- minimum query count;
- minimum Recall@5;
- minimum MRR@10;
- minimum nDCG@10;
- minimum must-hit@5;
- maximum false-positive@5;
- maximum warm p95 latency;
- maximum peak RSS;
- maximum warm ranking-drift count.

For a formal decision, runtime ceilings may not be `null`. An incomplete policy returns `blocked`, never `pass`.

The final report must also prove `held_out` judgement visibility, `blind` split, redacted query details, matching dataset identity, exact evaluator commit and matching retrieval-config hash.

Use `scripts/evaluate_pa1_acceptance.py` only after the policy is frozen. Failed/blocked decisions return a non-zero exit code.

## Anti-leakage rules

- Never commit private source, blind runner, private judgements, judge packages, ranking evidence, or unredacted scoring diagnostics.
- Never tune instructions, dimensions, candidate-k, hybrid weights or reranker settings after viewing held-out outcomes.
- The blind runner is introduced only after the retrieval configuration is frozen; query text itself is withheld from the normal tuning workspace.
- Open-benchmark diagnostics may be used for iteration.
- A new tuning decision after blind evaluation requires a new held-out cycle; do not recycle the old blind set as development data.

## Current blocker

The actual Windows machine/runtime has not yet been measured. Therefore latency/RSS ceilings are intentionally **not invented**. They must be frozen from the characterized target machine class before formal held-out scoring is viewed.
