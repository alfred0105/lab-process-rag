# Phase 8 — Unified Laboratory UX & Productization

**Status:** `PHASE_8_CORE_IMPLEMENTED` · `PHASE_8_CORE_SMOKE_TESTED`
**Remaining scope:** `PHASE_8_EXTENSION_DEFERRED_TO_PHASE_9`
**Design basis:** [`PHASE8_UX_PRINCIPLES.md`](PHASE8_UX_PRINCIPLES.md)

## Scope delivered

The initial experiment-first workspace reuses the existing topic, experiment, process timeline, analysis, decision, optimization, and Campaign APIs and components. It does not create a duplicate experiment database or a second workflow engine.

- A new default **Unified laboratory workspace / 작업 공간** brings process records, measurement and analysis, AI decision, optimization, and Campaign review into one topic-level workspace.
- One active experiment selector carries the selected experiment into the process timeline, analysis view, decision context, optimization Method Version, and Research Campaign creation.
- Three sequential stages expose the main workflow: **실험·공정 → 측정·분석 → 판단·추천**. Decision, optimization, and campaign views use one nested tab set.
- The context header shows topic, available non-demo run count, process-method count, step count, outcome count, current status, date, process, and recorded results.
- Process conditions are summarized next to the selected experiment in the analysis stage. Existing analysis tools, data review, provenance, BO controls, candidate review, and Campaign history remain implemented by their original components.
- Visible labels distinguish recorded experiment outcomes, computed analysis, and unapproved predictions. Candidate review and explicit approval remain in place.
- Responsive layout rules keep the workspace selector, workflow navigation, and process-condition summary usable at narrow widths. Stage and tool navigation use buttons with keyboard focus inherited from the app's existing controls.
- Existing overview, experiment archive, standalone analysis, simulation, literature, and technical panels remain accessible as legacy/specialist destinations; they are not removed or rewritten.

## Principal smoke scenario

The browser smoke test opens an isolated topic, confirms the workspace and active context, moves through process and measurement/analysis stages, opens AI decision and Campaign review, and verifies that the Campaign form is available. Existing API-level and end-to-end suites continue to exercise the underlying durable workflow and approval paths. This browser smoke does not claim a real research Campaign was run or a scientific recommendation was validated.

## Limits

- The existing `MethodWorkspace` keeps its own process/run selection for detailed timeline interaction; the workspace active experiment preselects that timeline when available. There is no new unified edit form duplicating the underlying process editor.
- Analysis remains topic-synthesis capable and may include other eligible records within the selected topic, as its backend contract specifies. The workspace shows the selected experiment conditions but does not silently change that aggregation scope.
- Existing optimizer constraints and inputs are retained. The workspace selects the active Method Version but does not infer optimization bounds, objectives, or measured values.
- Campaign Research requires explicit objective, variables, bounds, approved data, and researcher review. No device is controlled automatically.
- Local pilot identity is not authenticated. Multi-user access control and lab data isolation are not claimed.
- WCAG 2.2 AA formal evaluation, usability study, large-dataset performance evaluation, persisted interrupted-form recovery across every workflow, and broader responsive-device coverage remain Phase 9 work.
- No real laboratory validation or external user evaluation was performed.

## Verification record

Fill this record from the actual run for the commit that closes the Phase 8 core:

| Check | Result |
|---|---|
| Backend regression | `backend/.venv/bin/pytest -q` — **269 passed**, 408 existing deprecation warnings, 49.77 s |
| Frontend production build | `frontend/npm run build` — passed (Vite 6.4.5) |
| Browser E2E including Phase 8 workspace smoke | `frontend/npm run test:e2e` — **7 passed**, 47.6 s; new workspace test verifies topic context, workflow stages, analysis, and campaign view |
| GitHub Actions | Pending push |
