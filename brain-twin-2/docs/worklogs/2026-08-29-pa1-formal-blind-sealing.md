# 2026-08-29 — PA1 formal blind protocol sealing

- Agent: ChatGPT
- Branch: `brain-twin-dev`
- Base: `f9d24407cf5ac1ae09f9021dda466b65011323e9`
- Implementation commit: `6d08616d58d187d65df104bcb82a8705d2fe74aa`
- Scope: complete Launch Envelope, Critical Slice Gate, and shared Formal Config Builder; formal-blind hardening only; no production provider/backend, model download, PA2/PA3, or production activation.

## Changed

- retrieval behavior configuration can be frozen before blind corpus/query text is introduced;
- acceptance policy and launch envelope separately freeze measurement protocol and runtime gates;
- launch envelope binds runner/dataset/policy/config/evaluator/evaluation-k/warm-repeat commitments and optional model-artifact-manifest SHA;
- formal runner resolves the actual Git HEAD itself and requires a clean tracked worktree before model load;
- private critical-slice scoring exposes only rule-spec SHA, rule count, and aggregate PASS/FAIL in redacted formal output;
- formal acceptance requires the same launch envelope and verifies the complete policy/config/runtime attestation chain.

## Important correction

Runtime measurement/data-shape fields (`evaluation_k`, `warm_repeats`, `corpus_memory_count`, and label-only candidate IDs) are not retrieval-behavior identity. They are frozen independently in policy/envelope. Behavior-changing model/template/reranker/base-model/candidate-k fields remain in the retrieval-config SHA.

This separation is intentional: the retrieval profile can be frozen before blind query text is introduced without weakening the runtime protocol commitment.

## Verification

- exact-SHA commit: `6d08616d58d187d65df104bcb82a8705d2fe74aa`
- GitHub Actions run: `33227872937`
- job: `99034999663`
- result: **447 passed**
- production `brain_twin/`: unchanged by this implementation

## Status

Formal-blind tooling is sealed and CI-green. **No formal held-out run has occurred.** Production Vector Search remains **PENDING**.

## Next

1. Run the prepared open-development Qwen matrix on the target Windows machine.
2. Review Qwen plus challenger evidence and freeze one retrieval profile.
3. Freeze measured Windows CPU/RAM/latency budgets and warm-repeat protocol.
4. Create and independently two-judge/adjudicate a genuine private held-out corpus.
5. Only then create one launch envelope and run the sealed formal blind cycle.
