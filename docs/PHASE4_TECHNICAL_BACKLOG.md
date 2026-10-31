# Phase 4 — Optional Technical Backlog

**Status:** active, explicitly `NON_BLOCKING` to Phase 5 entry. The rows below retain completed Stage 2/3 IDs as source references; their accepted implementation remains unchanged. No optional extension changes a prior stage's completion criterion.

| Backlog ID / source requirement | Follow-up | Priority | Status | Dependency / completion evidence |
|---|---|---:|---|---|
| `P4-S2-004`, `P4-S2-005` | Spatially varying noise and qNEI / advanced noisy multi-objective acquisition (qNEHVI) | P2 | `NON_BLOCKING` | Research heteroscedasticity dataset; seeded numerical validation against trusted reference implementation |
| `P4-S2-006`, `P4-S3-011` | Unknown/nonlinear and probabilistic constraint modeling; richer multi-objective constraint interface | P2 | `NON_BLOCKING` | Domain-validated constraint data, feasibility calibration, unit and safety review |
| `P4-S2-007`, `P4-S2-010` | Cost-aware and asynchronous optimization with durable background execution | P2 | `NON_BLOCKING` | Runtime/cost observations, cancellation/restart/lease integration and persistence tests |
| `P4-S2-008` | Group k-fold / leave-one-experiment-out and nested validation for tiny datasets | P2 | `NON_BLOCKING` | More independent approved experiments; confidence intervals and leakage tests |
| `P4-S2-009`, `P4-S3-007` | Additional analytical/synthetic benchmarks and repeated platform profiles | P2 | `NON_BLOCKING` | Fixed objective definitions, equal budgets, repeatable seeds and report artifacts |
| `P4-S2-011`, `P4-S3-009` | Relational model/result tables or indexed provenance if JSON persistence no longer meets query needs | P3 | `NON_BLOCKING` | Measured query/storage need and a backup-tested additive migration |
| `P4-S2-012`, `P4-S3-010` | Posterior/constraint-region graphics, accessibility and multi-objective controls refinement | P2 | `NON_BLOCKING` | Usability scenarios and WCAG 2.2 AA checks; integrated Phase 8 design |
| `P4-S3-002`, `P4-S3-005`, `P4-S3-006` | Cross-objective covariance, noisy qNEHVI, asynchronous/non-greedy batch policies | P2 | `NON_BLOCKING` | Research data and validated numerical comparisons; current independent GP / greedy MC-HVI remains supported |
| `P4-S3-003`, `P4-S3-004` | Tolerance-aware dominance and hypervolume numerical robustness for extreme scales | P3 | `NON_BLOCKING` | Adversarial property tests and high-precision reference calculations |
| New `P4-EXT-01` | Mixed continuous/categorical/discrete variables | P2 | `NON_BLOCKING` | Typed variable schema, encoding validation and categorical benchmark |
| New `P4-EXT-02` | Large-scale/sparse GP and measured CPU/RAM optimization | P2 | `NON_BLOCKING` | Actual topic-size profiles on target Mac; compare accuracy, latency and peak memory |
| New `P4-EXT-03` | Model drift / data-distribution monitoring and retraining policy | P2 | `NON_BLOCKING` | Longitudinal accepted datasets and alert/review design |
| New `P4-EXT-04` | More objective counts (3+) and higher-dimensional Pareto visualization | P2 | `NON_BLOCKING` | Benchmarked algorithm choice and usable decision visualization |

Stage 1–3 implementation status and constraints remain documented in [`PHASE4_STAGE2.md`](PHASE4_STAGE2.md), [`PHASE4_STAGE3.md`](PHASE4_STAGE3.md), and [`PHASE4_CORE_COMPLETION.md`](PHASE4_CORE_COMPLETION.md). Optional work may be prioritized later without reopening `PHASE_4_CORE_COMPLETE` unless a genuine data-integrity, approval-bypass, security or scientific-handoff defect is found.
