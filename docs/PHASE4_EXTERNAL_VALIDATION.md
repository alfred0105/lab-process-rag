# Phase 4 — External Scientific Validation

**Status:** `EXTERNAL_VALIDATION_PENDING`
**Phase 4 core:** `PHASE_4_CORE_COMPLETE`
**Current blocker:** approved, provenance-complete real experiments suitable for GP/BO comparison have not been provided in this repository.

This document tracks empirical validation separately from software completion. No synthetic benchmark result is an experimental accuracy or success-rate claim. Completing a row below is optional for Phase 5 entry, but required before claiming scientific effectiveness for the affected process or objective.

| ID | Validation requirement | Status | Evidence needed to close |
|---|---|---|---|
| P4-EXT-001 | GP response prediction for actual ZnO process data | `PENDING` | Approved non-demo observations, fixed input/outcome definitions and experiment-group holdout; compare RMSE/MAE/R² to simple baselines |
| P4-EXT-002 | Real nanorod length / diameter prediction | `PENDING` | Accepted calibrated XRD/SEM/TEM or researcher-approved outcome measurements with units, specimen links and measurement uncertainty |
| P4-EXT-003 | Predictive uncertainty calibration | `PENDING` | Sufficient independent held-out experiments; coverage/reliability by outcome and replicate structure |
| P4-EXT-004 | Researcher assessment of candidate conditions | `PENDING` | Blind review protocol, feasibility and source review, reasons for accept/reject, no success-probability interpretation |
| P4-EXT-005 | Follow-up experiment at a recommended condition | `PENDING` | Researcher approval, safe feasible condition, recorded actual outcome and comparison with the registered predictive distribution |
| P4-EXT-006 | Efficiency relative to existing researcher design | `PENDING` | Predeclared objective and budget; compare target attainment, regret, experiments used and researcher workload fairly |
| P4-EXT-007 | Physical process constraints and safety review | `PENDING` | Method-specific bounds and safety review by responsible researcher; optimizer feasibility alone is not chemistry/safety approval |
| P4-EXT-008 | Generalization to new process conditions/method variants | `PENDING` | Topic/method/version-separated external holdout and documented applicability limits |

## Data admission checklist

Use only accepted records with original source identifiers, experiment and method version, process-step mapping, material/specimen identity, unit normalization, replicate identity, review status and measurement uncertainty when known. Preserve raw source values. Define objectives, maximize/minimize direction and process boundaries before running the comparison. Avoid selecting test conditions after viewing their outcomes.

Until evidence is available, retain `INSUFFICIENT_APPROVED_DATA` behavior. Never backfill this validation set with generated demo measurements or papers and describe the result as lab validation.
