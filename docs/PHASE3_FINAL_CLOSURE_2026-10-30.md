# Phase 3 final closure audit — 2026-10-30

This is an additive closure record. It preserves earlier audit history and does not mark unmeasured or partially exercised requirements complete.

## Decision

**Current phase status: `PHASE_3_SOFTWARE_IN_PROGRESS`.** The implementation and tests below close several known gaps, but the full required cache/concurrency/API-vs-worker benchmark matrix and the complete typed-artifact contract across every executable adapter are still open. The 24 GB M5 is measured only for the local single-process benchmark described below. External instrument accuracy and approved OpenFOAM/CFD validation remain `EXTERNAL_VALIDATION_PENDING`.

No Phase 5/6 work was started. Phase 4 remains a handoff only; no Gaussian Process or Bayesian Optimization implementation was started.

## Work completed in this closure pass

### P3-FC-01 — Analysis artifact integrity manifest

Added `backend/app/services/artifacts.py`. Original measurement files and generated image artifacts now record SHA-256, byte size, MIME type, root-relative storage path, source run key, parent IDs, tool/version, settings, source type, validation state, and review state. This metadata remains in the existing JSON column; this change does not require a database migration. Pending uploads receive a manifest before analysis starts. Direct and durable Worker analysis attach manifests to completed results.

Original and derived-file reads validate containment, reject path traversal and symlink components, ensure the manifest path matches the stored path, and verify size and SHA-256 before returning bytes. Legacy files without a manifest remain readable only within the analysis root and without symlinks; new files fail closed on integrity mismatch. API tests mutate a stored source and confirm the read is rejected.

**Verification:** direct API, worker-persisted SEM/TEM artifacts, tamper rejection, path traversal, symlink rejection, and metadata lineage assertions are covered by `test_material_analysis_api.py`, `test_material_durable_workflows_synthetic.py`, and `test_artifact_integrity.py`.

### P3-FC-02 — XRD reanalysis identity and preservation

The XRD API reuses a result only when the topic, experiment scope, input SHA-256, modality/tool, algorithm version, and complete settings match. A changed declared axis setting creates a new result while retaining the old run. A stored result whose algorithm version no longer matches also creates a fresh run.

The analyzer preserves the declared source axis (`2theta_deg`, `d_angstrom`, or `q_angstrom^-1`). It does **not** currently convert data between those axes. Wavelength remains mandatory for the separate reference-pattern comparison request; a generalized reanalysis-axis conversion tool and its wavelength-dependent conversions are still open work and are not claimed as complete.

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

This benchmark is **partial**: it does not yet measure full cold/warm/cached DAG execution, actual cache-hit reuse latency, concurrent load/throughput, API and Worker process RSS separately, all DAG persistence stages, or queue-to-terminal end-to-end latency distributions. Those are required before the integrated performance item can be VERIFIED.

## Phase 4 handoff boundary check

The existing approved-observation endpoint can emit topic, experiment, method version, process step, parameter/material IDs, normalized value/unit, uncertainty, replicate ID, source type, source ID, and analysis run ID. It filters to accepted real lab records/results and requires paired input/outcome experiments. It does not yet emit variable bounds, encoded physical constraints, or a fully validated optimization-ready contract matching every field in `docs/PHASE4_HANDOFF.md`. Keep this as a Phase 4 contract task; no optimizer is introduced here.

## Requirement-to-test closure map

| Requirement | Test/evidence | State |
|---|---|---|
| Artifact hashes, sizes, MIME, paths, parents, tool/version/settings, source/review state | `test_artifact_integrity.py`; direct and Worker material workflow tests | `VERIFIED` for material-analysis original/derived files |
| Artifact mutation, traversal, symlink safety | `test_artifact_integrity.py`; API tamper response check | `VERIFIED` for tested artifact read paths |
| XRD same-settings reuse and changed-settings reanalysis | `test_material_analysis_api.py` | `VERIFIED` for current XRD preview tool |
| XRD algorithm update invalidates prior result while retaining history | `test_material_analysis_api.py` | `VERIFIED` for direct API version comparison |
| XRD axis conversion with required wavelength | No conversion implementation; declared axis is preserved | `IN_PROGRESS` |
| PHREEQC equilibrium comparison against equivalent raw deck | `test_ph_simulation.py` | `VERIFIED` as adapter regression only |
| PHREEQC pH sweep equivalent-deck comparisons | `test_ph_simulation.py` | `VERIFIED` at tested points |
| PHREEQC planner browser/API/approval/queue/result flow | `frontend/e2e/workflow.spec.ts` | `VERIFIED` for the local browser run: pre-approval plan blocked, approved workflow queued and completed, result visible after reload |
| Integrated execution benchmark | `backend/scripts/benchmark_phase3_integrated.py` and JSON/CSV | `IN_PROGRESS`; cached/concurrent/full DAG/API-vs-worker measurements remain |
| Phase 4 database-to-contract extraction | `docs/PHASE4_HANDOFF.md`, optimization observations API | `IN_PROGRESS`; physical bounds and full contract validation remain |
| Existing INT-01..12 regressions | backend full suite and E2E | Preserve prior mapping; rerun results are in this commit's verification record |

## Current local verification record

Latest full backend run: `169 passed`; `209` warnings remain (SQLAlchemy `datetime.utcnow()`, SWIG, Starlette TestClient/httpx deprecations). Latest frontend production build: successful, TypeScript passed, Vite transformed 1,757 modules. Latest full Playwright run: `2 passed`, including the PHREEQC browser path. GitHub Actions run [41016536590](https://github.com/alfred0105/lab-process-rag/actions/runs/41016536590) for code commit `278f66824010113f390fa9185627001f4707123e` passed backend, frontend, and browser E2E jobs.

## Limits and follow-up

- Phase 3 remains open until the integrated performance matrix and common typed artifact contract are complete and tested for every executable adapter, including simulation artifacts and restart/retry paths.
- XRD conversion between axis systems is not provided. Do not imply a `d`/`q` conversion from a label alone; conversion must be a separate parameterized operation that requires wavelength where applicable.
- The final backend run still reports existing deprecation warnings, including `datetime.utcnow()`, Starlette TestClient/httpx, and SWIG native bindings. They do not fail tests but remain cleanup work.
- `PHREEQC` does not prove precipitation or growth, and the equivalent-deck comparison does not eliminate PHREEQC model/database limitations.
- No OpenFOAM physical case was run. Running one still requires explicit researcher approval and a separately supported/validated environment.
