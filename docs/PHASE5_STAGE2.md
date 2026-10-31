# Phase 5 Stage 2 — Decision Feedback Learning

**Repository:** `alfred0105/lab-process-rag`  
**Stage status:** `PHASE_5_STAGE_2_IMPLEMENTED`
**Phase 5 status:** `IN_PROGRESS`  
**Stage 1:** remains `PHASE_5_STAGE_1_MVP_IMPLEMENTED`; its historical record is retained in [`PHASE5_STAGE1.md`](PHASE5_STAGE1.md).  
**Scope:** the fixed P5-S2-001–012 acceptance list from the Stage 2 implementation request. No Phase 6, automated promotion, autonomous experiment execution or claim of laboratory accuracy is included.

## Design and safety boundaries

Phase 5 remains a shadow recommender. The NumPy Decision Head selects among `REQUEST_INFORMATION`, `ANALYZE`, `SIMULATE`, `OPTIMIZE`, `REQUEST_REVIEW`, and `ABSTAIN`; it does not call a tool, start a workflow, control an instrument, or replace researcher approval. Retraining and model activation are manual operations. Sandbox and Research models, cases, snapshots, datasets, comparisons and active shadow slots are mode-separated.

Reviewer names are self-reported and explicitly marked `SELF_REPORTED_NOT_AUTHENTICATED`. Such records are researcher-reviewed application input, not authenticated expert truth. Synthetic benchmark scores validate software paths only and do not measure real laboratory decision accuracy.

## Implemented data and API flow

1. `/compare` or `/models/{model_id}/predict` evaluates an explicitly identified model. Sandbox models accept stored synthetic cases/snapshots only; Research models require a non-demo experiment, a compatible Research snapshot, or a reviewed Research case. There is no Sandbox fallback for a Research request.
2. Each model decision creates a UUID `DecisionSnapshot` containing state, the exact feature vector and schema version, decision/data-availability timestamps, source row IDs, model/version/mode, probabilities, OOD state, provenance and a deterministic SHA-256 hash. Existing snapshots are read-only through the API. A missing historical decision-time snapshot is not reconstructed from present-day experiment data.
3. `/feedback` appends `ACCEPT`, `CORRECT`, `REJECT` or `UNSURE` revisions. `ACCEPT` labels the suggested action; `CORRECT` requires a different explicit action; `REJECT` is trainable only with an explicit final action; `UNSURE` cannot carry a label. Later revisions supersede earlier labels without deleting history. Sandbox feedback remains synthetic.
4. `/datasets/build` filters by topic, mode, source, review status, snapshot/schema and latest eligible feedback revision. Research datasets reject synthetic cases and demo experiments. Dataset manifests preserve case/snapshot/feedback IDs, feature vectors, groups, source provenance, label distribution, missingness and a frozen group-held-out evaluation set. A new eligible record produces a new hash/version; identical records return the existing immutable version. Frozen evaluation records are copied from the prior immutable manifest so later source-row changes cannot rewrite the test set.
5. `/retrain` is a manual full retrain of the Stage 1 NumPy MLP. It excludes the frozen evaluation groups before fitting and group-splits the remaining cases again for fit/calibration. Model provenance records parent ID, training seed/configuration, dataset and artifact hashes, fit/calibration/evaluation case and group IDs, evaluation hash, metrics, OOD summary and training timestamp. Insufficient independent groups fail closed.
6. `/models/compare` compares two explicit same-topic, same-mode models only when their evaluation case IDs and evaluation hash match and neither model used those evaluation cases for fitting or calibration. It reports `IMPROVED`, `COMPARABLE`, `REGRESSED`, `INSUFFICIENT_EVIDENCE` or `NOT_COMPARABLE`; low sample/group counts are insufficient evidence. Safety regression checks include calibration, abstention and conservative `REQUEST_REVIEW` / `ABSTAIN` class recall.
7. `/activate` changes only the topic/mode Shadow slot. The first evaluated model can be selected explicitly; replacing an active model requires an acceptable comparison against the currently active Champion. `/rollback` restores the previous model. Both append reviewer-attributed, unauthenticated audit events. Neither operation triggers a workflow.

The Stage 1 majority baseline now receives `(training_labels, evaluation_labels)` and selects its class only from training labels. `split_by_group` assigns whole groups and errors when an independent group holdout is impossible.

## Database changes

Alembic revision `0010_decision_feedback_learning` adds nullable decision-case snapshot/feedback links and tables for immutable snapshots, append-only feedback, immutable dataset versions, model comparisons, one active Shadow per topic/mode, and append-only activation/rollback events. SQLite uses a batch table rebuild to add the new decision-case foreign keys while preserving existing rows and indexes. The downgrade is intentionally refused because deleting the audit and learning history would violate the immutability contract; restore a pre-migration backup if a rollback is required.

## API and single-screen UI

The existing learned-decision route remains and gains case/snapshot history, feedback, dataset version listing/building, manual retraining, model-to-model comparison, active Shadow inspection, activation and rollback. The existing `DecisionPanel.tsx` provides one Korean/English flow for source mode, seed fixtures, build/select a dataset, request retraining, inspect label/source/hash/split summaries, run a shadow recommendation, record feedback, compare models, explicitly select a Shadow model and roll back. It displays self-reported identity status and synthetic-data limitations. It does not expose a novice/expert split or start experiments.

## Verification record

