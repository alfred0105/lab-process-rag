# Phase 6 Readiness Contract (Phase 5 Stage 4 output)

**Phase 6 status: `NOT_STARTED`.** This document specifies an integration boundary only. No Transformer, Early Exit, conditional language head, model-weight download, or autonomous tool execution is implemented here.

## Input: `ScientificRepresentation`

Required fields:

- `representation_version`: explicit version for the producer and adapter.
- `feature_schema_version`: source state/feature contract; never infer from vector width.
- `model_architecture_version`: backbone or encoder identity.
- `embedding_dimension`: positive integer and verified against payload shape.
- `values`: finite numeric vector or batch; reject NaN/Inf, unexpected rank and dimension.
- `source_provenance`: immutable snapshot/dataset/case references and synthetic-vs-research classification.
- `input_validity`: `VALID`, `PARTIAL`, `INVALID`, or `UNKNOWN`; unsupported and invalid states fail closed.
- `missingness_metadata`: explicit missing-data information; a numeric zero is not a missing marker.
- `shadow_mode`: must be true for unreviewed candidates.

The existing V2 representation is a 45-dimensional context embedding derived from the 153-feature `scientific-decision-features-v2` contract. A future Transformer hidden state is a different representation and cannot reuse V2 weights without a versioned adapter and new fit/calibration evaluation.

## Output: `DecisionResult`

Required fields:

- `action_mapping_version` and fixed action set: `REQUEST_INFORMATION`, `ANALYZE`, `SIMULATE`, `OPTIMIZE`, `REQUEST_REVIEW`, `ABSTAIN`.
- finite `action_logits` and normalized `action_probabilities` (or explicit unavailable calibration state).
- `raw_predicted_action` kept separate from the final safe output.
- `calibration_status`, calibration model/version and evaluated population.
- `ood_status`, detector/version, threshold provenance and evidence sufficient to explain the result.
- `final_safe_action`, `abstention_reason`, `safety_override` and structured override reasons.
- `model_version`, input/representation versions, source snapshot and `shadow_mode`.
- explicit `workflow_triggered: false` for this interface.

## Gates before any later implementation

1. Reject schema, architecture, action-mapping and embedding-dimension mismatches.
2. Reject unsupported representation and malformed/non-finite values.
3. Keep scientific validity, distribution shift and classifier uncertainty as separate signals.
4. Calibration and OOD thresholds must identify their calibration source and version.
5. Batch and single-input paths must be deterministic for fixed model/version/input.
6. Model loading must be version-aware; no implicit migration of V1/V2 weights.
7. Preserve Shadow-only behavior, researcher review, RuleBasedDecisionPolicy and ValidationGate precedence.
8. Any future promotion requires a separately approved, reviewed, group-independent research evaluation; synthetic Stage 4 metrics cannot satisfy it.

## Contract validation status

Stage 4 specifies these fields and validates the existing V2 representation/inference safety behavior. It does **not** provide a complete executable Transformer adapter or prove compatibility with future hidden states. Phase 6 remains `NOT_STARTED` until its own implementation plan, data contract, adapter tests and resource benchmark are approved.
