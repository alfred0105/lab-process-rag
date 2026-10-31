# Phase 5 Stage 4 — Decision Reliability, OOD Robustness & Generalization

**Status:** implementation and local verification complete; final v3 CI verification pending.
**Scope:** P5-S4-001–012, software-only decision reliability evaluation.
**Data limitation:** every Stage 4 label, shift and final holdout is synthetic. Results do not measure scientific correctness or real laboratory performance.

## Executive result

Stage 4 adds repeatable five-seed comparisons, feature diagnostics and ablations, class imbalance experiments, V2-Fusion comparison, five OOD scores, calibration and risk-coverage reporting, and a fresh final synthetic split. It does not promote or activate a candidate.

The five-seed development comparison retained the previously reported V1/V2 behavior: V1 mean accuracy **0.569** and macro-F1 **0.366**; V2 mean accuracy **0.591** and macro-F1 **0.326**. V2's seed-to-seed macro-F1 standard deviation was **0.137**, so the small accuracy advantage does not make V2 a stable winner. Class-weighted V2 achieved mean macro-F1 **0.510** and balanced accuracy **0.607**, while mean accuracy was **0.579**. Group-aware balanced sampling achieved macro-F1 **0.486** and accuracy **0.584**. These are synthetic-label tradeoffs, not evidence that either training strategy improves experimental decisions.

HistGradientBoosting scored development mean accuracy **0.864** and macro-F1 **0.839** and was selected under the predeclared development-only rule: maximize mean macro-F1 among candidates whose mean accuracy is within 0.05 of the best. On the frozen fresh synthetic v3 holdout it scored accuracy **0.861**, macro-F1 **0.722**; V1 scored accuracy **0.748**, V2 **0.722**, class-weighted V2 **0.626**, balanced-sampled V2 **0.661**, core-subset V2 **0.609**, and Fusion **0.548**. This holdout uses a separate synthetic recipe, but its labels still derive from a programmed rule. These figures verify software behavior against that rule only; they are not research evidence and do not justify model activation.

## Protocol and data isolation

- Development uses seeds `11, 29, 47, 71, 101`, 576 independent groups per seed and group-disjoint fit/calibration/evaluation splits.
- Fresh final data uses protocol `phase5-stage4-fresh-synthetic-protocol-v3`, generation seed `90422`, a different state-generation recipe, 576 unique groups, then a fixed grouped fit/calibration/evaluation split. Protocol v1/v2 runs were preliminary and are not the final evidence: the v1 label construction was too directly coupled to its scenario branch, and v2 was replaced to freeze the complete candidate set before final scoring. V3 is the final frozen score; later CI reruns check deterministic reproducibility only and are not used to tune models or thresholds.
- Final dataset SHA-256: `9cf6023aa69cfa69f96648bd399b248d8e06ebcfc735c8804980da35ad5fe2aa`.
- Final evaluation SHA-256 is recorded in `phase5_stage4_final_evaluation.json` and the baseline contract.
- Hash input rounds encoded features to eight decimal places before canonical JSON hashing, preventing insignificant floating-point serialization differences across local and CI dependency/platform builds. Labels and group IDs remain exact.
- No generated label is sourced from a paper or lab record. All candidates remain shadow-only; none triggers a workflow.

## Findings by acceptance item

| ID | Finding / outcome | Implementation and evidence | Status |
|---|---|---|---|
| P5-S4-001 | Per-class precision/recall, FP/FN, confusion matrix, NLL, Brier, ECE, high-confidence errors and raw-vs-safe action counts are emitted. | `backend/app/services/phase5_stage4.py`; diagnostics and comparison JSON | VERIFIED |
| P5-S4-002 | Per-feature missingness/constant/unique/mean/std/train-evaluation shift/correlation and nine predeclared group ablations are measured. Full, core, core+missing-mask and V1 18-feature subsets are compared. | Feature ablations are fitted on development fit rows, calibrated on calibration rows; final set is not used for selection. | VERIFIED |
| P5-S4-003 | Rule, V1, V2 and HistGradientBoosting are evaluated on the same grouped partitions; fit time, per-case latency, model size and parameters where applicable are recorded. | HistGradientBoosting is a diagnostic candidate only. | VERIFIED |
| P5-S4-004 | Inverse-frequency weighted V2 and group-aware balanced sampling increase synthetic macro-F1 over plain V2, with accuracy tradeoffs. | Weights and sampling are derived only from fit labels. No duplicate experiment-group identity is split across partitions. | VERIFIED |
| P5-S4-005 | A 32-unit Fusion layer was evaluated on identical splits; its mean macro-F1 (**0.116**) was below plain V2 (**0.326**). | Not selected as a default. | VERIFIED |
| P5-S4-006 | The old RMS distance's `max(6, 1.25 × train q99)` floor is contrasted with calibration-derived detector thresholds; full ID and OOD score quantiles are included. Synthetic constructed shifts, rather than source-code inspection alone, determine results. | Diagnostics report the existing threshold, held-out ID FPR and constructed-shift detection for each seed. | VERIFIED |
| P5-S4-007 | Standardized RMS, maximum deviation, numeric KNN, shrinkage Mahalanobis on the V2 embedding, and embedding KNN are compared. Eight synthetic shift patterns include extreme/mild, unseen combinations, missingness, categorical, contradictory, unsupported and provenance failures. | Thresholds derive from the separate ID calibration partition; per-shift rates, AUROC/AUPRC, fixed-ID-FPR TPR, FPR at 95% TPR and measured scoring latency are recorded. | VERIFIED |
| P5-S4-008 | Temperature scaling is measured against uncalibrated probabilities. A calibration-only threshold maximizes coverage subject to a Wilson 95% upper risk bound at target 0.20 and at least 24 calibration cases. Risk-coverage curves, reliability metrics and scenario-family slices are emitted. | Insufficient calibration evidence returns no threshold; no safety claim follows from the experimental target. | VERIFIED |
| P5-S4-009 | One fresh, recipe-versioned synthetic evaluation is group-independent from development and is never used for candidate or threshold selection. | Final counts, hashes, group overlap and candidate metrics are frozen in final JSON. | VERIFIED |
| P5-S4-010 | The development-only rule selects the compact-enough score winner among candidates within 0.05 of best mean accuracy. | The selected diagnostic baseline is HistGradientBoosting. It is not activated; V1/V2 production shadow behavior remains unchanged. | VERIFIED |
| P5-S4-011 | Phase 6 input/output, versioning, validity, calibration/OOD hooks and safe-action contract are specified without implementing a Transformer, Early Exit or conditional LM. | [`PHASE6_READINESS.md`](PHASE6_READINESS.md) | VERIFIED |
| P5-S4-012 | Existing source isolation, frozen evaluation, V1/V2, safe action and shadow constraints are protected by full backend, frontend, E2E, migration and CI regressions. | Local full suite passed; final protocol v3 CI run is pending. | IN_PROGRESS |

