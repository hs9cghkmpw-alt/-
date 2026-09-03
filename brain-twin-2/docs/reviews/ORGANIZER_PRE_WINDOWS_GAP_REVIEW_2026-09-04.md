# Organizer Pre-Windows Gap Review — 2026-09-04

Verdict at review time: **GO for hardened Organizer Windows evidence execution; NEEDS REAL MACHINE EVIDENCE before any model-selection claim.**

Current routing note: this implementation-side Organizer verdict does not override the later PA1
evidence-integrity STOP. Full Windows matrix/selection execution is paused until the focused PA1 repair
has independent Critical=0/Major=0 re-review. The focused repair's exact-SHA CI is already green
(`f9cb9652afc3f4b1838074091fbad3e510821c76`, run `33798627068`, 571 passed). See `docs/CURRENT_STATE.md`.

Review type: implementation-side/self-review. This is not the independent final acceptance review.

## Reviewed scope

- Organizer pinned-model acquisition
- local-only runtime
- Windows bootstrap / smoke
- open-v2 evaluation
- formal-blind tooling
- resource/evidence identity
- candidate comparison process isolation
- evidence gaps that Linux CI cannot close

## Findings fixed before Windows execution

### 1. Local artifact integrity was under-bound — FIXED

Before this review, acquisition pinned the Hugging Face revision but the Windows run did not verify a full local content fingerprint. A corrupted or locally modified model file could therefore retain the same nominal model revision.

Hardening adds a full SHA-256 tree over non-cache model files, including relative paths and byte sizes. Volatile `.cache` metadata and the self-referential pin manifest are excluded. The acquisition manifest records the digest/file-count/bytes, and the evidence runner recomputes and verifies them before model load.

Rationale: immutable upstream revision is necessary but not sufficient evidence that the local bytes actually executed are intact.

### 2. Multi-model RSS contamination — FIXED for the Windows core comparison path

`run_organizer_open_matrix.py --tier core` can load multiple candidates in one Python process. Even if Python releases object references, Torch allocator/process peak-working-set history can contaminate later memory evidence.

A dedicated `run_organizer_core_windows.ps1` now launches 0.8B and 2B in separate Python processes and refuses mixed Git/dataset/sample protocol summaries.

Rationale: process PeakWorkingSetSize is lifetime-scoped; one shared process is not a trustworthy per-model RAM comparison.

### 3. Evidence directory ambiguity — FIXED

Organizer open runs now create a unique evidence directory containing dataset version + Git SHA prefix + UTC timestamp. A non-empty collision is refused.

Rationale: reruns must not silently overwrite or mix evidence.

### 4. Git/machine/load evidence incomplete — FIXED

The organizer open runner now requires a clean tracked Git worktree and records exact Git SHA. It also records non-identifying machine evidence and separates artifact verification/model-load evidence from generation evidence.

Rationale: a quality/latency number without exact code and machine context is not reproducible evidence.

## Remaining gaps intentionally not disguised as complete

### Open runtime timing still needs deeper Windows interpretation

The existing open runtime aggregate includes per-sample median/p95 but is not yet the final Formal Blind timing contract. Formal Blind already distinguishes first-call and warm latency. Windows open results should therefore be treated as development diagnostics, while final resource gates use the frozen formal protocol.

### Stress corpus status after this review

Open-v2 covers relative dates, negation, undecided states, attribution, multiple dates, link hard negatives and other structured cases, but still lacks sufficient:

- prompt injection as raw data;
- long/noisy capture;
- embedded JSON/code/URLs;
- mixed Japanese/English/emoji;
- typo/abbreviation;
- multi-intent and pronoun ambiguity.

These were subsequently added in open-v3 (48 additional cases across 12 stress slices). They remain
synthetic/open and still require real Windows execution; they are not Formal Blind evidence.

### Reference runtime is not production runtime

The first Windows Organizer run uses frozen Transformers CPU with no quantization. It is suitable as a quality/reference path, not proof that the same runtime is the correct always-on production implementation.

If quality is good but resource cost is poor, compare a separately frozen quantized runtime rather than conflating model quality with one runtime implementation.

### Repeated-run / thermal evidence remains missing

One clean execution is insufficient for latency/RAM stability. Provisional winner must be repeated in fresh processes and under longer sequential workload.

## Exact evidence still required

1. PA1 Retrieval full Windows open matrix.
2. Nomic/GTE isolated custom-code smoke if they remain candidates.
3. Organizer 0.8B first Windows smoke.
4. Organizer isolated 0.8B vs 2B full open-v2 comparison.
5. Stress/robustness open set.
6. Fresh-process repeatability and thermal/resource drift.
7. Optional 4B only when 2B evidence justifies the cost.
8. Freeze model/runtime/prompt/schema/resource/quality gates.
9. Genuine private held-out dataset + judging/adjudication.
10. One sealed Formal Blind.
11. Independent evidence review.

## Stop conditions

STOP rather than tuning around failure when:

- Git worktree is dirty;
- model revision or local artifact hash mismatches;
- unexpected network/custom-code execution appears;
- evidence mixes Git or dataset identities;
- deterministic output drifts without explanation;
- RAM pressure destabilizes Windows;
- evaluation touches production Vault;
- open evidence is presented as formal acceptance.

## Next execution document

Use `docs/WORK_WINDOWS_VALIDATION_MASTER_PLAN_2026-09-04.md` as the master execution/evidence contract.
