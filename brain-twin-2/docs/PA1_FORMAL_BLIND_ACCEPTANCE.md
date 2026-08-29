# PA1 Formal Blind Acceptance Protocol

Status: tooling prepared and sealed; **no formal blind run has occurred**.

This document defines the formal held-out acceptance boundary for PA1 Japanese retrieval quality.
It exists to prevent tuning leakage, configuration drift, after-the-fact threshold changes, and
accidental promotion of an open development result into production evidence.

## Scope

This protocol applies only after open-development candidate comparison has produced a concrete
retrieval profile worth testing. It does **not** select the model by itself and does not authorize a
production embedding provider, reranker, ANN backend, or Production Vector Search activation.

Open development and formal acceptance are deliberately separate:

- open development may inspect per-query/per-slice diagnostics and iterate;
- formal blind evaluation must use a private held-out corpus and a configuration/budget commitment
  made before the held-out query text is used by the model-side run;
- formal output is redacted to avoid turning the held-out set into another tuning set.

## Required pre-blind sequence

Use this order. Do not skip or reorder the commitment boundary.

1. Run open-development Qwen/challenger evaluation and inspect diagnostics.
2. Choose one candidate retrieval profile for formal testing.
3. Freeze the behavior-changing retrieval configuration with
   `scripts/freeze_pa1_retrieval_config.py` **before the blind runner/query package is introduced**.
4. Characterize the selected profile on the target Windows machine and freeze numeric runtime
   budgets plus the expected warm-repeat protocol in the formal acceptance policy.
5. Independently judge/adjudicate the genuine held-out corpus with two judges and freeze its private
   dataset version/SHA.
6. Build the judgement-free runner package and private judgement package outside the repository.
7. Create one launch envelope with `scripts/create_pa1_launch_envelope.py`, also outside the repo.
8. Run `scripts/run_pa1_blind_candidate.py` from the exact frozen evaluator Git commit with a clean
   tracked worktree. The script verifies the real Git HEAD before loading a model.
9. Score ranking evidence only in the private environment with
   `scripts/score_pa1_blind_evidence.py`; apply the frozen critical-slice rules there.
10. Run `scripts/evaluate_pa1_acceptance.py` with the same policy and launch envelope. Only a complete
    PASS at this stage is formal acceptance evidence.

## Retrieval behavior identity vs measurement protocol

The retrieval-configuration SHA is intentionally limited to settings that can change retrieval
behavior. This is necessary so it can be frozen without seeing the blind runner/query corpus.

Behavior identity includes, as applicable:

- provider/runtime label;
- model name and immutable revision;
- instruction ID and instruction text SHA-256;
- embedding dimension;
- normalization contract;
- document template version;
- query/document template hashes;
- reranker model/revision/instruction;
- reranker base embedding-model contract;
- base query/document template hashes;
- base dimension/normalization;
- reranker candidate-k;
- other behavior-changing backend parameters.

The retrieval behavior SHA intentionally excludes measurement or data-shape fields such as:

- `evaluation_k`;
- `warm_repeats`;
- `corpus_memory_count`;
- label-only candidate IDs.

Exclusion from the retrieval SHA does **not** mean these values are mutable during a formal cycle.
The acceptance policy and launch envelope independently freeze the evaluation `k`, expected
warm-repeat count, dataset identity, and runtime ceilings. Formal acceptance also verifies the exact
warm sample count (`query_count × expected_warm_repeats`).

## Launch Envelope

`BlindLaunchEnvelope` is the sealed cycle commitment. It binds:

- cycle ID;
- judgement-free runner SHA-256;
- private source dataset SHA-256 and version;
- acceptance-policy SHA-256;
- expected retrieval-config SHA-256;
- exact evaluator Git commit;
- evaluation `k` (formal PA1 uses 10);
- expected warm-repeat count;
- optional model-artifact manifest SHA-256;
- creation timestamp.

The envelope is created only after the retrieval profile, policy, dataset identity, and runtime
protocol have been frozen. Ranking evidence must carry the exact launch-envelope commitment.

## Git/repository integrity

Formal blind execution does not trust a typed `--git-commit` value as evidence.
Before any model is loaded or any blind query is executed, the runner:

1. resolves the actual repository HEAD using `git rev-parse HEAD`;
2. requires that HEAD to equal the envelope's evaluator Git SHA;
3. checks `git status --porcelain --untracked-files=no`;
4. rejects the run if tracked files are modified.

