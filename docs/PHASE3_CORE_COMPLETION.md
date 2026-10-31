# Phase 3 Core Completion

**Official core status: `PHASE_3_CORE_COMPLETE`**
**Evidence snapshot:** code commit `468b2090cf110fc6e0c061f049902bce03ae05aa`; its CI passed in [run 41167692819](https://github.com/alfred0105/lab-process-rag/actions/runs/41167692819). The documentation/archive commit `9eb6ae5793bf15449261f9eb5d410ebd6a000174` also passed [CI run 41167844484](https://github.com/alfred0105/lab-process-rag/actions/runs/41167844484).
**Decision date:** 2026-10-31

> Phase 3의 핵심 소프트웨어 개발은 완료되었으며, 추가 성능 분석과 외부 과학 검증은 별도로 관리한다. 이는 모든 세부 요구사항의 검증 완료나 실제 연구 장비 정확도의 입증을 의미하지 않는다.

## Purpose and core architecture

Phase 3 supplies the scientific data and execution base used by experiment recording, measurement analysis, and later optimization. Its core path is an approved, topic-scoped record or file → data validation and provenance → `ToolRegistry` / `ScientificStateBuilder` / `RuleBasedDecisionPolicy` → `ValidationGate` → workflow planner and durable DAG → independent worker → adapter and `ResultValidator` → typed, persisted result for researcher review.

The execution service includes SQLite/Alembic, FastAPI, the existing React application, durable queue/workflow records, worker leases, heartbeat, fencing, retries, cancellation and timeout handling. Browser flows use workflow identity and persisted state. Actual instrument control is not part of the completion claim.

## Implemented scientific tools

- PHREEQC aqueous equilibrium and pH sweep use the installed engine and versioned database fingerprint. Calculated results retain `COMPUTED` state, tool/version, source and typed parent lineage; they are not silently accepted measurements.
- XRD, AFM, SEM and TEM have local analysis adapters and persisted material-analysis runs. XRD conversion across `2θ`, `q`, and `d` axes uses Bragg's law, validates wavelength and physical domains, and writes an immutable, provenance-linked child run.
- OpenFOAM has a constrained, approval-based execution structure. This archive does not claim a CFD case was run or physically validated.
- Approved observation retrieval separates accepted lab records from outcomes and excludes literature, simulation, synthetic demo and unapproved values from the experimental training path.

## Core verification evidence

- Full local backend regression: **178 passed**.
- Browser E2E: **2 passed**, validating PHREEQC-first and XRD flows by their own Workflow IDs.
- Frontend production build: **passed** (Vite 6.4.5, 1,757 modules).
- Latest archive commit CI: [run 41167844484](https://github.com/alfred0105/lab-process-rag/actions/runs/41167844484), with backend, frontend build and browser E2E jobs all successful.
- Isolated durable benchmark: XRD/AFM/SEM/TEM and warm PHREEQC each 20/20; two-node PHREEQC handoff 20/20; same-key and distinct-key two-worker cases completed; one completed result was reused through the cache. Raw output: [`phase3_durable_benchmark.json`](../backend/reports/phase3_durable_benchmark.json) and [CSV](../backend/reports/phase3_durable_benchmark.csv).
- This benchmark is synthetic software-path evidence, not scientific accuracy evidence. API and Worker RSS are not independently isolated; cold/cache samples and restart/retry timing are not a statistically complete performance study.

## Scope boundary and limitations

Core completion means the existing application can validate, schedule, run, persist and display its supported scientific software workflows, with reviewed data kept separate from computed output. The detailed requirement ledger retains the original IDs and their individual `IMPLEMENTED`, `VERIFIED`, `IN_PROGRESS`, or other status. Core completion does **not** upgrade every ledger row or close its remaining checks.

Non-blocking performance and broader recovery checks are tracked in [`PHASE3_TECHNICAL_BACKLOG.md`](PHASE3_TECHNICAL_BACKLOG.md). Device-reference comparisons and approved CFD are tracked in [`PHASE3_EXTERNAL_VALIDATION.md`](PHASE3_EXTERNAL_VALIDATION.md). A newly found data-integrity, authorization, wrong-result handoff or serious security defect remains blocking and must be fixed regardless of the phase label.

## Phase 4 entry basis

Phase 3 provides accepted, normalized, provenance-bearing observation records and a tested execution foundation. Phase 4 can therefore begin with its own strict dataset builder, keeping sandbox data isolated from research records. There are currently no approved research training data in the repository; research-mode GP must return `INSUFFICIENT_APPROVED_DATA` until valid records are provided.
