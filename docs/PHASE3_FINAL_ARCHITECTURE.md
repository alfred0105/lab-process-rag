# Phase 3 durable scientific execution

## What now runs

FastAPI stores approved OpenFOAM requests in `simulation_runs`; it no longer starts a `ThreadPoolExecutor` inside the web process. A separate process runs `python -m app.worker` (or `backend/scripts/run_worker.sh`) and claims durable rows. The per-user installer `backend/scripts/install_worker_launch_agent.py` installs the Worker as a macOS LaunchAgent; it is active on this Mac. Workflow nodes are persisted in `workflow_runs` and `workflow_nodes`, so the HTTP process and calculation process can restart independently.

`POST /api/workflows` validates a topic-scoped, acyclic graph against the allowlisted Tool Registry. It rejects demo records, cross-topic experiment IDs, unknown tools, invalid analysis modality/source pairs, and PHREEQC steps without explicit approval. Nodes have conditional DB claims, a monotonically increasing lease generation, worker ownership, heartbeat, timeout, attempts, and terminal status. Results are only committed when the worker still owns the same generation. Expired work is marked `REQUIRES_REVIEW`; OpenFOAM is never silently relaunched after an uncertain interruption.

Supported workflow node adapters in this increment are:

- `experiment.data_quality.v1`
- `xrd.local_peaks.v1`, `afm.plane_level_roughness.v1`, `microscopy.otsu_components.v1` through the existing deterministic material adapter
- `phreeqc.aqueous_equilibrium.v1` and `phreeqc.aqueous_sweep.v1` through PHREEQC

Typed handoff references use `{"$ref":{"node":"upstream-key","path":"saturation_indices.Calcite","unit":"1","meaning":"PHREEQC saturation index for Calcite"}}`. The reference must point to a direct dependency and match a declared output unit and meaning. Only result fields with an explicit output contract are available for handoff; unknown scalars are not assigned guessed units. Simulation outputs remain `SIMULATION` / `COMPUTED`, not laboratory measurements.

The React Analysis view now offers a one-click durable XRD workflow for a pending XRD upload, and shows saved workflow nodes, state, error, cancel, and retry. It polls persisted state, so navigation or refresh does not lose the job.

## Run model

- Run one worker process on a 24 GB laptop. OpenFOAM is additionally serialized to one active CFD run. Python-level task timeout and cancellation checks apply to the standalone worker; OpenFOAM uses its guest process group and a bounded solver timeout.
- PHREEQC and material analysis execute in the Worker, never on the FastAPI request thread.
- `--once` claims at most one queued job then exits; used by the cross-process SQLite claim test.
- Workflow creation is not a request to control laboratory equipment. Hardware actions remain outside the Worker.
- Local mode does not authenticate a reviewer or provide multi-user tenant authorization.

## Evidence and limits