The scripted benchmark is [`backend/scripts/benchmark_phase5_stage2.py`](../backend/scripts/benchmark_phase5_stage2.py); its generated report is [`backend/reports/phase5_stage2_learning_cycle.json`](../backend/reports/phase5_stage2_learning_cycle.json). It exercises Dataset V1, model training and reproducible clone, explicit feedback, Dataset V2, group-disjoint retraining, same-frozen-set comparison, explicit Shadow activation and rollback. It asserts that training/comparison do not automatically promote the V2 Challenger.

Current captured benchmark: **PASSED**, synthetic software fixtures only; V1 144 cases, V2 145 cases, and the same evaluation hash across versions. The reproducibility comparison is `COMPARABLE`. V1-vs-V2 is `REGRESSED` under the configured safety gate: macro F1 changed from 0.8418 to 0.8333 (−0.0085), Brier improved from 0.2158 to 0.2096, and ECE improved from 0.0827 to 0.0424, but `ABSTAIN` recall fell by 0.2857 (allowed decrease: 0.10). The active V1 Shadow stays in place; the V2 model was not auto-promoted. Frozen holdout: 36 cases across 36 independent groups; evaluation hash `7f9c21e285c1dc5fc8c9fb4990c18ab2a9e72aab2c82aab26e9fc8a04498e5da`. Full cycle runtime was 0.3725 s on the local test run; this is synthetic software runtime, not a general latency guarantee. This result is not evidence of scientific or laboratory performance.

The implementation commit is `c033612eb5ae43d1910c2c35bc469380c3781b19`. GitHub Actions [run 41190940798](https://github.com/alfred0105/lab-process-rag/actions/runs/41190940798) completed successfully for that SHA: backend **203 passed**, frontend production build passed and browser E2E **5 passed**. Local verification also passed the same backend suite, build and all five E2E cases.

Acceptance status will be updated only after full local and remote verification:

| ID | Requirement | Current state | Evidence / remaining gate |
|---|---|---|---|
| P5-S2-001 | Explicit Sandbox/Research model and inference isolation | VERIFIED | Cross-mode and cross-topic API regression tests plus full backend suite. |
| P5-S2-002 | Training-only Majority baseline and whole-group split | VERIFIED | Different train/evaluation class fixture, deterministic whole-group split tests, updated benchmark. |
| P5-S2-003 | Immutable decision-time snapshots with timestamps, source IDs, schema, hash | VERIFIED | Lifecycle test mutates source case after snapshot and verifies stored hash/state remain fixed. |
| P5-S2-004 | Append-only researcher feedback and eligibility policy | VERIFIED | ACCEPT/CORRECT/REJECT/UNSURE, revision supersession and label eligibility exercised. |
| P5-S2-005 | Immutable versioned dataset builder and provenance | VERIFIED | V1/V2 hashes, counts, latest feedback, source and frozen manifest covered by lifecycle test/benchmark. |
| P5-S2-006 | Group-aware fit/calibration/evaluation and frozen holdout | VERIFIED | Case/group partitions are persisted and disjoint; prior holdout content/hash remains frozen. |
| P5-S2-007 | Manual full retraining, parent lineage and artifact/config versioning | VERIFIED | Lifecycle test and executable synthetic benchmark. |
| P5-S2-008 | Same-evaluation Champion–Challenger gate | VERIFIED | Status, conservative-action recall, sample threshold and leakage guards exercised; V2 regression is surfaced. |
| P5-S2-009 | Explicit Shadow activation and audited rollback | VERIFIED | Initial activation, comparison-gated replacement, rollback and no-workflow assertion exercised. |
| P5-S2-010 | Data integrity, OOD/abstention and approval boundary | VERIFIED | Stage 1 OOD/abstention tests plus Stage 2 mode, latest-feedback and no-workflow tests; external accuracy unavailable. |
| P5-S2-011 | One-screen feedback and learning management UI/API | VERIFIED | Production build and full 5-case browser E2E, including feedback, retraining, comparison, activation and rollback. |
| P5-S2-012 | Learning-cycle report and complete CI/regression | VERIFIED | Local pytest **203 passed**, production build passed, Playwright **5 passed**; GitHub Actions [41190940798](https://github.com/alfred0105/lab-process-rag/actions/runs/41190940798) passed backend, frontend and browser E2E on implementation SHA `c033612eb5ae43d1910c2c35bc469380c3781b19`. |

## Limitations and later work

- No reviewed real research decision corpus was available; Research-mode readiness is expected to remain insufficient on an empty project.
- Reviewer identity is not authenticated. A later identity/role feature must not reinterpret historical self-reported names as verified experts.
- Time-aligned historical state is only guaranteed when the decision snapshot was created at decision time; old unlabeled state is never backfilled as a verified historical snapshot.
- Dataset manifests currently store record vectors and provenance in JSON for immutable reproducibility. Large-scale dataset storage/indexing can be separately evaluated.
- Comparison thresholds and conservative-action recall checks are software safeguards, not clinically/materially validated risk criteria. Metrics on the small synthetic holdout are uncertain.
- The lightweight OOD range test and probability calibration require independent, reviewed research data before scientific use.
- The MLP comparison is synchronous and intended for this small local learner; no scheduled retraining, automatic model promotion, Shared Transformer, instrument connection or real experiment execution is included.

## Phase status

All fixed acceptance items P5-S2-001–012 are `VERIFIED` against code, tests, benchmark, migration, UI integration and CI. Stage 2 is `PHASE_5_STAGE_2_IMPLEMENTED`. Phase 5 remains `IN_PROGRESS`; Phases 6, 7 and 8 remain `NOT_STARTED`. Real research accuracy remains unverified regardless of synthetic software-test success.
