# Phase 4 Stage 2 — GP/BO research-data integrity and constraints

**Status:** `PHASE_4_STAGE_2_IMPLEMENTED`  
**Overall Phase 4:** `IN_PROGRESS`  
**External scientific validation:** `PENDING`  
**Decision scope:** software implementation and synthetic numerical behavior only. The repository has no approved research training set, so no experimental predictive accuracy or ZnO-process performance is claimed.

This record implements the Phase 4 Stage 2 request while retaining the Stage 1 GP/BO API, model storage and Stage 1 JSON compatibility. It is additive to [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md) and the prior Phase 3 / Stage 1 records.

## Acceptance ledger

| ID | Requirement and priority | Status | Source / implementation | Verification and completion condition | Related commit | Remaining work / dependency |
|---|---|---|---|---|---|---|
| P4-S2-001 | Separate independent experiments, replicates, observations, unique input conditions and effective GP rows; minimum independent experiments is three. P0 | VERIFIED | `backend/app/api/optimization.py` dataset pairing/count helpers; replicate preservation and explicit inverse-variance aggregation | `backend/tests/test_gpbo_mvp.py`: multiple observations in one experiment, same-condition runs, replicate mismatch, provenance and exact row/count assertions. Full backend suite and CI. | 83fdf39 | The three-run threshold is a software gate, not a guarantee of statistically adequate data. |
| P4-S2-002 | Explicit feature/outcome Process Step pairing and replicate matching; downstream links require researcher declaration and do not imply causality. P0 | VERIFIED | `backend/app/api/optimization.py`; dataset options expose reference step/order; same-step and explicit downstream policies | API integration tests exercise same-step rejection across unrelated steps, downstream explicit relation, and ambiguous replicate matching. | 83fdf39 | User-entered downstream relationship is provenance, not causal proof. |
| P4-S2-003 | Reuse unit normalization; reject incompatible units, invalid uncertainty, missing provenance and insufficient approved data. P0 | VERIFIED | `backend/app/api/optimization.py` uses existing Pint registry and scientific-data normalization | API tests cover K/°C bounds, incompatible constraint dimensions, uncertainty validation, approved-source filtering and insufficient data. Log quantities such as pH are preserved without linear conversion. | 83fdf39 | Material identity and calibration completeness are bounded by the existing observation schema. |
| P4-S2-004 | Distinguish latent epistemic uncertainty, measured-noise conditioning and future observation uncertainty; preserve heteroscedastic training noise. P0 | VERIFIED | `backend/app/services/optimization/gpbo.py` posterior covariance, uncertainty components, jittered Cholesky and JSON round-trip | GP tests validate finite posterior mean, uncertainty decomposition, heteroscedastic covariance behavior, duplicate inputs and serialization. Stage 1 `gpbo-mvp-1` JSON loads. | 83fdf39 | Future-location aleatoric uncertainty uses a declared homoscedastic learned-nugget assumption; a spatial noise model is not learned. |
| P4-S2-005 | Preserve EI/PI/UCB and implement mathematically defined, reproducible noise-aware improvement. P0 | VERIFIED | `noisy_expected_improvement()` samples a joint latent posterior at observed baseline and conditionally samples candidates; seeded, bounded MC calculation | Tests cover same-seed reproducibility, changed noise response, maximization/minimization path, and API recommendation. Benchmark compares random, EI and Noisy EI with shared initial design and equal budgets. | 83fdf39 | Monte Carlo sampling error remains; the current acquisition is one-candidate noisy EI, not batch qNEI. |
| P4-S2-006 | Support structured variable bounds, linear inequalities, tolerant equalities and compatible variable relations without arbitrary code. P0 | VERIFIED | `backend/app/services/optimization/constraints.py`; Pydantic typed API schema; Pint dimensional checks; SciPy linear feasibility solver | Constraint tests cover equality projection, inequality, relations, incompatible dimensions, unsupported types and infeasible sets. No `eval()` path. | 83fdf39 | Nonlinear, uncertain and chemical safety constraints are intentionally unsupported. |
| P4-S2-007 | Recommend only feasible, diverse, nonduplicate candidates and record evaluation/rejection, rank, units and approval state. P0 | VERIFIED | `backend/app/api/optimization.py` filters feasible search points before GP acquisition ranking and persists recommendation lineage | API tests check unit-converted bounds, candidate feasibility, impossible-set errors, unsupported constraints and `PENDING_RESEARCHER_REVIEW`. | 83fdf39 | Finite random candidate generation can return `NO_FEASIBLE_CANDIDATES` for very narrow feasible regions; no experimental execution occurs. |
| P4-S2-008 | Prevent experiment-group leakage and fit preprocessing only on training groups. P0 | VERIFIED | `_group_holdout_indices()` in `backend/app/api/optimization.py`; Experiment ID grouped split | Tests assert an Experiment and its replicates never cross train/holdout; fewer than three independent groups reject validation. API records group counts and strategy. | 83fdf39 | Small datasets yield uncertain holdout metrics; group k-fold/LOEO is future scope. |
| P4-S2-009 | Retain Branin benchmark and add noisy and constrained synthetic benchmarks with >=5 seeds, shared initial data, equal budgets, regret, feasibility and runtime reporting. P0 | VERIFIED | `stage2_sandbox_benchmark()` in `gpbo.py`; saved result in `backend/reports/phase4_stage2_benchmark.json`; reproducible runner `backend/scripts/benchmark_phase4_stage2.py` | Local benchmark: 5 seeds, 12 additional evaluations/policy, σ=0.08; 6.28 s on this Mac. Noisy mean regret: Random 0.00210, EI 0.00654, Noisy EI 0.000786. Constrained feasible rate: constraint-aware 100% (0/60 violations), unconstrained EI 51.7% (29/60), random-feasible 100%. Initial shared design is included in true and measured best values. | 83fdf39 | Only three bounded synthetic objectives are covered; results are seed-sensitive and do not prove BO superiority or material validity. |
| P4-S2-010 | Add backwards-compatible API options, validation and stable explicit error codes. P0 | VERIFIED | `backend/app/api/optimization.py` retains Stage 1 routes; adds dataset options, pairing/replicate/noise/acquisition/constraint and Stage 2 benchmark options | API tests exercise preview, training, reload, prediction, EI/PI/UCB/Noisy EI, feasible and infeasible constraints, and both benchmark endpoints. | 83fdf39 | API remains synchronous and bounded; background optimization is later work. |
| P4-S2-011 | Preserve model/recommendation provenance, counts, settings and model-version compatibility in existing JSON records. P0 | VERIFIED | Existing `optimization_model_runs` / `optimization_recommendation_runs` JSON contracts reused; `gpbo-stage2-2` accepts Stage 1 `gpbo-mvp-1` JSON | Serialization compatibility test; API lifecycle asserts model dataset hash, provenance and pending reviewer approval. No schema migration required. | 83fdf39 | Existing DB schema is JSON-oriented; no extra relational indexes added because Stage 2 queries do not require them. |
| P4-S2-012 | Expose approved-data selectors, step/replicate contracts, counts, units, bounds, constraints, acquisition, uncertainty and isolated sandbox benchmarks in UI. P0 | VERIFIED | `frontend/src/components/OptimizationPanel.tsx`, `frontend/src/api/client.ts`, `frontend/src/language.tsx`, `frontend/src/style.css` | Production build and Playwright browser flow: trains sandbox GP, checks Branin result, selects noisy Stage 2 benchmark, calls API and displays Korean localized result table. | 83fdf39 | The UI does not yet draw generic 1D/2D posterior/constraint regions; numeric tables are provided. |

