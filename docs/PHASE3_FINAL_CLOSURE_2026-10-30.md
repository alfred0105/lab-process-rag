# Phase 3 definitive closure audit — historical verification snapshot 2026-10-31

> Status history: this document records the 2026-10-31 software verification decision and the then-open detailed checks. The later project decision separates `PHASE_3_CORE_COMPLETE` from non-blocking technical backlog and external validation. Current phase status is maintained in [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md); core evidence is summarized in [`PHASE3_CORE_COMPLETION.md`](PHASE3_CORE_COMPLETION.md). Do not rewrite the historical `IN_PROGRESS` audit into blanket `VERIFIED` states.

## Latest verification update — 2026-10-31

This update supersedes the older local run counts and E2E caveats below while preserving their dated audit history. The latest code commit is `468b2090cf110fc6e0c061f049902bce03ae05aa`.

**Historical audit decision: `PHASE_3_SOFTWARE_IN_PROGRESS`.** XRD axis conversion and workflow-ID-specific browser checks were locally verified. The durable benchmark ran the real API route through `TestClient`, a disposable SQLite queue, and the real Worker execution path. At that audit point, the complete software exit gate remained open because API and Worker process resources were not independently profiled for the whole matrix, restart/retry latency was not included in the benchmark, and the all-adapter artifact/recovery contract audit was incomplete. See the status history note above for the later core/backlog separation.

The latest full backend run passed **178 tests**. The production frontend build passed (Vite 6.4.5, 1,757 modules). The reordered browser E2E run passed **2 tests** with PHREEQC first and XRD second; each flow checks its own Workflow ID. The PHREEQC and XRD tests also passed separately in earlier runs. The backend run reported 211 warnings, mainly `datetime.utcnow()`, SWIG, and Starlette TestClient/httpx deprecations.

The repeatable benchmark is `backend/scripts/benchmark_phase3_durable.py`; data is in `backend/reports/phase3_durable_benchmark.json` and `.csv`. It uses only a temporary database and generated XRD/AFM/SEM/TEM fixtures. At 20 repetitions each, every measurement workflow and each two-node PHREEQC workflow completed 20/20. Selected end-to-end workflow p50/p95 (seconds): XRD 0.00603/0.00745; AFM 0.00599/0.00616; SEM 0.00641/0.00700; TEM 0.00647/0.00686; PHREEQC warm 0.00911/0.00986; two-node PHREEQC 0.01346/0.01556. One fresh Worker process PHREEQC execution measured 0.907 s including Python startup. A true completed-workflow cache reuse was observed (1 hit; 4.28 ms p50 in this single observation). Two concurrent same-key workflows completed using one SimulationRun; two distinct-key workflows completed using two SimulationRuns. Concurrent Worker RSS sampled maximum was about 149.2 MiB; one fresh PHREEQC Worker peak RSS was about 140.7 MiB.

These are local software timings, not scientific accuracy or throughput claims. Warm Worker calls run in the benchmark controller process, which combines TestClient/API and controller memory; controller peak RSS is not API-only memory. `ps` polling can miss short-lived RSS peaks. Cold and cached workflows currently have one observation each, so their p95 is not a stable percentile. Worker process restart recovery is covered by regression tests, but its recovery latency is not part of the timing matrix. Database persistence is included in Worker node time rather than independently timed.