Untracked local model/evidence files are not treated as source-code changes, but all private blind
artifacts and formal outputs are required to remain outside the repository by the private-path guard.

## Model-side / private-side separation

### Model execution side

The judgement-free runner contains only what retrieval needs:

- synthetic/private Memory text and stable logical IDs;
- blind query IDs and query text;
- active state needed for corpus construction.

It does **not** contain:

- relevance grades;
- must-hit IDs;
- slice tags used for judgement/acceptance;
- hard-negative truth;
- adjudication notes.

The model side emits ranking evidence plus timing/RSS/runtime metadata. It cannot calculate quality
metrics.

### Private scoring side

Only the private scoring environment receives the hidden judgement package. It reconstructs the
committed dataset, validates runner/evidence/envelope commitments, scores the rankings, evaluates
critical slices, and creates the redacted formal report.

## Critical Slice Gates

Overall averages are not sufficient. A candidate must not pass formal acceptance while silently
failing an important Japanese-retrieval slice.

The policy supports private slice rules over:

- Recall@5;
- MRR@10;
- nDCG@10;
- must-hit@5;
- false-positive@5.

Each rule has a frozen slice tag, metric, comparator (`min` or `max`), and threshold. The complete
rule set is committed into a deterministic spec SHA-256 before launch.

To reduce tuning leakage, the final formal report/attestation exposes only:

- critical-rule spec SHA-256;
- number of critical rules;
- whether **all** frozen critical rules passed.

It does not expose private slice names, thresholds, or observed held-out slice values. Detailed
critical-slice evidence remains in the private adjudication environment.

## Acceptance Policy

The formal policy freezes at least:

- policy ID;
- held-out dataset version/SHA;
- exact evaluator Git SHA;
- expected retrieval-config SHA;
- minimum blind query count;
- expected warm-repeat count;
- overall quality gates;
- false-positive ceiling;
- warm p95 latency ceiling;
- peak RSS ceiling;
- maximum warm ranking-drift count;
- at least one critical-slice rule.

A policy with unresolved runtime ceilings or no critical-slice rule is not `formal_ready` and formal
acceptance is blocked.

The acceptance evaluator additionally requires:

- held-out judgement visibility;
- `blind` split;
- redacted query details;
- exact dataset/evaluator/config commitments;
- exact warm-sample count;
- policy/config/critical-slice attestations produced by the private scoring step;
- a matching launch envelope.

Changing the model, revision, instruction, dimension, templates, reranker/base contract,
candidate-k, or other behavior-changing configuration after policy freeze changes the retrieval
config SHA and therefore fails the cycle.

## Two-judge adjudication

Formal held-out labels must be independently judged before the dataset is frozen. The adjudication
tooling compares judge A/B on relevance grades, must-hit decisions, and hard-negative status and
surfaces disagreements for explicit resolution.

This tooling exists, but **actual two-judge adjudication of the final private held-out corpus has not
yet occurred**. Do not treat synthetic unit-test fixtures or the public v2 benchmark as a substitute.

## Artifact privacy

The following formal-blind artifacts must stay outside the Git repository:

- private source dataset;
- judgement-free blind runner;
- private judgement package;
- judge files and adjudication output;
- launch envelope;
- model-artifact manifest when used;
- ranking evidence;
- formal JSON/Markdown report;
- final acceptance decision.

Public/open development fixtures are not formal held-out evidence even if their query records use a
field named `blind`.

## Current evidence and blocker

Formal-blind protocol sealing implementation:

- commit: `6d08616d58d187d65df104bcb82a8705d2fe74aa`
- exact-SHA Actions run: `33227872937`
- job: `99034999663`
- result: **447 passed**

This proves the tooling contracts are regression-tested. It does **not** prove model quality or
formal acceptance.

Before the first formal cycle, still required:

- physical Windows execution of the prepared open Qwen matrix;
- measured Windows CPU/RAM/latency data for the selected profile;
- numeric runtime ceilings chosen from that evidence rather than invented;
- final model/instruction/dimension/reranker decision after open challenger comparison;
- genuine private held-out corpus creation;
- actual independent two-judge adjudication and frozen dataset SHA;
- then one sealed launch-envelope cycle.

Until those are complete: **PA1 formal acceptance is pending and Production Vector Search remains
PENDING.**
