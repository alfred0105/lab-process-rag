# Phase 8 — Unified Laboratory UX & Productization

**Status:** `PHASE_8_CORE_IMPLEMENTED` · `PHASE_8_CORE_SMOKE_TESTED` (core workspace; see [`PHASE8_CORE_IMPLEMENTATION.md`](PHASE8_CORE_IMPLEMENTATION.md))
**Official name:** Phase 8 — Unified Laboratory UX & Productization

## Goal

Enable a new laboratory researcher to register an experiment, enter process and measurement data, analyze results, and review next-condition suggestions in one understandable workspace without separate product modes or a dedicated program course.

## Fixed principles

1. **One interface:** no beginner/expert mode switch and no separate feature sets based on skill level. Progressive disclosure is allowed within the same screen.
2. **Experiment-first navigation:** show research topics, experiment records, process conditions, measurement data, analysis, optimization and next-step recommendations. Explain GP, BO, JEV and DAG in context rather than using jargon as the only label.
3. **Progressive disclosure:** put common work in view; reveal advanced settings as needed without silently dropping safety-critical constraints.
4. **Contextual guidance:** label meaning, units, permitted ranges, short explanation, examples, error cause and recovery action appear where users enter data.
5. **Continuous research workflow:** topic → process conditions → run/result registration → analysis → AI comparison → next condition suggestion → researcher review, with redundant re-entry minimized.
6. **Scientific transparency:** preserve and distinguish raw measurement, computed output, prediction and uncertainty, model/data version, provenance, acceptance, analysis tool, calculation history and reviewer state. Predictions are never rendered as measurements.
7. **Accessibility target:** WCAG 2.2 AA; keyboard use, screen-reader semantics, adequate contrast, non-color cues, accessible names and labels, helpful errors, responsive layout and safe recovery.
8. **Performance and recovery:** manage rerenders, large run sets and chart cost; avoid duplicate API requests; retain input on failure; show loading/empty/error/long-job states and recoverable actions.

## Completion gates

- A new researcher can complete the principal research workflow in the same interface.
- Defined usability, accessibility and performance scenarios pass measurable, task-specific acceptance criteria. Those metrics and scenarios must be agreed at Phase 8 kickoff; this registration does not invent thresholds.
- End-to-end tests cover real research-work scenarios and user testing shows the principal flow can be completed reliably.

Phase 8 is not implemented by this registration. Phase 5–7 may build their minimum necessary UI but should follow these principles. Full product-wide redesign remains in Phase 8.
