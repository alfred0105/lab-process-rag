# Phase 4 — GP/BO Core Completion

**Official status:** `PHASE_4_CORE_COMPLETE`
**Research validation:** `EXTERNAL_VALIDATION_PENDING`
**Verification baseline:** Stage 3 code commit `a3bc55ae9702548e138e365328dc404eb5d6a217`; GitHub Actions [run 41185807419](https://github.com/alfred0105/lab-process-rag/actions/runs/41185807419) passed backend, frontend and browser E2E.

## Purpose and completion decision

Phase 4 provides a software core for learning surrogate response models from traceable lab observations and suggesting feasible next conditions. The supported core includes bounded single-objective GP/BO and two-objective Pareto recommendations. Research recommendations remain subject to researcher review and do not execute experiments.

**The core GP/BO software development in Phase 4 is complete. Scientific accuracy validation on actual experimental data, extended optimization algorithms, and optional performance improvements are tracked separately and do not automatically block Phase 5.** This decision closes the agreed Stage 1–3 software core; it does not mark every historical Phase 4 requirement `VERIFIED` and does not assert experimental predictive accuracy.

## Stages

| Stage | Status | Main contents | Evidence |
|---|---|---|---|
| Stage 1 — GP/BO Foundation | `PHASE_4_MVP_IMPLEMENTED` | Gaussian Process Regression, RBF/Matérn, fitted hyperparameters, predictive mean and uncertainty, EI/PI/UCB, candidate persistence, provenance, Branin sandbox, API and UI | Backend 182 tests, frontend build, 3 browser E2E; Actions [41169550349](https://github.com/alfred0105/lab-process-rag/actions/runs/41169550349) |
| Stage 2 — Research data integrity and constraints | `PHASE_4_STAGE_2_IMPLEMENTED` | experiment/replicate pairing, units, measurement noise, grouped holdout, noisy EI, deterministic constraints, feasibility filtering, benchmark comparisons | Backend 189 tests, frontend build, 3 browser E2E; Actions [41171942181](https://github.com/alfred0105/lab-process-rag/actions/runs/41171942181) |
| Stage 3 — Multi-objective optimization | `PHASE_4_STAGE_3_IMPLEMENTED` | two objective GPs, Pareto ranking, exact 2D hypervolume, MC-EHVI, greedy joint MC-HVI batches q=1–4, API/UI and synthetic benchmark | Backend 195 tests, frontend build, 4 browser E2E; Actions [41185807419](https://github.com/alfred0105/lab-process-rag/actions/runs/41185807419) |

Detailed criteria remain in [`PHASE4_STAGE2.md`](PHASE4_STAGE2.md), [`PHASE4_STAGE3.md`](PHASE4_STAGE3.md), and the historical Phase 4 rows of [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md). Do not rewrite the stage statuses when changing the parent phase status.

## Architecture and data contract

- The Stage 1/2 single-objective implementation remains in `backend/app/services/optimization/gpbo.py`, with APIs in `backend/app/api/optimization.py` and feasibility checks in `backend/app/services/optimization/constraints.py`.
- Stage 3 lives alongside it in `backend/app/services/optimization/multiobjective.py` and `backend/app/api/optimization_multiobjective.py`. Stage 3 uses two independent objective GPs; it does not model cross-objective output covariance.
- Research mode selects accepted, non-demo, provenance-bearing observations within the selected topic and method version. Experiment, replicate and process step pairing remain explicit. Group holdout is by experiment to avoid replicate leakage. Missing objective pairs are not imputed.
- Predictions and recommendations are separate from measurements. Recommendations persist with `PENDING_RESEARCHER_REVIEW`; no automatic experiment or equipment action is connected.
- Sandbox values are tagged synthetic and do not create `ScientificObservation` records.
- Existing optimization JSON tables were reused. Stage 3 needed no migration; the current DB head at that point was `0008_gpbo_mvp`.

## Noise, constraints and multi-objective behavior

Stage 2 distinguishes latent/epistemic spread, measurement-noise conditioning and future observation uncertainty under the model's declared noise assumption. Noisy EI samples the posterior rather than treating noisy observed best values as exact. Constraints use typed linear or variable-relation inputs and reject unsupported, conflicting, unit-incompatible or infeasible definitions. Candidate output is never filled with fabricated feasible points.

Stage 3 transforms objective directions into a common minimization frame for Pareto comparisons. The 2D hypervolume is exact for its supplied reference point and positive objective scales. MC-HVI is seeded and reproducible for a fixed input. For q>1, candidates are selected greedily while preserving the joint posterior covariance between candidate locations within each objective. The separate objective models assume objective independence.

## Synthetic benchmark record

Stage 3 compared Random Search, scalarized GP, single MC-EHVI and greedy batch MC-HVI on ZDT1 and Branin–Currin using shared initial designs, five seeds and equal total evaluation budgets. Mean hypervolume values were:

| Benchmark | Random | Scalarized GP | MC-EHVI | Greedy batch MC-HVI |
|---|---:|---:|---:|---:|
| ZDT1 | 8.06270 | 9.91452 | 10.01507 | 9.93745 |
| Branin–Currin | 2.16403 | 2.29610 | 2.23204 | 2.34158 |

These values only verify software behavior on the named synthetic objectives. Hypervolume values use benchmark-specific reference points and cannot be compared across the two rows. Five seeds do not establish policy superiority. The Branin–Currin reference front uses a fixed dense-grid approximation. See [`phase4_stage3_benchmark.json`](../backend/reports/phase4_stage3_benchmark.json) for run settings and resource metadata.

## Performance and boundary

The recorded Stage 3 local synthetic benchmark took 19.34 seconds and the Python process reached 72.2 MiB high-water RSS. This is process-wide high-water memory on one run, not incremental optimizer memory, a sustained service profile, or a measurement of complete M5 system pressure. No long-running/asynchronous optimization, sparse GP, mixed variable search, unknown constraint model, or three-plus objective support is included in core completion.

## Phase 5 entry

Phase 5 does not require completing the optional backlog or obtaining external research data first. It uses the existing `ScientificStateBuilder`/`RuleBasedDecisionPolicy` as input and comparison baselines while keeping learned action selection in a non-executing shadow path. Actual research performance remains an independent validation track.
