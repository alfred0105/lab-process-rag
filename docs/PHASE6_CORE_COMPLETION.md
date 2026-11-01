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
- Browser E2E: `6 passed` locally (46.4 s) and in GitHub Actions.
- GitHub Actions: [run 41263699260](https://github.com/alfred0105/lab-process-rag/actions/runs/41263699260), implementation commit `189fbf0235e78c655e6e9af10d49f803d9a3edfa`; backend, frontend and browser E2E jobs passed.
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


## Early Exit research update — 2026-11-01

Expanded synthetic experiment: 480/1,920/3,840 cases, six disjoint partitions at N=3,840, class-balanced/effective-number/fusion/MLP/distillation head candidates, five routers, family-held-out diagnostic and OOD rejection. PABEE was selected for certification; 377/384 synthetic certificate cases exited, 46 errors, Wilson upper 0.1589 and exact upper 0.1533, meeting the software experiment's 0.20 threshold. On frozen synthetic data, offline mean depth was 15.42/28 and macro F1 0.8446 versus full-depth 0.8487. This statistical result does not authorize research use: all targets came from generated synthetic rule contracts, no reviewed laboratory labels exist, and no adaptive decoder loop was timed.

Actual local Qwen3-0.6B revision `c1899de289a04d12100db370d81485cdf75e47ca` full-depth benchmark: MPS FP16, 471 input tokens, 3 warmups, 30 synchronized repetitions, hooks verified 28/28 layers each time, latest batch p50 84.69ms and p95 96.54ms (three batches ranged 84.69–120.89ms p50 and 91.46–145.16ms p95). Adaptive p50/p95 and actual layer skipping remain unmeasured. Phase 6 stays `IN_PROGRESS`, Phase 7 `NOT_STARTED`; the roadmap retains COMBO-A~E integration, real data validation and adaptive runtime proof as open requirements.


## Final regression and CI record for Early Exit research — 2026-11-01

Local regression after the import fix: backend **253 passed** (357 pre-existing/dependency warnings), frontend production build passed, browser E2E **6 passed**. Latest GitHub Actions for commit `14b62922928dec5d7867216f6b0fb1dd0ef3c4f8`: [run 41267630400](https://github.com/alfred0105/lab-process-rag/actions/runs/41267630400) passed backend, frontend and browser-e2e jobs. The first CI run exposed an optional PyTorch import at module load; commit `14b6292` moved it into the research-run entry point, and the following CI run passed.

## Minimal Adaptive Early Exit Runtime — 2026-11-01

The sandbox runtime now rehydrates Candidate A (PABEE) and Candidate C (Fusion + EEFP) from a locally generated, contract-checked tensor artifact and runs the existing pinned Qwen3-0.6B checkpoint. On 30 balanced frozen synthetic inputs, token IDs matched 30/30; hidden states matched exactly at layers 7/14/21/28; probability maximum error was below `9e-7` against a `2e-4` tolerance; actions and exit layers matched offline routing 30/30 for each candidate. Forward hooks confirmed each adaptive call count matched its exit layer and the full-depth path called all 28 layers.

Synchronized MPS FP16 p50/p95: Full `85.25/87.63 ms`; A `45.38/68.34 ms` (1.88× p50); C `26.97/40.41 ms` (3.16× p50). Candidate C preserved full-depth macro F1 (`0.8283`), matched full-depth actions on 30/30, and had zero OOD early-exit violations and zero unsafe `OPTIMIZE` false positives in this diagnostic slice. It is selected only for the isolated sandbox comparison. No runtime router was added to Research API, no workflow ran, and this sample is not a new certificate or scientific validation.

Artifacts: `backend/reports/phase6_ee_runtime_parity.json`, `phase6_ee_actual_runtime.json`, `phase6_ee_runtime_selection.json`. Full regression and CI for this commit are tracked in the latest repository checks after push. Phase 6 remains `IN_PROGRESS`; Phase 7 remains `NOT_STARTED`; external scientific validation remains pending.
