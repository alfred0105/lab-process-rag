# Phase 8 Dark Scientific Workstation Redesign

Date: 2026-11-02
Status: `IMPLEMENTED`; the focused local browser checks and production build passed.
This is an additive UI redesign. The prior Phase 8 core status remains unchanged.

## Implemented

- Replaced the horizontal application navigation with a dark fixed sidebar while retaining access to the existing Overview, experiment, paper, analysis, simulation, benchmark, assistant, optimization, decision, and Campaign destinations.
- Added workstation context controls for research topic, Method, Method Version, and active Run.
- Rebuilt `UnifiedLabWorkspace` around a React Flow process canvas. Its stages come from the selected saved Method Version `process_map`; run values appear only where the Run step matches the version stage by both order and name.
- Added method, run-condition, and measurement-link display layers; pan, zoom, fit view, minimap, keyboard-focusable controls, empty states, and a contextual inspector.
- Inspector tabs show Method condition definitions separately from recorded Run values and materials, source/version identifiers, stage logs, environment readings, partial experiments, stage attachments, step-linked analyses, and run-level analyses without a process step.
- Added same-version Run comparison by default. Cross-version comparison is an explicit selector choice. The frontend sends `comparison_mode` to the existing comparison endpoint and renders the returned same, different, missing, and unresolved variables. It does not calculate scientific equivalence locally.
- Integrated existing Analysis, Decision, Optimization, and Campaign panels through the workstation navigation, preserving their current APIs and review/safety behavior.
- Added responsive dark workstation styles using the requested process, analysis, and recommendation colors. Existing Korean/English switching remains available.

## Existing data and policy preservation

- No database schema or persisted data changed.
- Existing APIs were reused: topic/experiment loading, `GET /api/experiments/{a}/compare/{b}`, analysis runs, Method Version creation in the existing editor, and existing decision/optimization/Campaign panels.
- Comparison remains server-validated. Different versions require explicit cross-version mode; incompatible comparisons are surfaced as an error.
- Synthetic Method/Run fixtures are created only by the isolated Playwright environment. The application does not create fake analysis results.
- Analysis with `process_step_id` is attached only to its recorded Run step. Analyses without a step are labeled at Run level and are not assigned to a process stage.
- Process canvas layout is visual only; method stage order and stored parent-version history remain the source of truth. Arbitrary DAG merge/edit is not implemented because the current data model does not expose it.

## Changed files

- `frontend/src/pages/App.tsx` — persistent sidebar shell and navigation.
- `frontend/src/components/UnifiedLabWorkspace.tsx` — Method/Version/Run state, canvas, comparison, Inspector, and existing panel routing.
- `frontend/src/api/client.ts` — optional explicit comparison mode.
- `frontend/src/style.css` — shared dark theme, canvas, Inspector, and responsive layout.
- `frontend/e2e/run_environment.py` — isolated synthetic process-canvas fixture.
- `frontend/e2e/phase8_unified_workspace.spec.ts` — workspace navigation, saved condition inspection, and server comparison UI coverage.
- `frontend/e2e/b_optimization_sandbox.spec.ts`, `frontend/e2e/workflow.spec.ts` — updated navigation selectors for the sidebar.

## Verification

- `cd frontend && npm run build` — passed.
- `cd frontend && npx playwright test e2e/phase8_unified_workspace.spec.ts e2e/workflow.spec.ts -g "dark workstation|method canvas|Phase 6 shared-transformer" --reporter=list` — **3 passed**.
- The focused canvas E2E confirmed actual isolated API-backed Method/Version/Run values, fetched a same-version comparison, and verified the changed process stage highlight.
- A broader E2E invocation was started but interrupted after legacy optimization tests continued looking for the retired horizontal “기타” menu. Relevant navigation selectors were updated and the affected Phase 6 sidebar route passed; the complete E2E suite has not been rerun after that update.

## Limitations and follow-up

- The focused E2E covers same-version comparison. Cross-version behavior is wired to the existing endpoint and server rules but did not receive a separate browser fixture in this change.
- Measurement comparison remains in the existing Analysis panel; this canvas only indicates step/run linkage and does not fabricate XRD overlays or microscopy metrics.
- Method editing continues to use the existing `MethodWorkspace`/`ProcessTimeline` editor. This UI does not add arbitrary directed graph editing or merge operations.
- Formal WCAG contrast/screen-reader audit, broad viewport review, usability study, and real Research data scientific validation remain open.
- No commit or push was made.
