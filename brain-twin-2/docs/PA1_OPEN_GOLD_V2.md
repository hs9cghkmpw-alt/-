# PA1 Open Gold v2 — Dataset Construction Note

Date: 2026-08-29

This document describes the generated **development** benchmark produced by
`brain_twin_eval.open_gold_v2`.

## Why a second dataset exists

The original 36-Memory / 24-query seed proved the evaluator contract, but it is too small to choose
a production embedding/reranker. v2 expands the open development corpus while keeping every item
synthetic and reviewable.

It intentionally does **not** pretend to be a hidden blind set.

## Shape

- 30 synthetic second-brain scenarios
- 12 Memories per scenario
  - 1 primary target
  - 1 partially relevant Memory
  - 10 same-entity/domain distractors
- 360 Memories total
- 4 queries per scenario
- 120 queries total
- 80 `dev`
- 40 `blind`-labelled pipeline cases
- 10 explicit no-answer hard-negative queries
- 5 inactive distractor Memories
- 5 long target Memories

The 300 same-entity/domain distractors make simple proper-noun matching insufficient for many
queries. This is deliberate: a retrieval model should distinguish *which fact about the same
subject* is being recalled.

## Reproducibility

Source of truth for construction logic:

`brain_twin_eval/open_gold_v2.py`

Materialize JSON when needed:

```powershell
python scripts/generate_japanese_retrieval_v2.py
```

The default output is `.evaluation-results/japanese_retrieval_v2_open.json` and remains uncommitted.
The tests validate the generated dataset directly, including deterministic identity and contract
counts.

## Privacy

All scenarios, entities, facts, schedules, products, companies, locations, codes and rules in v2
are synthetic. The generator does not inspect the user Vault and the output contains no real Vault
path.

## Interpretation

Use v2 for:

- open model development;
- Qwen instruction/dimension comparison;
- challenger screening;
- BM25/embedding/hybrid comparison;
- reranker OFF/ON development;
- regression testing.

Do not use v2 as the final production acceptance set because its judgements are derivable from
committed source.

## Formal acceptance

A separate held-out set must keep its judgements outside the tuning workspace. Acceptance budgets
must be predeclared before opening those results. The held-out set should also add tokenizer-aware
near-512 / 2k / 8k cases after the candidate tokenizers are locally available.
