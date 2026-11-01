# Phase 9 Scope

**Official name:** Phase 9 — System Integration, Advanced Optimization & Scientific Validation
**Status:** `REGISTERED_NOT_STARTED`
**Registration date:** 2026-11-01
**Source backlog:** [`PHASE9_MASTER_BACKLOG.md`](PHASE9_MASTER_BACKLOG.md)

## Purpose

Phase 9 handles expanded integration, advanced optimization, actual scientific validation, runtime and product hardening left after the core implementations in Phases 0–8. It begins only after the Phase 8 core is completed and accepted. This document is a scope registration, not a claim that Phase 9 implementation has started.

## Included work

1. **P9-A — AI Decision & Model Integration:** real Campaign state contract, training/decision data from reviewed research, calibrated and safe JEV action routing, fallback and model lifecycle.
2. **P9-B — Transformer & Runtime Optimization:** validated early exit, quantized inference, runtime comparison, memory/latency/power/thermal measurement on supported local hardware.
3. **P9-C — Advanced Scientific Tool Orchestration:** PHREEQC handoff, additional registry tools, typed multi-tool workflows, recovery, long-running Campaign behavior.
4. **P9-D — Advanced Experiment Optimization:** multi-objective Campaigns, constraints, experiment cost/budget, simulation discrepancy, process-branch-aware recommendations and longer campaign history.
5. **P9-E — Scientific Validation:** instrument-analysis accuracy, paper evidence quality, scientific decision validity, and prospective/independent recommendation evaluation on reviewed real data.
6. **P9-F — Product Hardening:** authentication/authorization, lab/topic isolation, backup/restore, security, formal accessibility and usability studies, measured performance and data recovery.
7. **P9-G — Technical Backlog Consolidation:** map every Phase 0–8 backlog ID to a Phase 9 continuation ID while preserving original wording, status, evidence, and historical commits.

## Explicit non-goals at registration

- No Phase 9 feature implementation begins in the Phase 8 closure task.
- No new AI model or optimization algorithm is trained or promoted as part of backlog registration.
- No claim of laboratory accuracy is derived from synthetic benchmark or browser smoke tests.
- No externally collected data, unreviewed sources, or demo values are relabeled as measurements.
- No actual instrument control or execution without existing approval and safety gates.

## Priority and gates

- **P0:** Critical security, data integrity, provenance, safety, and approval bypass issues. Any discovered issue is fixed immediately.
- **P1:** Core existing feature integration and completion.
- **P2:** Measured optimization, accessibility, usability, and technical debt.
- **P3:** External scientific validation requiring reviewed laboratory data, expert labels, or approved environments.

Each Phase 9 work item must declare the source requirement ID, current status, code evidence, dependencies, required external data/environment, and executable completion check before implementation. Missing external evidence is `BLOCKED_EXTERNAL_DATA` or `EXTERNAL_VALIDATION_PENDING`, not `VERIFIED`.

## Phase 9 commencement condition

Phase 8 must have its core workspace and principal user flow implemented and smoke-tested, with extensions explicitly transferred here. A later Phase 9 kickoff must select the highest-priority unblocked items, review the entire backlog, and preserve all source IDs and evidence. No automatic assumption promotes any model or opens Research routing.
