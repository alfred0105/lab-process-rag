# Phase 5 — Learned JEV Decision Head Handoff

**Phase status:** `IN_PROGRESS`
**Stage 1 status:** `PHASE_5_STAGE_1_MVP_IMPLEMENTED`
**Stage 2 status:** `IN_PROGRESS` pending full-suite/browser/CI closure; detailed ledger: [`PHASE5_STAGE2.md`](PHASE5_STAGE2.md)
**Operating mode:** shadow recommendation only

## Purpose and role boundaries

Phase 5 learns which action family to recommend from a snapshot of the current scientific state. It does not analyze instrument files, run simulations, approve measurements, or execute a workflow. The action families are `REQUEST_INFORMATION`, `ANALYZE`, `SIMULATE`, `OPTIMIZE`, `REQUEST_REVIEW`, and `ABSTAIN`.

The existing `RuleBasedDecisionPolicy` remains available as an engineering baseline. `ToolRegistry` determines what tools appear available. A learned action does not override the registry, the existing validation gates, researcher approval, or any workflow execution boundary. Every prediction is explicitly returned as `SHADOW_ONLY` with `workflow_triggered: false`.

## State and feature contract

`state_from_experiment` assembles accepted and pending scientific observations, analysis/simulation/optimization readiness, tool availability and required-information checks. `FeatureExtractor` converts this state into a deterministic 18-value vector under `scientific-decision-features-v1`. The model stores the exact feature names and schema version. Missing values are zero-filled and counted; non-finite values and invalid normalized ranges are rejected.

The final experiment outcome is deliberately not encoded: `workflow_state` is held at neutral zero, so a later success/failure label cannot be read from that field. Stage 2 stores exact model recommendation state/features/source IDs and timestamps in immutable `DecisionSnapshot` rows. Legacy Stage 1 cases created before snapshots existed cannot be reconstructed as verified historical states and are excluded from the Stage 2 versioned dataset builder when a required snapshot is absent.

Feature inputs include observation count/completeness, available and pending analysis, analysis and simulation tool availability, GP readiness/uncertainty, optimization readiness/tool availability, pending review, available tools, missing required information, provenance validity, validation status, neutral workflow state, and missing-feature count.

## Dataset, labeling and isolation

Decision cases record topic, optional non-demo experiment, group, state and extracted features, feature schema, candidate action set, selected action, label source, reviewer attribution, review status, provenance, dataset version and time. Sources are restricted to `HUMAN_REVIEWED_DECISION` and `EXPERT_ANNOTATION` in research labeling. Research training filters out every synthetic case and requires at least 20 independent groups, at least two action classes, and two groups per included class; otherwise it returns `INSUFFICIENT_REVIEWED_DECISIONS`.

Synthetic fixtures use `SYNTHETIC_SANDBOX` / `SYNTHETIC_ONLY` and cannot enter research-mode training. Group splits keep each experiment/scenario together. The existing local app has no authenticated reviewer identity, so the reviewer string is self-attributed, not cryptographically verified; production multi-user use needs identity and role controls before treating it as an authenticated approval.

## Model, training and evaluation

The MVP is a small NumPy tanh MLP with 18 input features, 12 hidden units and six action outputs. Training uses supervised multiclass cross-entropy and deterministic fixed-seed gradient descent, records loss, and serializes weights, normalizers, class/action mapping, model version and feature schema to the model-run record. Inference returns a probability distribution over action families. Those values are action scores, not success probabilities.

Training splits scenario/experiment groups into fit, calibration and validation partitions. Temperature scaling is only applied when there are enough independent calibration examples and classes; otherwise the model remains explicitly uncalibrated. Metrics include accuracy, macro F1, confusion matrix, negative log likelihood, Brier score, 10-bin ECE and risk–coverage. A majority predictor and the current rule policy are reported on the same validation cases.

OOD is a separate lightweight guard: missing required feature count and standardized distance from training feature ranges produce `IN_DISTRIBUTION`, `POTENTIAL_OOD` or `UNSUPPORTED_STATE`. OOD or unsupported input abstains. Missing required information and pending reviews route to their corresponding request actions; low score abstains. This range check is an MVP safety signal, not a validated detector.

## API and UI

The router under `/api/decisions/learned` provides training readiness, human/expert case capture, sandbox seeding, training, model retrieval, prediction and rule-vs-learned comparison. Representative endpoints are:

- `GET /api/decisions/learned/training-readiness?topic_id=…`
- `POST /api/decisions/learned/cases`
- `POST /api/decisions/learned/sandbox/seed?topic_id=…`
- `POST /api/decisions/learned/train`
- `GET /api/decisions/learned/models/{model_id}?topic_id=…`
- `POST /api/decisions/learned/models/{model_id}/predict`
- `POST /api/decisions/learned/compare`

The Decision panel is part of the existing app navigation. It shows the current state summary, dataset readiness, sandbox/research distinction, model metrics, action scores, OOD/abstention, baseline agreement and the shadow-only safety boundary. Detailed UX polish remains in Phase 8.

## Phase 6 extension boundary

The feature-vector interface is deliberately explicit and versioned. Phase 6 may add an adapter from a shared Transformer representation to a Decision Head, but its embedding space, dimensions, training distribution and calibration will differ. Reuse of these numeric-feature weights is not guaranteed; adapter design and likely retraining must be evaluated then. No Transformer backbone, model-weight download, early exit or conditional LM generation is part of Stage 1.

## Limitations and next work

- No accepted human-reviewed research decision dataset was available in this repository, so research training remains unavailable and scientific decision accuracy is unverified.
- Synthetic benchmark scores establish the training/evaluation code path only; their labels are designed fixtures, not expert truth.
- Reviewer attribution is unauthenticated in the current local application.
- Historical decisions that predate Stage 2 snapshots cannot be backfilled as verified decision-time state; only new captures have the immutable snapshot guarantee.
- The OOD range heuristic and confidence threshold need evaluation on independent reviewed decisions.
- The Decision Head does not execute a selected tool or workflow.

## Stage 2 handoff — decision feedback and versioned learning

Stage 2 adds decision-time snapshots, append-only ACCEPT/CORRECT/REJECT/UNSURE feedback, immutable Research/Sandbox dataset versions, frozen group evaluation, explicit manual retraining, same-holdout Champion–Challenger comparison, and audited Shadow activation/rollback. The original stage 1 training API remains available for compatibility; the new lifecycle is `/datasets/build` → `/retrain` → `/models/compare` → explicit `/activate` or `/rollback`.

The stage-2 MLP remains a shadow recommender and cannot trigger tools or workflows. Researcher names remain unauthenticated self-reported labels, and synthetic cases remain explicitly sandbox-only. Until a reviewed, independent research dataset has been evaluated, no real-world or laboratory decision-accuracy claim is supported. Acceptance details and validation evidence are in [`PHASE5_STAGE2.md`](PHASE5_STAGE2.md); optional follow-up work is in [`PHASE5_TECHNICAL_BACKLOG.md`](PHASE5_TECHNICAL_BACKLOG.md).

See [`PHASE5_STAGE1.md`](PHASE5_STAGE1.md) for the acceptance ledger and measured synthetic benchmark.