GitHub Actions run [41167692819](https://github.com/alfred0105/lab-process-rag/actions/runs/41167692819) passed for code commit `468b2090cf110fc6e0c061f049902bce03ae05aa`: backend, frontend build, and browser E2E all succeeded. No Phase 4 optimizer, JEV, Transformer, or physical experiment control was implemented. External instrument accuracy and approved OpenFOAM/CFD remain `EXTERNAL_VALIDATION_PENDING`.

# Phase 3 final closure audit — 2026-10-30

This is an additive closure record. It preserves earlier audit history and does not mark unmeasured or partially exercised requirements complete.

## Decision

**Historical status at this audit snapshot: `PHASE_3_SOFTWARE_IN_PROGRESS`.** See the latest dated update above for current evidence and remaining requirements. External instrument accuracy and approved OpenFOAM/CFD validation remain `EXTERNAL_VALIDATION_PENDING`.

No Phase 5/6 work was started. Phase 4 remains a handoff only; no Gaussian Process or Bayesian Optimization implementation was started.

## Work completed in this closure pass

### P3-FC-01 — Analysis artifact integrity manifest

Added `backend/app/services/artifacts.py`. Original measurement files and generated image artifacts now record SHA-256, byte size, MIME type, root-relative storage path, source run key, parent IDs, tool/version, settings, source type, validation state, and review state. This metadata remains in the existing JSON column; this change does not require a database migration. Pending uploads receive a manifest before analysis starts. Direct and durable Worker analysis attach manifests to completed results.

Original and derived-file reads validate containment, reject path traversal and symlink components, ensure the manifest path matches the stored path, and verify size and SHA-256 before returning bytes. Legacy files without a manifest remain readable only within the analysis root and without symlinks; new files fail closed on integrity mismatch. API tests mutate a stored source and confirm the read is rejected.

**Verification:** direct API, worker-persisted SEM/TEM artifacts, tamper rejection, path traversal, symlink rejection, and metadata lineage assertions are covered by `test_material_analysis_api.py`, `test_material_durable_workflows_synthetic.py`, and `test_artifact_integrity.py`.

### P3-FC-02 — XRD reanalysis identity and preservation

The XRD API reuses a result only when the topic, experiment scope, input SHA-256, modality/tool, algorithm version, and complete settings match. A changed declared axis setting creates a new result while retaining the old run. A stored result whose algorithm version no longer matches also creates a fresh run.

The analyzer preserves the declared source axis (`2theta_deg`, `d_angstrom`, or `q_angstrom^-1`). At this historical snapshot it did not convert axes. See the 2026-10-31 update: `POST /api/analysis/runs/{run_id}/convert-axis` now applies physical Bragg-law conversions and persists an immutable child analysis run with source lineage.

**Verification:** API tests cover identical-input/settings reuse, changed-settings new run, previous-run retention, and algorithm-version invalidation. Existing tests cover axis declaration preservation and reject unsupported axis declarations.

### P3-FC-03 — PHREEQC equivalent-deck numerical regression

Added a separately authored raw PHREEQC input-deck check using exactly the same temperature, fixed pH, analytical totals, and selected mineral phase as the general adapter. Species molalities and calcite saturation index are compared at relative/absolute tolerances of `1e-8`. Each point in the pH sweep is checked against a separately run equivalent deck at the same pH.

This is a strong adapter/input-translation regression, but both paths use the same PHREEQC engine and `phreeqc.dat`; it is not an independent engine validation or a claim that the database represents a particular real experiment.

### P3-FC-04 — Browser PHREEQC planner path

The durable workflow panel now accepts explicit analytical totals, temperature, fixed pH, and phases for PHREEQC planning. Chemistry inputs start blank (totals are `{}`); no example chemistry or implicit pH/temperature is inserted. Required temperature and pH must be entered before planning. It never converts recipe masses or volumes into analytical totals. Explicit researcher approval is required to make the plan executable. Editing the goal, experiment, or any chemistry input clears the approval checkbox and invalidates the old plan.

Added Playwright coverage for input entry, a pre-approval plan that remains non-executable, an approved plan, queue registration, Worker completion, and visible result/tool state. This validates the current browser/API/queue result path with isolated synthetic test records; it does not validate chemistry inputs as a real laboratory composition.

### P3-FC-05 — Integrated local benchmark

Added `backend/scripts/benchmark_phase3_integrated.py`, which uses a disposable SQLite database and generated synthetic files. It writes JSON and CSV results under `backend/reports/`. It measures 15 software paths: Scientific State Builder, rule policy, workflow planner, validation gate, result schema validator, typed unit conversion, PHREEQC cache identity generation, XRD, AFM, SEM, TEM, PHREEQC execution, SQLite workflow enqueue, Worker claim, and SQLite read/write persistence round trip.

The 5-repeat M5 run is recorded in `backend/reports/phase3_integrated_benchmark.json` and `.csv` (macOS 27.0.1 arm64, Python 3.12.14). It reported zero operation errors and process peak RSS of 158.47 MB. Selected p50s: workflow planner 0.238 ms, XRD 0.756 ms, AFM 2.693 ms, SEM 0.593 ms, TEM 0.617 ms, PHREEQC 1.886 ms, SQLite enqueue 0.535 ms, Worker claim 1.008 ms, and SQLite read/write round trip 0.402 ms. At five repetitions the p95 values are nearest-rank and unstable; the JSON/CSV include p50/p95/min/max for each operation. These timings measure software paths only and are not scientific performance claims.

This benchmark was **partial at the original audit snapshot**. The separate durable benchmark now measures queue-to-terminal workflow latency, fresh Worker startup, warm local execution, cache reuse, typed multi-node handoff, and same-/different-key two-Worker cases. Independent API/Worker memory, statistically repeated cold/cache runs, restart/retry timing, and single-vs-multiple Worker throughput remain open.

## Phase 4 handoff boundary check

The existing approved-observation endpoint can emit topic, experiment, method version, process step, parameter/material IDs, normalized value/unit, uncertainty, replicate ID, source type, source ID, and analysis run ID. It filters to accepted real lab records/results and requires paired input/outcome experiments. It does not yet emit variable bounds, encoded physical constraints, or a fully validated optimization-ready contract matching every field in `docs/PHASE4_HANDOFF.md`. Keep this as a Phase 4 contract task; no optimizer is introduced here.

## Requirement-to-test closure map

| Requirement | Test/evidence | State |
|---|---|---|
| Artifact hashes, sizes, MIME, paths, parents, tool/version/settings, source/review state | `test_artifact_integrity.py`; direct and Worker material workflow tests | `VERIFIED` for material-analysis original/derived files |
| Artifact mutation, traversal, symlink safety | `test_artifact_integrity.py`; API tamper response check | `VERIFIED` for tested artifact read paths |
| XRD same-settings reuse and changed-settings reanalysis | `test_material_analysis_api.py` | `VERIFIED` for current XRD preview tool |
| XRD algorithm update invalidates prior result while retaining history | `test_material_analysis_api.py` | `VERIFIED` for direct API version comparison |
| XRD axis conversion with required wavelength | `test_xrd_axis_conversions_round_trip_against_bragg_law`, `test_xrd_axis_conversion_rejects_missing_or_nonphysical_inputs`, `test_xrd_axis_converted_result_preserves_intensity_and_declares_transform`, `test_material_analysis_api.py` | `VERIFIED` for the supported 2θ/d/q conversions and persisted child-run lineage |
| PHREEQC equilibrium comparison against equivalent raw deck | `test_ph_simulation.py` | `VERIFIED` as adapter regression only |
| PHREEQC pH sweep equivalent-deck comparisons | `test_ph_simulation.py` | `VERIFIED` at tested points |
| PHREEQC planner browser/API/approval/queue/result flow | `frontend/e2e/a_phreeqc_workflow.spec.ts` | `VERIFIED` locally with exact Workflow ID, completed PHREEQC node, SimulationRun ID, database fingerprint, refresh persistence |
| XRD browser workflow and exact run identity | `frontend/e2e/workflow.spec.ts` | `VERIFIED` locally with exact Workflow IDs for cancel, complete, retry, and reload assertions |
| Integrated execution benchmark | `backend/scripts/benchmark_phase3_durable.py`, `backend/reports/phase3_durable_benchmark.json`, `.csv` | `IN_PROGRESS`; full workflows/cold/warm/cache/multi-node/same- and different-key concurrency measured. Independent API/Worker memory, restart/retry timing and throughput scaling remain |
| Phase 4 database-to-contract extraction | `docs/PHASE4_HANDOFF.md`, optimization observations API | `IN_PROGRESS`; physical bounds and full contract validation remain |
| Existing INT-01..12 regressions | backend full suite and E2E | Preserve prior mapping; rerun results are in this commit's verification record |

## Current local verification record

At the original audit snapshot: backend 169 passed and Playwright 2 passed. The latest run records in the 2026-10-31 update supersede those counts.

## Limits and follow-up

- Phase 3 remains open until the integrated performance matrix and common typed artifact contract are complete and tested for every executable adapter, including simulation artifacts and restart/retry paths.
- XRD conversion is provided for supported axes; retain the explicit wavelength and transformation metadata when interpreting converted values.
- The final backend run still reports existing deprecation warnings, including `datetime.utcnow()`, Starlette TestClient/httpx, and SWIG native bindings. They do not fail tests but remain cleanup work.
- `PHREEQC` does not prove precipitation or growth, and the equivalent-deck comparison does not eliminate PHREEQC model/database limitations.
- No OpenFOAM physical case was run. Running one still requires explicit researcher approval and a separately supported/validated environment.