- Alembic `0006_durable_workflows` adds workflow history and a simulation lease generation; `0007_workflow_approval_flag` backfills the approval column for an in-progress 0006 database. Both are additive; downgrade intentionally refuses to delete execution history. The local database migrated to `0007_workflow_approval_flag` after a consistent pre-upgrade backup.
- OpenFOAM output validation now requires an actual reported cell count, mesh check evidence, final residuals, and solver `End` evidence. If the installed tutorial output does not contain these values, the run fails validation. The CFD case was **not run** in this increment because no new run approval was given.
- PHREEQC was executed end-to-end through the DAG using the installed PHREEQC engine and `phreeqc.dat`; the test preserves result provenance and computed observations. Results now record the adapter package version and SHA-256 of the exact bundled database file. A separate numerical regression reproduces the published 25 °C pure-water gypsum/anhydrite case from [USGS PHREEQC Example 2](https://water.usgs.gov/water-resources/software/PHREEQC/documentation/phreeqc3-html/phreeqc3-64.htm): anhydrite SI −0.30 and gypsum SI 0.00, within the source's 0.01 rounding. This validates that documented database case only, not ZnO chemistry or precipitation kinetics.
- `backend/scripts/benchmark_phase3.py` measures repeated PHREEQC runtime and process peak RSS only. It does not measure OpenFOAM, ML model coexistence, full-app memory, or scientific accuracy.
- A single-process execution policy is the supported laptop configuration. Multiple worker processes are safe from duplicate claims, but broad resource scheduling and OS-enforced CPU/RAM quotas are not implemented.

## Integration verification matrix

| Scenario | Status | Evidence / remaining work |
|---|---|---|
| 1. XRD original → worker analysis → result and source lineage | IMPLEMENTED | Worker adapter is connected; actual uploaded-data workflow test and browser E2E remain. |
| 2. SEM/TEM scale → segmentation → mask | IMPLEMENTED | Existing adapter is connected; real data workflow and human mask review remain. |
| 3. AFM plane leveling → Sa/Sq/Sz | IMPLEMENTED | Existing adapter is connected; calibrated instrument-file workflow remains unverified. |
| 4. solution inputs → PHREEQC → species/SI | VERIFIED | Real PHREEQC workflow test executes and persists SimulationRun and computed observations; separate installed-engine regression matches USGS Example 2 gypsum/anhydrite saturation indices. ZnO-specific equilibrium validation remains outside this scenario. |
| 5. missing fields/units block execution | VERIFIED | PHREEQC schema and adapter reject missing/invalid inputs; DAG node errors stop descendants. |
| 6. unsupported CFD geometry is blocked | VERIFIED | OpenFOAM planning gate remains before enqueue. |
| 7. literature outputs cannot enter measured training data | VERIFIED | Existing source separation and optimization-eligibility regression tests. |
| 8. duplicate request reuses prior calculation | IN_PROGRESS | Existing direct PHREEQC API reuses keyed output; workflow-level idempotent reuse needs coverage. |
| 9. failed predecessor blocks downstream | VERIFIED | Durable workflow test asserts `BLOCKED` and no claim. |
| 10. worker death → expired lease → safe review | IMPLEMENTED | Recovery marks uncertain runs `REQUIRES_REVIEW`; forced process-crash/lease-expiry test remains. |
| 11. goal change changes tool choice or abstains | VERIFIED | Existing goal-driven registry policy tests. |
| 12. unapproved measurements are excluded from optimization | VERIFIED | Existing acceptance/source-filtering tests. |

## M5 microbenchmark (2026-10-30)

The reproducible command is `cd backend && .venv/bin/python scripts/benchmark_phase3.py --repeats 10`. On the Apple M5 / Python 3.12.14 host on 2026-10-30, 10 repeated Calcite equilibrium calls passed output schema validation: p50 **1.96 ms**, nearest-rank p95 **59.45 ms**, min **1.78 ms**, and process peak RSS **123.42 MB**. The p95 is the slowest of ten samples (one runtime outlier), not a stable service-level estimate. The benchmark reports the actual machine, input, repeat count, schema validation, runtime percentiles, and process peak RSS. It is explicitly a runtime microbenchmark and not a model-accuracy test. Re-run after material code or dependency changes; do not interpret this one operation as whole-application memory.

## Phase 3 disposition

> The following earlier disposition is a historical snapshot. The authoritative current audit is in [`PHASE3_SOFTWARE_CLOSURE.md`](PHASE3_SOFTWARE_CLOSURE.md).

`PHASE_3_IN_PROGRESS`. The durable execution foundation and a real PHREEQC DAG are implemented and tested, and one official PHREEQC reference case is reproduced. The complete 12-scenario system validation, real uploaded XRD/AFM/SEM/TEM workflow coverage, OpenFOAM CFD validation, browser E2E, worker crash recovery, complete adapter coverage, workflow-level idempotency, and full M5 contention measurements remain outstanding. Those items stay open on the master roadmap.

## Final software verification pass (2026-10-30)

The latest test additions and actual verification are tracked in [`PHASE3_SOFTWARE_VERIFICATION_REPORT.md`](PHASE3_SOFTWARE_VERIFICATION_REPORT.md), with detailed additive requirement rows in `MASTER_ROADMAP.md`. On this update, the backend suite reports **153 passed**. Isolated deterministic synthetic AFM, SEM, and TEM worker paths are covered; XRD edge cases and Pint unit conversion through a real worker handoff are covered. A 30-case Planner regression set is included. The PHREEQCAdapter executes one explicit USGS reference batch case. A dedicated Playwright CI job and isolated browser environment passed locally 1/1, including queue, cancel, completion, refresh restoration, failure/retry, and cross-topic isolation.

The scoped Apple M5 24 GiB PHREEQC microbenchmark ran 30 times: p50 1.902 ms, nearest-rank p95 3.168 ms, process peak RSS 140.72 MB. This is one adapter only; it is not a complete service benchmark. No OpenFOAM CFD was executed. No real instrument data was available, so none of the synthetic image/curve tests establish measurement accuracy.

GitHub Actions run [41009238796](https://github.com/alfred0105/lab-process-rag/actions/runs/41009238796) for commit `51953fc` passed all three jobs (backend, production frontend build, and browser E2E). The latest final-pass state remains **`PHASE_3_SOFTWARE_IN_PROGRESS`** until all 12 integrated scenarios and broader workflow performance are verified. The OpenFOAM software parser fixture matrix is verified; no physical CFD was run. External scientific/device validation remains separately pending. See [`PHASE4_HANDOFF.md`](PHASE4_HANDOFF.md) for the optimization observation contract; the Phase 4 optimizer itself is not implemented.

## Latest closure audit — 2026-10-30

The latest local validation on changes after `115d591` reports backend **164 passed**, frontend production build successful, Playwright browser E2E **1 passed**, and a 30-repeat M5 PHREEQC adapter benchmark (p50 1.763 ms, p95 2.092 ms, peak process RSS 140.58 MB). A real PHREEQC result is now consumed numerically by a dependent PHREEQC Worker node, with review/provenance metadata preserved and checked against its persisted source. The current disposition remains **`PHASE_3_SOFTWARE_IN_PROGRESS`** pending full DAG/tool performance measurements and GitHub Actions for the closure commit. No instrument data or approved CFD solver run was used. See [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md) for current Phase 0–7 realignment.
