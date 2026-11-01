# Phase 7 Core Implementation

## Status

- `PHASE_7_CORE_IMPLEMENTED`: implemented for the single-campaign core path.
- `PHASE_7_CORE_SMOKE_TESTED`: verified. The campaign integration test, full backend suite, and frontend production build pass on this commit.
- `PHASE_7_EXTENSION_PENDING`: multi-objective campaigns, additional campaign tool types, richer Research feedback entry, and trained JEV campaign routing remain future work.
- `EXTERNAL_SCIENTIFIC_VALIDATION_PENDING`: Branin is a software-only synthetic benchmark; this implementation does not establish scientific validity or improved laboratory outcomes.

## What runs

The new persistent Campaign API and page connect these existing parts:

1. Research goal and target configuration are stored in `experiment_campaigns`.
2. A compact typed campaign state is converted to the existing decision feature contract. The current campaign router uses the existing safe `RuleBasedDecisionPolicy` for the initial read-only data-quality action and a deterministic route to GP optimization after validation. The campaign path does **not** claim to run a trained JEV model; Phase 5/6 learned runtime activation is not required for this loop and remains a follow-up integration.
3. When a non-demo experiment is linked, `experiment.data_quality.v1` is queued through the existing durable `WorkflowRun` / `WorkflowNode` store and executed by the existing Worker. Results are checked with `ResultValidator` before the controller advances.
4. GP/Expected Improvement generates one bounded candidate. The persisted candidate includes source IDs/type, uncertainty, model/recommendation IDs, an explicit pending approval state, and a `prediction_is_not_measurement` marker.
5. Candidate approval only enters `WAITING_FOR_RESULT`; it never starts equipment. Reject and revision requests require a new explicit advance.
6. Sandbox uses deterministic Branin observations in a campaign-local table. New synthetic feedback is held pending review and only accepted rows enter that Campaign's next GP fit. No synthetic feedback is written to `ScientificObservation`.
7. Research requires a non-demo experiment plus its Method Version. GP inputs come from the existing `_research_dataset` eligibility policy. Linking a new result accepts only an accepted, normalized `LAB_RESULT` or `ANALYSIS_OUTPUT` from that exact topic, experiment, and Method Version.
8. Append-only, idempotent campaign events retain decision, tool, review, and observation-link history. Pause, resume, cancellation, retrieval, and explicit advance are persisted.

## API and UI

The `/api/campaigns` API provides create/list/get/advance/review/feedback/link/pause/resume/cancel actions. The app exposes the minimal interface through the **최적화 캠페인** tab in **기타**. It supports Sandbox and Research configuration, condition bounds, candidate review, and feedback/linking. The Sandbox controls are intentionally fixed to Branin `x1`/`x2` bounds; this protects the documented synthetic fixture from being mistaken for material science.

For Research, variable rows use `id,name,unit,minimum,maximum` and target `id` values must match the normalized observation parameter IDs. Research feedback must first exist as a reviewed observation in the experiment workspace; the UI links its observation ID after campaign approval.

## Verification

The integration test creates a Campaign, queues and runs the real local data-quality Worker, validates the result, fits GP/BO, creates a pending candidate, approves it, submits and reviews Sandbox feedback, advances to the next candidate, and checks idempotency and source separation. `cd backend && .venv/bin/pytest -q` passed **264 tests**; `cd frontend && npm run build` passed. Existing deprecation warnings remain. See `backend/tests/test_phase7_campaign_loop.py`.

## Limits and next work

- No instrument control, experiment execution, or approval bypass exists.
- The current actual analysis step is read-only experiment-record data quality. Instrument analysis and simulations remain available through their existing workflows but are not dynamically chained by Campaign yet.
- The learned JEV/COMBO-C model is not invoked by the Campaign path; the recorded feature vector and decision-policy adapter boundary are present, with the safe rule policy used today.
- Research recommendations require at least three distinct eligible accepted records and bounds in the configured variable order. More robust cross-run association of the approved candidate with execution results is needed for multi-step methods.
- Synthetic Branin feedback demonstrates software plumbing only. It is not laboratory data, a material prediction, or evidence that a proposed real experiment will succeed.
- Authentication, multi-user authorization, richer constraints, multi-objective closed-loop optimization, restart/failure stress testing, and external scientific validation are not claimed complete.
