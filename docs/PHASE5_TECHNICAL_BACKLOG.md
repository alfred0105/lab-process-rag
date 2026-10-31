# Phase 5 Technical Backlog

## Stage 4 follow-up — external validity remains open

The software acceptance register for Stage 4 is tracked in [`PHASE5_STAGE4.md`](PHASE5_STAGE4.md). Completion of synthetic diagnostics does not close external validation. The candidate selected in synthetic evaluation remains a benchmark reference only and is not promoted or activated.

| ID | Remaining requirement | Priority | Status | Dependency / closure evidence |
|---|---|---|---|---|
| P5-EXT-009 | Obtain independently reviewed, provenance-complete human decisions from multiple real experiments/topics/methods; preregister group/topic/method splits and evaluate V1/V2/Rule/selected reference without synthetic labels. | P0 | NOT_STARTED | Requires researcher-reviewed data and governance. Report calibration, per-class errors, OOD and abstention with uncertainty; no synthetic benchmark can satisfy it. |
| P5-EXT-010 | Validate OOD and risk thresholds on a held-out reviewed research corpus and distinguish data validity gates from representation shift. | P1 | NOT_STARTED | Depends on P5-EXT-009 and enough independent groups per partition. |
| P5-EXT-011 | Evaluate any future Transformer representation adapter using a versioned contract and fresh reviewed evaluation. | P2 | NOT_STARTED | Phase 6 kickoff; no automatic transfer of V2 weights or embedding semantics. |

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
# Phase 5 Stage 3 follow-up backlog

The Stage 3 software acceptance gate is tracked separately in [`PHASE5_STAGE3.md`](PHASE5_STAGE3.md). These are external validation or optional future capabilities and do not change its fixed 12-item acceptance scope.

| ID | Follow-up | State | Dependency / exit evidence |
|---|---|---|---|
| P5-EXT-001 | Evaluate on independently reviewed, non-demo laboratory decisions | NOT_STARTED | Researcher-approved labels across independent experiments; frozen evaluation protocol |
| P5-EXT-002 | Cross-topic and cross-method generalization | NOT_STARTED | Current benchmark correctly returns `INSUFFICIENT_DATA`; needs multiple independent, source-verified topics and method versions |
| P5-EXT-003 | Validate calibration, selective risk and thresholds on reviewed real decisions | NOT_STARTED | Adequate held-out reviewed examples per action and class |
| P5-EXT-004 | Validate OOD false positives / detection under naturally occurring lab distribution shifts | NOT_STARTED | Prospective or external shift corpus with adjudicated OOD status |
| P5-EXT-005 | Dataset/model drift monitoring and update policy | NOT_STARTED | Deployment data governance and researcher review lifecycle |
| P5-EXT-006 | Advanced domain adaptation / active / continual learning | NOT_STARTED | Evidence that a specific adaptation method improves the fixed research holdout without leakage |
| P5-EXT-007 | Cross-laboratory validation | NOT_STARTED | Independent laboratory data and review protocol |
| P5-EXT-008 | Phase 6 shared Transformer adapter | NOT_STARTED | Separate Phase 6 kickoff; embedding compatibility and retraining must be evaluated, not presumed |

Stage 3's synthetic benchmark is implementation evidence only. It must not be used as a substitute for these external validation datasets.
