# Phase 5 Stage 1 — Learned Decision Head MVP

**Decision:** `PHASE_5_STAGE_1_MVP_IMPLEMENTED`
**Overall Phase 5:** `IN_PROGRESS`
**Dataset used for software benchmark:** synthetic fixtures only
**Research accuracy:** not validated

## Acceptance ledger

| ID | Requirement | Status | Implementation and verification |
|---|---|---|---|
| P5-S1-001 | ScientificState → versioned deterministic feature vector | `VERIFIED` | `backend/app/services/decision_head.py`; deterministic extraction and outcome-neutral feature regression test |
| P5-S1-002 | Provenance-aware labels, review state, candidate actions and isolation | `VERIFIED` | `DecisionCase`, Alembic `0009`, `/cases`, separate research/synthetic dataset filters; API tests |
| P5-S1-003 | Trainable multiclass Decision Head, persistence, deterministic seed | `VERIFIED` | NumPy MLP, training-loss update, JSON model serialization and reload test |
| P5-S1-004 | Action probabilities, calibration metrics, abstention | `VERIFIED` | Temperature scaling when sample criteria are met, Brier/NLL/ECE/risk–coverage and safe inference tests |
| P5-S1-005 | OOD and unsupported-state guard | `VERIFIED` | Feature-range and missing-state gate with far-value and sparse-state tests |
| P5-S1-006 | Rule and majority baselines | `VERIFIED` | Same validation partition and metrics in training response and benchmark report |
| P5-S1-007 | Workflow-safe shadow mode | `VERIFIED` | API marks shadow, sets `workflow_triggered: false`, and never calls a workflow runner; API/E2E assertions |
| P5-S1-008 | Readiness, label, training, model, prediction and compare API | `VERIFIED` | FastAPI router and API integration tests including insufficient research data and topic isolation |
| P5-S1-009 | Minimal integrated Decision UI | `VERIFIED` | Existing app tab, API client and UI; production build and Playwright shadow flow |
| P5-S1-010 | Synthetic benchmark and regression/CI | `IMPLEMENTED` | Benchmark report, full local tests/build/E2E and fresh migration evidence recorded below; latest commit CI must pass before promotion to `VERIFIED` |

The acceptance gate is software implementation, not research efficacy. P5-S1-010 remains `IMPLEMENTED` until the current commit's full test/build/E2E results and GitHub Actions are recorded. The Stage 1 MVP decision does not close Phase 5.

## Implementation map

| Component | Source |
|---|---|
| Feature schema, extraction, MLP, calibration, OOD, metrics, splits | `backend/app/services/decision_head.py` |
| Training/readiness/label/predict/compare API | `backend/app/api/decisions.py` |
| Decision case and model-run persistence | `backend/app/db/models.py` |
| Alembic schema revision | `backend/migrations/versions/0009_learned_decision_head.py` |
| FastAPI router registration | `backend/app/main.py` |
| Integrated panel | `frontend/src/components/DecisionPanel.tsx`, `frontend/src/pages/App.tsx` |
| API client and styling | `frontend/src/api/client.ts`, `frontend/src/style.css` |
| Tests | `backend/tests/test_phase5_stage1_decisions.py`, `frontend/e2e/b_optimization_sandbox.spec.ts` |
| Reproducible benchmark | `backend/scripts/benchmark_phase5_stage1.py` |
| Benchmark output | `backend/reports/phase5_stage1_decision_benchmark.json` |

## Synthetic benchmark results

Environment: Python 3.12.14, macOS arm64, NumPy 2.5.4. Seed 7. The 180 synthetic cases were grouped by independent scenario: 108 fit/training, 24 calibration and 48 validation. The model is an 18→12→6 tanh MLP, approximately 7,359 serialized bytes.

| Measure | Learned head | Rule baseline | Majority baseline |
|---|---:|---:|---:|
| Accuracy | 0.9583 | 0.7083 | 0.1667 |
| Macro F1 | 0.9577 | 0.6636 | 0.0476 |
| Negative log likelihood | 0.1178 | — | — |
| Brier score | 0.0724 | — | — |
| ECE, 10 bins | 0.0353 | — | — |
| Risk at 100% coverage | 0.0417 | — | — |

Observed synthetic run: training loss decreased from 1.7921 to 0.2832; temperature scaling used a separate scenario-group calibration split. Inference p50/p95 were approximately 0.0075/0.0077 ms for the benchmark's single-vector MLP call; model size was 7.36 KB. Process high-water RSS was 36,143,104 bytes, which is whole-process memory and not incremental head memory. Far numeric input returned `POTENTIAL_OOD`; a mostly missing state returned `UNSUPPORTED_STATE`.

These values are reproducible software-fixture results, not a claim that the model outperforms human experts or is accurate on laboratory decisions. The synthetic patterns are intentionally structured by action family, so their accuracy must not be used to estimate deployment accuracy. The rule baseline is an engineering comparison, not human ground truth. See the full confusion matrix, reliability bins, risk–coverage curve and run metadata in the JSON report.

## Verification evidence

- The Alembic chain reaches `0009_learned_decision_head` on a fresh temporary SQLite database.
- A compatibility test that previously asserted the old DB head `0008_gpbo_mvp` was updated to expect the new migration head; it still checks repeated upgrade/idempotence and legacy schema preservation.
- Backend full suite: **200 passed**, 312 existing deprecation warnings, 41.35 seconds.
- Frontend production build: **passed**, Vite transformed 1,760 modules; DecisionPanel emitted as a separate 11.35 kB chunk.
- Browser E2E: **5 passed** (PHREEQC approval workflow, single-objective GP/BO, multi-objective GP/BO, learned decision shadow flow, durable XRD workflow).
- Fresh temporary SQLite migration: reached `0009_learned_decision_head`; legacy repeated-upgrade test passes against the new head.
- Latest GitHub Actions: pending push; do not mark P5-S1-010 `VERIFIED` until this commit's workflow succeeds.

## Remaining limitations

- No reviewed research dataset was available; the research trainer correctly reports `INSUFFICIENT_REVIEWED_DECISIONS`.
- Reviewer name is self-entered because this local application does not currently authenticate users.
- Current feature snapshots do not reconstruct historical decision-time state.
- OOD is a simple range/missingness gate and has no measured sensitivity/specificity on real labels.
- Score calibration is only a small holdout check; it is not deployment calibration.
- No Transformer weights, conditional LM, action execution, tool invocation, device control or autonomous optimization loop is included.

## Next stage boundary

Phase 5 continues with a reviewed-data acquisition and stronger state/action evaluation plan. Phase 6 remains `NOT_STARTED`; it owns shared Transformer representations, conditional language generation and any Early Exit experiments. Phase 8 remains `NOT_STARTED` and owns broad UX/accessibility validation, while this MVP keeps the current single integrated UI.
