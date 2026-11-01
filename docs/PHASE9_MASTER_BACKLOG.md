# Phase 9 Master Backlog

**Official name:** Phase 9 — System Integration, Advanced Optimization & Scientific Validation
**Status:** `REGISTERED_NOT_STARTED`
**Execution rule:** registration and planning only during Phase 8. Phase 9 feature implementation has not started. P0 safety, data-integrity, security, or approval-bypass defects must still be fixed immediately if discovered.

Phase 9 consolidates deferred work from Phases 0–8 without deleting its original requirement ID, historical status, source, or evidence. The detailed historical records remain in [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md), [`PHASE3_TECHNICAL_BACKLOG.md`](PHASE3_TECHNICAL_BACKLOG.md), [`PHASE4_TECHNICAL_BACKLOG.md`](PHASE4_TECHNICAL_BACKLOG.md), [`PHASE5_TECHNICAL_BACKLOG.md`](PHASE5_TECHNICAL_BACKLOG.md), and Phase 6/7 design and closure documents.

## Priority and state conventions

- **P0 Critical:** live data-integrity, security, safety, authorization, or approval-gate defect. Fix immediately; do not defer a known defect.
- **P1 Core Expansion:** connect or complete an existing feature.
- **P2 Optimization:** measured performance, resource use, refactoring, and usability improvements.
- **P3 External Validation:** requires real reviewed laboratory data, an approved external environment, or expert/user study. Lack of required material is recorded as `BLOCKED_EXTERNAL_DATA` or `EXTERNAL_VALIDATION_PENDING`, never as a pass.
- Statuses follow the repository's `NOT_STARTED`, `IN_PROGRESS`, `IMPLEMENTED`, `VERIFIED`, `REVISED`, `BLOCKED` vocabulary. `VERIFIED` requires actual code and relevant executed tests; planning alone does not qualify.

## P9-A — AI Decision & Model Integration

| Phase 9 ID | Original Phase / Requirement ID | Description and current status | Remaining work | Priority | Dependency / completion condition |
|---|---|---|---|---|---|
| P9-A01 | P5 / P5-S4-001–012, JEV decision-head requirements | Synthetic-only diagnostics and software contracts exist; reviewed research decision validity remains pending. `EXTERNAL_VALIDATION_PENDING` | Build a versioned dataset from reviewed research outcomes; preserve group isolation and review provenance; evaluate calibration, abstention, and decision errors on frozen independent research groups. | P3 | Reviewed labels and independent holdout; report errors/uncertainty without promoting a model automatically. |
| P9-A02 | P6 / P6-002–009; P7 / P7-FINAL-001, P7-FINAL-004 | Shared Transformer runtime and Campaign adapter exist, but Campaign adapter state is sparse and current local model invocation fell back on OOD. `IN_PROGRESS` | Map actual Campaign state, tool result, source lineage, uncertainty, and review state into the versioned ScientificState contract; improve explicit fallback reason and capability checks. | P1 | Contract tests for missing/unknown fields, source non-leakage, schema mismatch, OOD, and incompatible runtime. |
| P9-A03 | P6 / EE-012, P6-007; P7 / Phase 7 trained JEV extension | COMBO-C/EEFP sandbox comparison and sandbox early-exit hook exist; adaptive Research execution is not enabled. `EXTERNAL_VALIDATION_PENDING` | Integrate only after human-reviewed data supports calibrated Research routing; retain shadow and deterministic fallback; preserve raw prediction vs final safe action. | P0/P3 | Real labels, independent safety review, parity and latency evidence, and explicit approved model version. |
| P9-A04 | P5/P6 model lifecycle requirements | Local artifact metadata exists; complete deployment, promotion, rollback, and compatibility lifecycle remains incomplete. `IN_PROGRESS` | Version artifact, encoder, calibration, OOD detector, training data hash and action schema together; add signed/immutable promotion and rollback rules. | P1 | Artifact compatibility/rejection tests and an auditable promotion record. |

## P9-B — Transformer & Runtime Optimization