## OOD result and limits

The average across five seeds for the constructed mixture of shift probes was:

| Detector | ID false-positive rate | Shift detection rate | AUROC | Mean scoring latency per case |
|---|---:|---:|---:|---:|
| Standardized RMS | 0.061 | 0.154 | 0.622 | <0.001 ms |
| Maximum standardized deviation | 0.096 | 0.298 | 0.628 | <0.001 ms |
| Numeric KNN | 0.054 | 0.220 | 0.643 | 0.004 ms |
| Shrinkage Mahalanobis, V2 embedding | 0.075 | 0.729 | 0.889 | 0.003 ms |
| Embedding KNN | 0.071 | 0.559 | 0.817 | 0.002 ms |

Thresholds target 5% ID FPR on calibration data; measured evaluation FPR varies around that target on finite samples. The mixed probe distribution and synthetic feature representation materially determine these metrics. Detection is not the same as identifying a scientifically invalid state. The reported OOD abstention rate is explicitly **counterfactual** (the rate that would abstain if a detector flag were wired to ABSTAIN); the detectors are not connected to or modifying the safe-action policy. Scientific validity gates remain separate and authoritative.

## Model selection and Phase 6 boundary

The selection is a **benchmark reference**, not a production champion. Tree-based performance is not directly transferable to a Transformer-compatible decision head. No artifact is activated, no researcher review is bypassed, and no workflow execution is added. The report records the selection rule, schema, data/evaluation hashes, calibration and OOD policies, known failures and serialization boundary. The current model registry and V1/V2 activation policy remain unchanged.

## Files

- Service: `backend/app/services/phase5_stage4.py`
- Reproduction command: `backend/scripts/benchmark_phase5_stage4.py`
- Reports: `backend/reports/phase5_stage4_diagnostics.json`, `phase5_stage4_model_comparison.json`, `phase5_stage4_reliability.json`, `phase5_stage4_final_evaluation.json`
- Tests: `backend/tests/test_phase5_stage4.py`; Stage 3 integrity tests remain in `backend/tests/test_phase5_stage3.py`
- CI executes the benchmark after backend pytest.

## Remaining limits

1. No reviewed research/lab decision dataset exists in this validation path; real decision accuracy is unknown.
2. Synthetic labels represent a software contract, not expert truth.
3. Constructed OOD patterns do not cover deployment shift or arbitrary malformed input.
4. The risk target is an experiment setting and is not a safety guarantee.
5. The chosen tree baseline is not a Transformer Decision Head, and is not activated.
6. Phase 6 implementation remains `NOT_STARTED`.

## Local verification record — 2026-10-31

- Backend full suite: **223 passed** locally; no skips. The previous protocol-v2 CI run reported 223 backend tests passed (deprecation warnings only); protocol-v3 CI verification is pending.
- Focused Stage 3 and Stage 4 regressions: **15 passed** before the final hash regression was added; the final backend suite includes the added hash stability regression.
- Stage 3 API cycle: V1 → frozen evaluation group → V2 with three excluded new cases → JSON DB round-trip → V2 retrain/artifact → V3; frozen hash/version and group isolation preserved.
- Stage 4 benchmark: five seeds, 576 development examples per seed, 576 fresh final synthetic examples, final evaluation `115` examples. Protocol v3 is the frozen final report; the checked-in script also runs in CI for reproducibility.
- Final dataset SHA-256: `9cf6023aa69cfa69f96648bd399b248d8e06ebcfc735c8804980da35ad5fe2aa`. Feature vectors are rounded to 8 decimal places for cross-platform hash stability; the evaluation SHA-256 is stored in the final report and selected baseline contract.
- Frontend production build: passed locally and in CI (Vite 6.4.5; 1,760 modules). Browser E2E: **5 passed** locally and in CI. The multi-objective five-seed browser test receives a 240-second ceiling because a shared CI runner exceeded the former 90-second limit; its assertions remain enabled.
- Migration regression: **1 passed**; no schema migration was required.
- Previous protocol-v2 integration CI [run 41209545732](https://github.com/alfred0105/lab-process-rag/actions/runs/41209545732) passed backend, frontend, browser E2E and benchmark. The final protocol-v3 CI run is pending. The slow multi-objective E2E now has a 240-second ceiling; its assertions are unchanged.
- Implementation commits: `9ad141e` (Stage 3 JSON closure and Stage 4), `107d73c` (cross-platform hash stability), `6382c8d` (CI E2E timeout allowance); final v3 evaluation update pending commit.
