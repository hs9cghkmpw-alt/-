# Organizer LLM Evaluation

Status: **evaluation foundation GO; production integration not authorized**

## Purpose

The organizer is the structured-interpretation component in the Brain Twin target architecture. It is separate from embedding/reranking and must remain replaceable.

Its job is to derive metadata from a raw capture while the raw capture itself remains authoritative and unchanged. This benchmark does **not** authorize replacing the current production classifier.

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

If the organizer fails, returns invalid JSON, times out, or is unavailable, the original Raw Log must already be safely stored. Failure means **organization pending/retryable**, not capture loss.

## Output schema and prompt

Machine-readable schema: `evaluation_profiles/organizer_output_schema_v1.json`

Current open-development instruction: `evaluation_profiles/organizer_system_prompt_v2.txt`

The Python evaluator uses a small dependency-free strict validator rather than adding an evaluation-only JSON-schema dependency to production requirements.

Raw captures are not classified as `ai_inference`; that type is reserved for derived AI material, not source captures.

### Temporal semantics

The v2 prompt freezes these rules for open development:

- `created_at` may resolve explicit relative expressions such as today/yesterday/tomorrow;
- experience → occurrence date;
- goal with explicit deadline → deadline, not discussion date;
- dated fact/decision → date tied to that durable fact/decision;
- vague or equally ambiguous dates → `null`, never fabricated precision.

These semantics must be reviewed again before a formal blind corpus is frozen.

## Open benchmark

### v1

Generator: `brain_twin_eval.organizer_gold.build_organizer_open_v1()`

- 128 deterministic synthetic samples;
- all raw-capture Memory types;
- non-memory chatter;
- explicit/no-date cases;
- importance range;
- single/multiple entities;
- multi-topic input;
- JP+EN input;
- context link disambiguation.

### v2 — current default

Generator: `brain_twin_eval.organizer_gold_v2.build_organizer_open_v2()`

v2 contains all v1 samples plus 64 hard cases, for **192 total synthetic samples**. Added slices include:

- relative dates resolved from `created_at`;
- negated/cancelled intentions;
- uncertain/vague future language that must not fabricate exact dates;
- quoted third-party preference vs the user's own preference;
- multiple dates where the durable goal deadline must be selected;
- thought-vs-decision ambiguity with explicit `まだ決めていない`;
- link hard negatives where entity/topic overlap is explicitly a different matter.

Committed v1/v2 data are **open development data**, never formal blind evidence.

## Metrics

Overall and per-slice metrics include:

- schema valid rate;
- strict semantic record accuracy;
- memory-worthy accuracy/F1;
- Memory Type accuracy on gold-worthy captures;
- topic precision/recall/F1;
- entity precision/recall/F1;
- entity false-positive/hallucination rate against adjudicated gold;
- explicit event-date exact rate;
- no-date/null accuracy;
- importance MAE and within-one rate;
- link precision/recall/F1;
- confidence Brier score for the memory-worthy/type decision.

Invalid/missing JSON is a record failure rather than being silently excluded.

Title wording is deliberately not an exact-match quality metric because multiple concise faithful titles can be correct. Schema still constrains title presence/length; formal acceptance should add adjudicated title-faithfulness sampling if needed.

## Candidate catalog

Catalog: `evaluation_profiles/organizer_candidate_catalog_v1.json`

Fail-closed rules are implemented by `brain_twin_eval.organizer_candidates`.

Current research set:

- Qwen3.5-0.8B — efficiency floor;
- Qwen3.5-2B — balanced-size candidate;
- Qwen3.5-4B — higher-capacity quality target;
- Qwen3-4B-Instruct-2507 — text-only Qwen control;
- Phi-4-mini-instruct — remote-code smoke required before execution;
- Gemma-3-4B-it — gated/research-only until license/access and immutable revision are explicitly reviewed.

This list is an evaluation set, **not a ranking or production decision**.

## Formal run identity

`OrganizerRunConfig` hashes all behavior/artifact inputs that can change output:

- exact model revision;
- organizer prompt SHA-256;
- JSON schema SHA-256;
- chat-template/tokenizer SHA-256;
- runtime backend and runtime revision;
- quantization;
- temperature/top-p/max output tokens/seed;
- extra runtime parameters such as thread count when relevant.

Changing any of these changes the organizer config SHA. Formal blind acceptance must freeze this identity before the private corpus is executed.

`brain_twin_eval.organizer_runtime` is model-framework-independent and records first-call/warm latency, process peak RSS, exact config/dataset identity, predictions, and repeated-run determinism. It intentionally does not import Transformers or llama.cpp.

## Formal-blind direction

Before organizer model acceptance:

1. use v2 open data to eliminate obviously weak/unstable candidates;
2. decide the practical Windows runtime/quantization track from real CPU/RAM measurements;
3. create a genuinely private held-out corpus outside the repo/tuning workspace;
4. use independent annotation/adjudication for type/topics/entities/date/importance/link targets;
5. freeze prompt/schema/model/chat-template/runtime/quantization/generation configuration;
6. predeclare Windows CPU/RAM/latency and quality gates;
7. run one sealed blind cycle;
8. independently review evidence before production integration.

Retrieval PA1 blind machinery is conceptually reusable, but organizer evidence must not be forced through retrieval-specific ranking metrics.

## Draft screening priorities

These are priorities, not frozen formal thresholds:

1. **Zero data-loss / non-destructive behavior** — hard invariant.
2. **Schema reliability** — invalid JSON must be extremely rare.
3. **Low hallucination** — especially people/projects/places/dates/links.
4. **Memory-worthy + type correctness**.
5. **Entity/date precision**.
6. **Topic consistency**.
7. **Importance calibration**.
8. **Repeated-run determinism**.
9. **Windows local CPU/RAM/latency/installation footprint**.

A candidate with better aggregate F1 is still rejected if it materially increases fabricated metadata, destructive output, invalid-schema rate, or operational cost beyond the frozen budget.

## CLI

v2 is the current default:

```powershell
python scripts/evaluate_organizer.py export-open --output .\tmp\organizer_open_inputs.jsonl
```

Explicit v1 compatibility:

```powershell
python scripts/evaluate_organizer.py --dataset v1 export-open --output .\tmp\organizer_v1_inputs.jsonl
```

Score outputs:

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

`brain_twin_eval.organizer*` is evaluation-only. Production `brain_twin/` must not depend on it. The eventual production organizer requires a separately reviewed adapter mapping accepted structured output into the existing Memory pipeline while preserving Raw Log source-of-truth and safe fallback behavior.
