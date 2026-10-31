# Phase 5 Stage 3 — Scientific State V2 and Robust Generalization

**Status:** `PHASE_5_STAGE_3_IMPLEMENTED` (software acceptance; real laboratory decision validity remains unverified)
**Scope:** P5-S3-001–012 from the Stage 3 implementation directive.
**Implementation commit:** `43a7f7d53285e85f760a295672c12fc35c5e455e`
**CI:** [GitHub Actions run 41196292332](https://github.com/alfred0105/lab-process-rag/actions/runs/41196292332) — all jobs passed.
**Evidence:** `backend/reports/phase5_stage3_generalization.json`, `backend/tests/test_phase5_stage3.py`, and full project test/build/CI results below.

## What changed

Stage 2's 18-input V1 model and stored artifacts remain available with their original schema. Stage 3 adds a separate `scientific-state-v2` object and `scientific-decision-features-v2` vector. The V2 schema contains **153 uniquely named features across nine context groups**: experiment, process conditions, measurements, analysis, simulation, optimization, tool readiness, pending reviews, and provenance. Feature names include the group to avoid collisions. Unknown values are represented by zero plus an explicit `__missing_mask`; actual zero remains distinguishable. Categoricals are one-hot encoded. Experiment/topic identifiers and scenario IDs remain trace metadata and are not model inputs.

Dimensioned process conditions are normalized through Pint to °C, kPa, minutes, mL, and mol/L. The extraction metadata retains original value/unit, normalized value/unit, and conversion status. Unsupported units are left explicitly unresolved rather than guessed. Learned mean/scale normalization is fitted from fit rows only when training a V2 model.

`StructuredDecisionHeadV2` is a CPU NumPy model with nine trainable context branches (five tanh units each) feeding six action logits. It is intentionally small and independently serialized/version checked. Its embedding interface is a software boundary for later adapters; it does not promise compatibility with a future Transformer embedding. There is no Transformer, Early Exit, conditional LM, tool execution, or automatic promotion in Stage 3.

## Data, evaluation, and safety

The reproducible software benchmark is generated from 12 explicitly labeled synthetic scenario families. It is not lab evidence or expert judgment. Each of five fixed seeds (`11, 29, 47, 71, 101`) uses 576 distinct scenario groups and group-disjoint 60/20/20 fit/calibration/test partitions. A separate condition-shift run withholds the `unseen_condition_combination` family from both fit and calibration. Topic- and method-generalization are marked insufficient because this benchmark has no independent multi-topic or multi-method reviewed corpus. Research datasets still require verified source experiments, compatible immutable snapshots, human-reviewed labels, and matching feature schema.

The benchmark compares the existing V1 MLP, V2, training-only majority baseline, and the actual `RuleBasedDecisionPolicy` through the existing `rule_metrics` implementation on identical ordinary test rows. Metrics include accuracy, balanced accuracy, macro F1, per-class precision/recall, confusion matrix, NLL, Brier, ECE, risk/coverage, calibration, parameter count, model size, fit time, inference latency, Python peak traced memory, OOD probes, and per-group ablation. The held-out condition-shift result is reported separately for V1 and V2. Thresholds are fitted on calibration groups only.

V2 inference remains shadow-only. It returns the raw class, final safe action, confidence semantics, OOD reasons, safety override, and immutable V2 snapshot. It never launches a tool, simulation, or experiment. Research inference refuses synthetic sandbox sources; the Stage 2 reviewed-feedback, source validation, snapshot, shadow activation and rollback routes remain schema-version guarded.

## API and UI

The existing Decision panel now exposes V2 state inspection, V2 dataset creation, V2 manual training, shadow prediction, and the fixed five-seed benchmark. It shows synthetic-vs-research limitations and status/diagnostic summaries in the same UI. The API is under `/api/decisions/learned/stage3`:

- `GET /schema`
- `POST /features`
- `POST /datasets/build`
- `POST /retrain`
- `POST /benchmark`
- `POST /models/{id}/predict`

The public benchmark endpoint always uses the five fixed seeds; no single-seed mode can be mistaken for the acceptance benchmark.

## Acceptance ledger

| ID | Status | Implementation / evidence | Remaining limit |
|---|---|---|---|
| P5-S3-001 | VERIFIED | Versioned V2 schema, stable feature order, unique names; schema/API regression | Schema changes require a new version |
| P5-S3-002 | VERIFIED | Typed extraction, missing masks, status context, Pint normalization; unit/missing tests | Features only reflect fields present in current records |
| P5-S3-003 | VERIFIED | Trainable grouped encoder, deterministic training, serialization/reload test | NumPy CPU model; no empirical value claim |
| P5-S3-004 | VERIFIED | Versioned V2 dataset, frozen group split, experiment/method/topic/condition policies | Research cross-topic/method validation may return insufficient |
| P5-S3-005 | VERIFIED | Five-seed synthetic benchmark with V1/V2/majority/real rule policy and held-out condition family | Synthetic scenario labels only |
| P5-S3-006 | VERIFIED | Separate calibration partition, temperature scaling, calibration metrics and selective-risk reporting | Calibration is only synthetic in this benchmark |
| P5-S3-007 | VERIFIED | standardized distance, high-missingness and contradiction gates; OOD probes | Probe does not establish deployment OOD accuracy |
| P5-S3-008 | VERIFIED | Group ablation, unit invariance and missingness distinction tests | Sensitivity is not causal attribution |
| P5-S3-009 | VERIFIED | Separate V1/V2 schema checks and version-aware model loader; V1 regressions retained | Historical V1 state cannot recover fields never recorded |
| P5-S3-010 | VERIFIED | Stage 2 source/snapshot/feedback gates retained; V2 API prediction regression confirms shadow-only | Reviewer identity remains self-attributed as documented in Stage 2 |
| P5-S3-011 | VERIFIED | Existing Decision UI includes V2 inspect/build/train/predict/benchmark flow; production build | Browser-level visual acceptance is limited to project E2E coverage |
| P5-S3-012 | VERIFIED | Reproducible benchmark report; 213 backend tests, production build, 5 browser E2E, migration regression, and GitHub Actions run 41196292332 all passed | Actual reviewed research validation remains pending |

## Five-seed synthetic benchmark

The full generated report is stored at [`backend/reports/phase5_stage3_generalization.json`](../backend/reports/phase5_stage3_generalization.json). At the run recorded in that report, mean held-out accuracy was **0.569 ± 0.041 for V1** and **0.591 ± 0.105 for V2**. This small synthetic difference is not evidence that V2 is superior; V2 has higher seed variation and per-seed results include regressions. The model is not automatically promoted. The generated benchmark completed in approximately 5.75 seconds with approximately 14.0 MiB Python-traced peak memory in this environment; this is not total process or device memory.

The frozen condition-shift family has 48 cases per seed at the 576-sample benchmark size. V1 and V2 metrics are emitted separately in each seed record, with no group overlap between fit/calibration/shift test. Its mean accuracy was **0.546 ± 0.086 for V1** and **0.225 ± 0.097 for V2**. This is a clear synthetic regression for V2 on this held-out family and must not be hidden by the in-distribution mean. It also does not establish broad real-world shift performance, because the held-out family and labels are synthetic.

## Verification record

- Backend: `backend/.venv/bin/pytest` — **213 passed**, 332 warnings, 42.50 seconds. Warnings are existing Starlette/httpx, SQLAlchemy `utcnow`, and PyMuPDF/SWIG deprecations; no test was skipped.
- Stage 3 targeted regressions: **6 passed**. Includes schema uniqueness, explicit zero-vs-missing, unit invariance, model save/load and safety, group split and five-seed benchmark, plus API state extraction and sandbox dataset→train→shadow-predict integration.
- Frontend: `npm run build` — passed (Vite 6.4.5; 1,760 modules).
- Browser E2E: `npm run test:e2e` — **5 passed** (original full run 44.1 seconds; after adding the Stage 3 browser flow, the changed Decision scenario also passed in 4.6 seconds; final full-suite rerun is in progress).
- Alembic migration compatibility: migration regression in the full backend suite passed.
- Phase 3/4 and Stage 1/2 regression: covered by the same full backend suite and passed.
- Five-seed benchmark: `backend/.venv/bin/python backend/scripts/benchmark_phase5_stage3.py` — passed; report saved in `backend/reports/phase5_stage3_generalization.json`.
- GitHub Actions: [run 41196292332](https://github.com/alfred0105/lab-process-rag/actions/runs/41196292332) — backend, frontend build, and browser E2E jobs all passed for implementation commit `43a7f7d53285e85f760a295672c12fc35c5e455e`.

## Limitations / next phase boundary

- No real reviewed lab-decision corpus has been evaluated; scientific decision accuracy remains unverified.
- Synthetic labels encode a declared conservative scenario contract, not expert truth.
- Calibration and OOD metrics are software diagnostics for constructed test data only.
- Historical V1 snapshots are adapted loss-aware; absent historical fields remain unknown and are not backfilled from current state.
- V2 remains shadow-only; researchers retain all approval and execution control.
- Phase 6 shared Transformer, Early Exit and conditional LM are out of scope.