| Phase 9 ID | Original Phase / Requirement ID | Description and current status | Remaining work | Priority | Dependency / completion condition |
|---|---|---|---|---|---|
| P9-B01 | P6 / P6-004–008, P6-010–011, EE-* | Shared Qwen backbone, synthetic sandbox adaptive hook, MPS FP16 measurements, and KV reuse exist. No Research early-exit claim. `IN_PROGRESS` | Evaluate actual runtime lifecycle, safe cache reuse, token/hidden-state parity, and supported early-exit runtime configurations. | P2 | Reproducible workload and version-pinned local runtime report; do not convert synthetic parity into scientific validity. |
| P9-B02 | P6 / P6-010; global MacBook Air M5 24GB target | MPS FP16 has partial measurements; quantized paths, energy, thermals, full peak memory, and MLX/Ollama comparisons remain unmeasured. `IN_PROGRESS` | Compare PyTorch/MPS, MLX, and Ollama only where functional; test available INT8/INT4 formats, memory, latency, power/thermal behavior, and model quality separately. | P2 | Pin hardware/OS/runtime/checkpoint and disclose unavailable runtimes and non-comparable precision. |
| P9-B03 | P0 / performance and runtime budgets | Request-level responsiveness and sustained Campaign resource use are not fully profiled. `NOT_STARTED` | Establish task-specific latency, memory, CPU/GPU, and recovery measurements before optimizing bottlenecks. | P2 | Workload definition and actual device measurements; no invented targets. |

## P9-C — Advanced Scientific Tool Orchestration

| Phase 9 ID | Original Phase / Requirement ID | Description and current status | Remaining work | Priority | Dependency / completion condition |
|---|---|---|---|---|---|
| P9-C01 | P3 / PHREEQC typed workflow backlog; P7 / P7-FINAL-002 | Existing PHREEQC workflow exists outside Campaign. Campaign currently requests explicit input and researcher approval. `IN_PROGRESS` | Add typed input collection, database/tool/version provenance, approval confirmation, run state, validation, and safe Campaign handoff. | P1 | API + worker integration test proving no missing-input defaults and preserving simulation source type. |
| P9-C02 | P3 / XRD, AFM, microscopy and tool backlog; P7 / P7-FINAL-002 | Campaign can reuse compatible saved results from a limited set of modalities; it does not execute raw file analyzers dynamically. `IN_PROGRESS` | Expand only registered adapters with explicit input schema, compatible-result matching, result validation, retry and review behavior. | P1 | One end-to-end test per added adapter; preserve raw source files and analysis lineage. |
| P9-C03 | P3 / DAG and planner requirements | Durable worker/DAG execution exists; broad multi-tool adaptive plans and long-running recovery remain incomplete. `IN_PROGRESS` | Add multi-step validated typed handoffs, resumable failures, cancellation, idempotency and resource estimates for campaign orchestrations. | P1 | Failure/restart/retry tests and explicit approval for any external computation. |

## P9-D — Advanced Experiment Optimization

| Phase 9 ID | Original Phase / Requirement ID | Description and current status | Remaining work | Priority | Dependency / completion condition |
|---|---|---|---|---|---|
| P9-D01 | P4 / multi-objective BO; P7 / multi-objective campaign extension | Multi-objective optimizer exists as a separate API/UI; Campaign is single-objective. `IMPLEMENTED` (separate subsystem), `NOT_STARTED` (Campaign integration) | Connect multiple objectives, uncertainty, feasibility, Pareto batch review, and outcomes to Campaign without collapsing distinct objectives. | P1 | Campaign API, persistence, UI, and review integration tests for two or more objectives. |
| P9-D02 | P4 / constraint-aware and noisy BO backlog | GP/BO constraints and noise-related pieces exist; Campaign constraint and budget handling are limited. `IN_PROGRESS` | Carry validated bounds/units, constraints, run cost/budget, replicates, and stopping rules through a researcher-reviewed recommendation. | P1 | Unit and infeasibility tests plus reproducible persisted recommendation record. |
| P9-D03 | P4/P7 / active learning and simulation discrepancy | Simulation-to-experiment calibration and cost-aware acquisition remain incomplete. `NOT_STARTED` | Track paired simulation and measurement rows with provenance; estimate discrepancy only where paired validated data support it; consider measurement cost explicitly. | P2 | Valid paired data, uncertainty-aware implementation, and calibration/holdout tests. |
| P9-D04 | P7 / complex process and campaign memory requirements | Campaign supports a bounded loop; multi-step process branching and long-horizon memory are incomplete. `IN_PROGRESS` | Preserve process-version/branch boundaries and link each recommendation, execution, analysis, and outcome to exact process and experiment identifiers. | P1 | Multi-step provenance test; no pooling across incompatible process routes by default. |

