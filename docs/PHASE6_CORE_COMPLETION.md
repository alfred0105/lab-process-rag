# Phase 6 Core Completion Review — 2026-11-01

## Decision

**Phase 6 remains `IN_PROGRESS`; do not declare `PHASE_6_CORE_IMPLEMENTED`.** The local Research boundary and structured-output software path are materially improved and exercised with the pinned Qwen3-0.6B checkpoint. The calibrated early-exit acceptance gate is not met. No Phase 7 work was started.

This document separates verified software behavior from scientific validity. All newly generated training and integration cases are synthetic software fixtures. No human-reviewed laboratory decision dataset or paper-claim entailment review was available.

## Closure gates

| Gate | Status | Evidence | Remaining condition |
|---|---|---|---|
| CLOSE-P6-001 Local Research access | `VERIFIED_LOCAL_SINGLE_USER_ONLY` | LaunchAgent and observed Uvicorn listener use `127.0.0.1:8000`; request peer is checked as loopback; direct unit/API tests reject remote peers and reject multi-user mode without auth. CORS remains exact localhost dev origin. | Add real user identity and topic authorization before any multi-user deployment. Do not expose through a proxy or LAN. |
| CLOSE-P6-002 Structured explanation | `VERIFIED_SOFTWARE_FIXTURE_PATH; SCIENTIFIC_VALIDITY_OPEN` | Real pinned Qwen checkpoint; JSON Schema token constraint; exact action lock and citation allowlist; 4/5 scenario outputs accepted; explicit conflicting-action injection rejected; no-evidence generation skipped; cache/no-cache output sequence identical. | Evaluate on real curated paper claims and reviewed lab decisions; citation identity does not prove semantic entailment. |
| CLOSE-P6-003 Calibrated early exit | `PARTIAL` | 480 group-disjoint synthetic rows; Linear/MLP/regularized MLP × seven layers; separate fit/calibration/controller/frozen groups. All sequential controllers failed the prespecified Wilson upper risk ≤0.20 with ≥24 exits. | Obtain reviewed independent labels, refit/recalibrate; only then run actual candidate layer-hook and latency benchmarks. |

## Local verification performed

- Backend: `248 passed`; 357 warnings, predominantly existing SQLAlchemy `datetime.utcnow()` deprecations plus dependency deprecations.
- Frontend production build: passed (TypeScript + Vite, 1,760 modules).
- Browser E2E: see final verification report for current run result.
- Actual checkpoint integration: see `backend/reports/phase6_generation_validation.json`; synthetic DB/PDF fixtures only; workflow trigger remained false.
- Full early-exit metrics: `backend/reports/phase6_early_exit_diagnostics.json` and `backend/reports/phase6_early_exit_final.json`.
- Access boundary evidence: `backend/reports/phase6_access_security.json`.
- Structured generation evidence: `backend/reports/phase6_structured_generation.json`.

## Early-exit findings

Synthetic label counts were imbalanced (REQUEST_REVIEW: 210/480). Controller coverage/error counts were Linear 20/1 (Wilson upper 0.236), MLP 18/2 (0.328), and regularized MLP 16/2 (0.360). All exceeded the risk ceiling; the linear candidate also failed the minimum 24 accepted exits. No threshold was loosened. Therefore the diagnostic/frozen router authorized 0 early exits, ran all 28 layers, and achieved 0% compute reduction. Candidate latency was not measured because no policy was eligible. Historical forced-threshold layer-hook evidence is structural only, not a safe operating result.

## Generation findings and limits

The model was Qwen/Qwen3-0.6B at pinned revision `c1899de289a04d12100db370d81485cdf75e47ca`, running MPS FP16 on the local M5. Token-level JSON Schema constraints came from `lm-format-enforcer==0.11.3` through Transformers `prefix_allowed_tokens_fn`. Accepted outputs were checked for exact schema, final action, and server allowlisted citation ID. The explicit alternate-action conflict guard rejected the malicious fixture output. Citation and action checking do not prove that an evidence excerpt entails the explanation. All fixture evidence is synthetic and no scientific claim accuracy is asserted.

With and without KV reuse, the same tested prompt produced the same 82-token sequence. One local run measured about 2.31 s cached and 13.73 s uncached; this is a single comparison, not a stable latency benchmark.

## Access boundary

`LOCAL_SINGLE_USER` is intended only for a loopback-bound process. `AUTHENTICATED_MULTI_USER` rejects Research access with `AUTHENTICATION_REQUIRED` because this repository does not currently authenticate users or authorize topics per user. A topic ID or a loopback check is not a substitute for multi-user authorization. No external penetration test was performed.

## Status of P6-001–012

The detailed register remains in `docs/MASTER_ROADMAP.md`. No blanket promotion is made. The shared checkpoint, canonical context, synthetic head training/artifact, deterministic decision-only path, provenance gates, and existing interfaces retain their previously documented implementation/verification statuses. P6-006 is still partial because scientific grounding is unverified; P6-007 is partial because no calibrated safe exit exists; P6-008 remains partial despite cache token equivalence because end-to-end evidence-backed user explanation remains unverified; P6-010/011 remain partial pending broader and repeatable performance evidence. Research accuracy, claim entailment, authenticated multi-user operation, and scientific early-exit safety remain unverified.

## Release controls

- Decision outputs remain shadow-only.
- No workflow execution or automatic promotion is enabled.
- No synthetic head is promoted to production.
- Phase 7 remains `NOT_STARTED`.
- Phase 8 remains `NOT_STARTED`.