## Model and data contracts

- Research observations must be accepted, non-demo, normalized and provenance-bearing. Topic and Method Version are isolated.
- Each training pair retains Experiment, replicate/observation, input/output identifiers, Process Step anchors, source identifiers and the selected pairing/replicate policy.
- Same-step pairing compares the explicit step order/name within the selected Method Version. Downstream pairing requires later target step plus user confirmation and a relationship label. Ordering alone is never described as causal evidence.
- Raw replicate observations remain separate by default. Inverse-variance aggregation is opt-in and requires known positive uncertainty; raw source IDs and observations remain in lineage.
- The GP conditions with per-observation known variance plus a learned residual nugget. Latent epistemic standard deviation is separated from future observation standard deviation. Future aleatoric noise uses a homoscedastic nugget assumption and is identified as such.
- Noisy EI samples the joint latent posterior at the noisy baseline inputs, samples candidate values conditionally on the same baseline draws, and computes expected improvement over the sampled latent incumbent. Seed and sample limit are explicit.
- Constraints are deterministic and typed. Unsupported nonlinear or probabilistic constraints fail closed. Candidate feasibility is checked before acquisition ranking, and all returned candidates remain pending researcher review.
- Sandbox data are isolated from `ScientificObservation` research records. The constrained benchmark evaluates mathematically infeasible suggestions only inside the synthetic function to count violations; those values never become experiment records or executable recommendations.

## Reproduction

From `backend/`:

```bash
.venv/bin/python -m scripts.benchmark_phase4_stage2
.venv/bin/pytest -q
```

From `frontend/`:

```bash
npm run build
npm run test:e2e
```

The benchmark runner writes deterministic settings and measurements to `backend/reports/phase4_stage2_benchmark.json`. Wall-clock time is informational and naturally varies by machine/load.

## Phase decision

The 12 Stage 2 software acceptance items are implemented and verified by local unit/integration tests, production build, browser E2E, and the latest pushed CI run recorded in `MASTER_ROADMAP.md`. This closes Stage 2 only. Phase 4 remains `IN_PROGRESS`; approved real research data, external scientific validation, posterior-region visualization, richer validation folds, nonlinear constraints and later multi-objective/batch optimization remain outside this stage.
