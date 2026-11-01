# Phase 7 Core Implementation

## Status (Phase 7 Official Core Closure)

- `PHASE_7_CORE_IMPLEMENTED`: persistent Campaign invokes the existing Phase 6 decision runtime in explicitly selected Sandbox/Shadow modes, routes compatible saved instrument results through the Registry and Durable Worker, and consumes Worker completion in the backend.
- `PHASE_7_CORE_SMOKE_TESTED`: the Campaign API → data-quality Worker → JEV action → registered XRD result → XRD Worker → GP/EI → researcher review → feedback → next-candidate path passed its integration fixture and the latest local regression, frontend build, browser E2E, and remote CI.
- `PHASE_7_EXTENSION_DEFERRED_TO_PHASE_9`: Research-qualified JEV routing, richer ScientificState, PHREEQC orchestration, multi-objective campaigns, broader tools, and external research-data validation remain explicitly deferred; they are not marked complete.
- `EXTERNAL_SCIENTIFIC_VALIDATION_PENDING`: Branin is a software-only synthetic benchmark; this implementation does not establish scientific validity or improved laboratory outcomes.

## What runs

The new persistent Campaign API and page connect these existing parts:

1. Research goal and target configuration are stored in `experiment_campaigns`.
2. Campaign decision mode is `RULE_BASED`, `JEV_SHADOW`, or isolated `JEV_SANDBOX`. The adapter converts only persisted campaign counters into the Phase 6 ScientificState V2 contract; absent measurement, chemistry, provenance, and evidence remain unknown. `JEV_SHADOW` records the learned prediction while RuleBased retains the action. `JEV_SANDBOX` can route only supported Sandbox actions. Runtime, artifact, schema, prediction, or OOD failures are marked as RuleBased fallback and never labeled as JEV decisions. Research defaults to RuleBased; `JEV_SANDBOX` is rejected for Research.
3. When a non-demo experiment is linked, `experiment.data_quality.v1` is queued through the existing durable `WorkflowRun` / `WorkflowNode` store and executed by the existing Worker. Worker completion invokes the Campaign controller, which validates the result and progresses without an API advance request. When JEV selects `ANALYZE`, only an already stored, compatible XRD/AFM/SEM/TEM run from the linked experiment can be chosen; its registered result is passed through the same Worker and validated. Missing/incompatible input stops for researcher information. PHREEQC simulation action currently stops for explicit simulation inputs and approval; it is not auto-executed by Campaign.
4. GP/Expected Improvement generates one bounded candidate. The persisted candidate includes source IDs/type, uncertainty, model/recommendation IDs, an explicit pending approval state, and a `prediction_is_not_measurement` marker.
5. Candidate approval only enters `WAITING_FOR_RESULT`; it never starts equipment. Reject and revision requests require a new explicit advance.
6. Sandbox uses deterministic Branin observations in a campaign-local table. New synthetic feedback is held pending review and only accepted rows enter that Campaign's next GP fit. No synthetic feedback is written to `ScientificObservation`.
7. Research requires a non-demo experiment plus its Method Version. GP inputs come from the existing `_research_dataset` eligibility policy. Linking a new result accepts only an accepted, normalized `LAB_RESULT` or `ANALYSIS_OUTPUT` from that exact topic, experiment, and Method Version.
8. Append-only, idempotent campaign events retain decision, tool, review, and observation-link history. Pause, resume, cancellation, retrieval, and explicit advance are persisted.

## API and UI

The `/api/campaigns` API provides create/list/get/advance/review/feedback/link/pause/resume/cancel actions. The interface is available in the unified experiment-first workspace and in the legacy **최적화 캠페인** menu. It supports Sandbox and Research configuration, condition bounds, candidate review, and feedback/linking. The Sandbox controls are intentionally fixed to Branin `x1`/`x2` bounds; this protects the documented synthetic fixture from being mistaken for material science.

For Research, variable rows use `id,name,unit,minimum,maximum` and target `id` values must match the normalized observation parameter IDs. Research feedback must first exist as a reviewed observation in the experiment workspace; the UI links its observation ID after campaign approval.

## Verification

The Phase 7 final integration test creates a Campaign, runs the data-quality Worker, applies an explicit JEV prediction fixture to select a previously saved XRD output through the allowlisted Registry, runs the XRD Worker, validates its result, automatically advances to GP/EI, then exercises candidate approval, feedback review, the next candidate, idempotency, and Sandbox/Research separation. The local checkpoint was also invoked directly; its current synthetic-only artifact marked this sparse Campaign state `POTENTIAL_OOD`, so the adapter correctly selected RuleBased fallback. `cd backend && .venv/bin/pytest -q` passed **269 tests**; `cd frontend && npm run build` passed; `cd frontend && npm run test:e2e` passed **6 tests**. Existing deprecation warnings remain. See `backend/tests/test_phase7_campaign_loop.py` and `backend/tests/test_campaign_decision_runtime.py`.

## Phase 9 handoff and limits

- No instrument control, experiment execution, or approval bypass exists.
- Campaign can dynamically route the registered data-quality check and a compatible, previously saved instrument analysis (XRD/AFM/SEM/TEM) through the existing Worker. It does not re-run raw instrument analysis automatically or dynamically execute PHREEQC; the latter still needs its explicit input and human-review workflow.
- The Campaign invokes the actual Phase 6 shared-transformer decision runtime and reuses its local checkpoint/artifact. Current artifact is trained on synthetic Sandbox cases and is explicitly marked synthetically trained/unvalidated; an OOD Campaign state falls back to RuleBased, as observed in the local smoke. This does not validate scientific decision accuracy.
- Research recommendations require at least three distinct eligible accepted records and bounds in the configured variable order. More robust cross-run association of the approved candidate with execution results is needed for multi-step methods.
- Synthetic Branin feedback demonstrates software plumbing only. It is not laboratory data, a material prediction, or evidence that a proposed real experiment will succeed.
- Authentication, multi-user authorization, richer constraints, multi-objective closed-loop optimization, restart/failure stress testing, and external scientific validation are not claimed complete.
- Original Phase 7 IDs and their individual implementation evidence remain in [`MASTER_ROADMAP.md`](MASTER_ROADMAP.md); Phase 9 continuation IDs are in [`PHASE9_MASTER_BACKLOG.md`](PHASE9_MASTER_BACKLOG.md). No original requirement is deleted or promoted by this closure.
