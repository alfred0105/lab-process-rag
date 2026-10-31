# Phase 5 Technical Backlog

This is a non-blocking backlog outside the fixed Stage 2 acceptance criteria. Items are not implied to be implemented or verified. New safety or data-integrity defects still take priority over phase boundaries.

**Closed Stage 2 integrity defects:** FIX-01 (raw prediction vs. safety-filtered final label) and FIX-02 (Research source eligibility) were corrected, locally verified and passed GitHub Actions in implementation commit `884063bf9dd44f6110958df3799d01f136d15669`; they are closure work within P5-S2-004/005/010, not new backlog criteria. The remaining entries below are future work only.

| ID | Follow-up | Priority | State | Dependency / completion evidence |
|---|---|---:|---|---|
| P5-BL-001 | Collect a sufficiently large, consented, reviewer-authenticated real research decision corpus with time-aligned snapshots and source provenance. | P0 | NOT_STARTED | Identity/role controls and institutional data governance; publish inclusion, exclusion and review-agreement report. |
| P5-BL-002 | Measure expert agreement and adjudicate conflicting labels, multi-reviewer outcomes and label withdrawal. | P1 | NOT_STARTED | P5-BL-001; versioned adjudication policy and disagreement tests. |
| P5-BL-003 | Assess calibration, OOD detection, abstention and risk/coverage on independent, topic/experiment-grouped real data. | P0 | NOT_STARTED | P5-BL-001; held-out external evaluation with uncertainty intervals. |
| P5-BL-004 | Add model/dataset drift monitoring and manual review alerts across model versions. | P1 | NOT_STARTED | Stable opt-in telemetry, privacy controls and a validated drift policy. |
| P5-BL-005 | Evaluate scheduled or event-driven retraining proposals without enabling automatic promotion. | P2 | NOT_STARTED | P5-S2 manual process operational; human-visible dry-run and audit evidence. |
| P5-BL-006 | Research advanced active-learning selection for which state should receive expert labels. | P2 | NOT_STARTED | P5-BL-001; compare label efficiency under group-aware external evaluation. |
| P5-BL-007 | Evaluate stronger OOD and probability-calibration methods against the Stage 1/2 baselines. | P1 | NOT_STARTED | P5-BL-003; include small-data and topic-shift uncertainty. |
| P5-BL-008 | Design a separate authenticated reviewer identity and role/permission integration. | P0 | NOT_STARTED | User/account architecture; historical free-text reviewer names remain unauthenticated. |
| P5-BL-009 | Evaluate Shared Transformer representations and an independent Decision Head. | P2 | NOT_STARTED | Phase 6 kickoff; measure quality, latency and memory on the target M5 24 GB machine. |
| P5-BL-010 | Evaluate any future automated Shadow promotion policy, only as an offline proposal with explicit human authorization. | P3 | NOT_STARTED | External real-data evidence, safety case and rollback drills; no autonomous promotion in Stage 2. |