## P9-E — Scientific Validation

| Phase 9 ID | Original Phase / Requirement ID | Description and current status | Remaining work | Priority | Dependency / completion condition |
|---|---|---|---|---|---|
| P9-E01 | P3/P5/P6/P7 / external validation requirements | No authenticated, independently reviewed laboratory decision corpus is available in the repository. `EXTERNAL_VALIDATION_PENDING` | Evaluate decision correctness, analysis quality, recommendation utility, calibration, abstention, and subgroup/condition shift using reviewed data. | P3 | Approved real dataset and predeclared evaluation protocol; if unavailable, mark `BLOCKED_EXTERNAL_DATA`. |
| P9-E02 | P2/P3 / evidence and instrument-analysis validity | Software-level schema and selected result checks exist; claim entailment and expert-labeled instrument accuracy are not established. `EXTERNAL_VALIDATION_PENDING` | Obtain expert-labeled XRD/AFM/SEM/TEM outputs and paper-to-claim examples; measure errors and provenance fidelity. | P3 | Domain expert labels and independent review; no fabricated reference truth. |
| P9-E03 | P4/P7 / optimization efficacy | Synthetic benchmarks verify optimization code paths only. Laboratory success improvement is unverified. `EXTERNAL_VALIDATION_PENDING` | Compare approved recommendations with observed outcomes under prospective or independently held-out study designs. | P3 | Real study design and researcher-approved execution; predictions stay distinct from measurements. |

## P9-F — Product Hardening

| Phase 9 ID | Original Phase / Requirement ID | Description and current status | Remaining work | Priority | Dependency / completion condition |
|---|---|---|---|---|---|
| P9-F01 | P0/P1 / AUTH-*, SAFE-*, DATA-*, PROV-* | Local pilot has no authenticated identity or multi-user authorization. `IN_PROGRESS` | Before external or multi-user deployment, establish authentication, authorization, topic/lab isolation, audit, secret handling, and approval identity. | P0 | Security review and cross-user access regression suite. |
| P9-F02 | P0 / storage, backup and recovery requirements | Existing local persistence and workflow recovery mechanisms are partial; full operational backup/recovery evidence remains open. `IN_PROGRESS` | Define supported deployment backup/restore, database migration rollback, uploaded-file consistency, and restore drills. | P1 | Tested backup restoration of DB and source files with recorded integrity. |
| P9-F03 | P8 / P8-010 accessibility and P8 UX principles | Phase 8 implements basic semantics and responsive rules; no full WCAG audit or external usability evaluation. `IN_PROGRESS` | Run keyboard/screen-reader/contrast/reflow evaluation and user task study; fix critical barriers. | P2 | Documented scenarios and findings, then verified remediation. |
| P9-F04 | P8 / P8-011 performance and recovery | Workspace uses existing panels/APIs; broad large-data, network-loss, and interrupted-form recovery checks remain open. `IN_PROGRESS` | Profile real slow paths, reduce duplicate fetches, retain recoverable drafts, and validate large record lists on supported devices. | P2 | Reproducible workload-specific before/after measurements and recovery tests. |

## P9-G — Technical Backlog Consolidation

| Phase 9 ID | Original Phase / Requirement ID | Description and current status | Remaining work | Priority | Dependency / completion condition |
|---|---|---|---|---|---|
| P9-G01 | P0–P8 / all existing backlog IDs | Historical detailed backlogs remain in their source documents. This register links them without replacing those records. `IN_PROGRESS` | During each Phase 9 kickoff, reconcile every source backlog row to a P9 ID, preserve original ID/state/evidence, and add newly discovered debt. | P1 | Link coverage reviewed; never delete a completed historical record or reset a completed status. |
| P9-G02 | P0–P8 / tests, CI, migrations and operations | CI and regression suites exist; migration matrix, broad operational stress, and support-platform coverage are limited. `IN_PROGRESS` | Maintain targeted tests per changed workflow; add migration/restore/platform tests where corresponding support is claimed. | P1 | Required test evidence attached to each item; documentation-only status is insufficient. |

## Exit criteria

Phase 9 closes only when every P9 item is `VERIFIED`, a justified alternative is recorded and verified, or the item remains transparently blocked on external data/environment with an explicit owner and dependency. A blocked scientific validation is never reported as a passed validation. Critical security, integrity, approval, or safety defects cannot be waived by external-data limitations.
