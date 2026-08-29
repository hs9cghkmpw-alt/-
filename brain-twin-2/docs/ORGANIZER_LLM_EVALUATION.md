# Organizer LLM Evaluation

Status: **evaluation foundation — production integration not authorized**

## Purpose

The organizer is the structured-interpretation component in the Brain Twin target architecture. It is separate from embedding/reranking and must remain replaceable.

Its job is to derive metadata from a raw capture while the raw capture itself remains authoritative and unchanged.

This benchmark does **not** authorize replacing the current production classifier yet.

## Non-destructive boundary

Organizer input contains the original capture plus optional candidate Memory context. Organizer output may contain only derived metadata:

- `memory_worthy`
- `memory_type`
- `title`
- `topics`
- `entities[]` with confidence
- `event_date`
- `importance`
- overall classification `confidence`
- `link_candidates`

`content`, `raw_text`, `rewritten_text`, summaries that replace the Memory body, or any unknown output field are rejected by the strict evaluator contract.

If the organizer fails, returns invalid JSON, times out, or is unavailable, the original Raw Log must already be safely stored. Failure means "organization pending/retryable", not "capture lost".

## Output schema

Machine-readable schema: `evaluation_profiles/organizer_output_schema_v1.json`

Reference task instruction: `evaluation_profiles/organizer_system_prompt_v1.txt`

The Python evaluator intentionally uses a small dependency-free strict validator rather than adding JSON-schema runtime dependencies to production requirements.

Raw user captures are not classified as `ai_inference`; that Memory type is reserved for derived AI material, not source captures.

## Open benchmark v1

Generator: `brain_twin_eval.organizer_gold.build_organizer_open_v1()`

Properties:

- deterministic;
- 128 fully synthetic samples;
- no production Vault paths or real user data;
- all current raw-capture Memory types covered: fact, experience, thought, decision, preference, goal, knowledge, person, project;
- short non-memory chatter;
- explicit dates and no-date abstention;
- low/high importance cases;
- single/multiple entities;
- multiple topic labels;
- Japanese + English mixed input;
- supplied-context link disambiguation.

This committed benchmark is **open development data**, never formal blind evidence.

## Metrics

Overall and per-slice metrics include:

- schema valid rate;
- strict semantic record accuracy;
- memory-worthy accuracy/F1;
- Memory Type accuracy on gold-worthy captures;
- topic precision/recall/F1;
- entity precision/recall/F1;
- entity hallucination rate (predicted entity absent from adjudicated gold);
- explicit event-date exact rate;
- no-date/null accuracy;
- importance MAE and within-one rate;
- link precision/recall/F1;
- confidence Brier score for the memory-worthy/type decision.

Invalid/missing JSON is scored as a record failure rather than being silently excluded.

Title wording is deliberately **not** an exact-match quality metric in v1 because many concise faithful titles can be correct. The schema still constrains title presence/length, and future human/adjudicated title-faithfulness checks may be added separately.

## Formal-blind direction

The dataset contract already supports `judgement_visibility=held_out`. Held-out reports redact per-slice metrics and invalid sample IDs.

Before organizer model acceptance:

1. expand the open corpus with harder ambiguity, relative-date, negation and entity-boundary cases;
2. create a genuinely private held-out corpus outside the repo/tuning workspace;
3. use independent annotation/adjudication for type/topics/entities/date/importance/link targets;
4. freeze prompt/schema/model revision/quantization/runtime configuration before blind execution;
5. predeclare Windows CPU/RAM/latency and quality gates;
6. run one sealed blind cycle;
7. independently review evidence before production integration.

The retrieval PA1 blind machinery is conceptually reusable, but organizer evidence must not be forced through retrieval-specific ranking metrics.

## Draft screening priorities

These are priorities, not yet frozen formal thresholds:

1. **Zero data-loss / non-destructive behavior** — hard invariant.
2. **Schema reliability** — invalid JSON must be extremely rare.
3. **Low hallucination** — especially people/projects/places and links.
4. **Memory-worthy + type correctness** — wrong durable classification causes long-lived organization errors.
5. **Entity/date precision** — false metadata can create misleading links/timelines.
6. **Topic consistency** — stable labels matter more than creative vocabulary.
7. **Importance calibration** — useful but lower-risk than invented entities/dates.
8. **Windows local resource fit** — offline CPU/RAM/latency/installation footprint.

A candidate with better aggregate F1 must still be rejected if it materially increases hallucinated entities, fabricated links, destructive output, or invalid-schema rate.

## CLI

Export open model-side inputs without gold/slices:

```powershell
python scripts/evaluate_organizer.py export-open --output .\tmp\organizer_open_inputs.jsonl
```

Score a candidate's JSONL outputs:

```powershell
python scripts/evaluate_organizer.py score-open `
  --predictions .\tmp\organizer_predictions.jsonl `
  --json-report .\tmp\organizer_report.json `
  --markdown-report .\tmp\organizer_report.md
```

Prediction JSONL format:

```json
{"sample_id":"org-decision-01","output":{"memory_worthy":true,"memory_type":"decision","title":"端末内保存を優先","topics":["work","technology"],"entities":[{"name":"オリオン1","confidence":0.99}],"event_date":"2026-05-11","importance":4,"confidence":0.98,"link_candidates":[]}}
```

## Production boundary

`brain_twin_eval.organizer*` is evaluation-only. Production `brain_twin/` must not depend on it. The eventual production organizer should implement a separately reviewed adapter that maps accepted structured output into the existing `ClassificationResult`/Memory pipeline while preserving Raw Log source-of-truth behavior.
