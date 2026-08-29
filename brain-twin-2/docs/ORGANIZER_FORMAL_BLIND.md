# Organizer Formal Blind Protocol

Status: **protocol implemented; numeric policy intentionally DRAFT; no formal blind run performed**

## Objective

Select the Brain Twin organizer LLM without leaking held-out labels into model execution or changing acceptance rules after seeing private results.

This protocol is independent of retrieval PA1 ranking metrics. Organizer-specific risks are schema failure, destructive output, fabricated metadata, incorrect durable classification, bad temporal interpretation, wrong links, nondeterminism, and unacceptable Windows resource cost.

## Physical separation

Formal evaluation has three logical zones:

```text
private authoring / adjudication
  OrganizerDataset(judgement_visibility=held_out)
  - raw capture
  - gold metadata
  - slice labels
          |
          | build sealed packages
          v
model execution zone
  OrganizerPublicPackage ONLY
  - sample_id
  - raw_text
  - created_at
  - candidate context memories
  NO gold
  NO slice labels
  NO private dataset SHA
          |
          | private evidence: outputs + timing/RSS/determinism
          v
private scoring zone
  verify package/config/launch commitments
  score against private gold
  evaluate frozen policy
          |
          v
public decision
  PASS / FAIL
  policy SHA
  launch SHA
  boolean gates only
```

The formal model-side function accepts `OrganizerPublicPackage`; it does not accept `OrganizerDataset`. This prevents accidental in-process access to gold/slices.

## Private-artifact rule

Private organizer corpus, judgements, launch material containing private commitments, raw model evidence, adjudication files, and private score objects must remain outside the Git repository/tuning workspace.

`assert_private_artifact_outside_repo()` rejects repository-contained paths.

The committed open v1/v2 datasets are never formal-blind evidence.

## Package commitments

`build_organizer_blind_packages()` requires a held-out dataset and creates:

- `OrganizerPublicPackage`
  - model-side fields only;
  - its own SHA-256 computed without gold/slices.
- `OrganizerPrivateCommitment`
  - private dataset canonical SHA-256;
  - public package SHA-256;
  - dataset version and sample count.

The public package deliberately does not contain the private dataset SHA.

Formal packaging additionally validates:

- `created_at` is canonical ISO-8601 with explicit timezone offset;
- context Memory IDs/titles/summaries are non-empty and bounded;
- no duplicate context IDs;
- maximum 32 context Memories per sample.

## Organizer config identity

Before blind execution, `OrganizerRunConfig` freezes behavior-changing inputs:

- exact model revision;
- prompt SHA-256;
- schema SHA-256;
- chat-template/tokenizer SHA-256;
- runtime backend + exact runtime revision;
- quantization;
- temperature;
- top-p;
- max output tokens;
- seed;
- additional runtime parameters such as threads when relevant.

Any change creates a different config SHA-256.

## Acceptance policy

Code: `brain_twin_eval.organizer_formal`

Human-readable unresolved template: `evaluation_profiles/organizer_acceptance_policy_draft_v1.json`

The committed template is intentionally non-executable. It contains `null` thresholds because Windows/open model evidence does not exist yet. We do not invent numeric gates before measurement.

A `frozen` policy is rejected unless every required threshold has a value and at least one critical-slice rule is frozen.

Required overall gates:

### Quality minimums

- schema valid rate
- strict record accuracy
- memory-worthy F1
- Memory Type accuracy
- topic F1
- entity F1
- event-date exact rate
- event-date null/abstention accuracy
- importance within-one rate
- link F1

### Quality maximums

- entity false-positive/hallucination rate
- importance MAE
- confidence Brier score

### Runtime maximums

- determinism mismatch count
- warm p95 latency
- process peak RSS
- model/runtime artifact disk bytes

Critical-slice rules use private per-slice scores internally, but the public outcome exposes only one boolean `critical_slice_gate`. Slice names and private slice scores are not published from the formal decision object.

## Launch Envelope

`OrganizerLaunchEnvelope` is created only from a complete frozen policy and binds:

- cycle ID;
- private commitment SHA;
- private dataset SHA;
- public package SHA;
- organizer config SHA;
- policy SHA;
- evaluator exact Git commit;
- sample count.

The model evidence must carry the exact Launch Envelope SHA and exact organizer config/public package identities. Private scoring/acceptance fails closed on mismatch.

## Model-side evidence

`run_organizer_blind_package()` records:

- exact launch/config/public-package identity;
- candidate/model/revision;
- output per sample (PRIVATE evidence);
- first call latency;
- warm median/p95/max latency;
- process peak RSS before/after/growth;
- deterministic-repeat mismatch count.

The evidence object contains predictions and therefore stays private. The final public decision does not expose predictions, raw samples, sample IDs, per-slice metrics, or failure cases.

## Scoring and acceptance

1. Private scorer verifies exact held-out dataset commitment.
2. It verifies that evidence covers exactly the held-out sample IDs.
3. It evaluates with the strict organizer schema/metrics.
4. Formal acceptance verifies Launch Envelope, policy, config, dataset and package identities.
5. It evaluates all frozen quality/runtime gates.
6. It evaluates frozen critical-slice rules privately.
7. Public output is only:
   - `PASS` / `FAIL`;
   - policy SHA;
   - launch SHA;
   - boolean overall gate map;
   - boolean critical-slice gate.

No failure is repaired or regenerated during a formal cycle. Invalid JSON is a failed sample. Changing prompt, model, quantization, runtime or generation parameters requires a new config identity and therefore a new predeclared cycle.

## Formal launch blockers

Formal Organizer blind evaluation remains **STOP** until all are satisfied:

1. real Windows open-development runs exist for shortlisted models;
2. practical runtime/quantization path is chosen;
3. genuine held-out corpus is created outside repo/tuning workspace;
4. independent annotation/adjudication is complete;
5. entity aliases/canonical forms are resolved in gold rather than fuzzy-matched after the fact;
6. numeric quality/runtime thresholds are predeclared and frozen;
7. critical slices + thresholds are predeclared;
8. exact evaluator Git SHA and organizer config SHA are frozen;
9. independent review approves launch.

## Production boundary

Passing this protocol selects an organizer configuration for integration review. It does **not** by itself enable production processing.

Production integration still requires a separately reviewed adapter/fallback design that guarantees:

- Raw Log save happens before organizer inference;
- inference failure cannot lose or overwrite capture text;
- derived metadata has provenance/model fingerprint;
- retries are idempotent;
- existing Markdown/Vault SOT and reindex/recovery invariants remain intact.
