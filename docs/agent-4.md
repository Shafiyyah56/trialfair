# Agent 4 — Trial Improvement Planner

The user explicitly authorises Agent 4 implementation; older deferral statements
in onboarding documents describe the previous scope.

Entry point after agreed contract integration:
`async run_planner(planner_input: PlannerInput, context: ToolContext) -> PlannerReport`.
Own planner implementation, planner tests/examples, usage and handoff. Coordinate
shared interfaces with the integrator through docs/integration.md before edits.

Consume validated snapshots, inspect accepted evidence and existing analyses,
and prioritise concrete research follow-ups for human review. Preserve source
wording, missingness, reported categories, contradictions, applicability limits,
synthetic labels and unavailable analysis status. Search previews are not evidence.
Python checks data prerequisites; the model selects and prioritises bounded actions.
No fresh research, statistical execution, recursive agents, clinical decisions,
patient-specific dosing, automatic experiments, external communication or email.

Reuse the one model adapter, run context, event sink, counters and deadline.
Preserve full assistant responses and opaque continuations; return a result for
every model tool call. Insufficient budget must produce an honest unavailable
result. Keep live checks opt-in. Close owned contexts in finally.

Acceptance covers concrete prioritisation, reference chains and mismatch rejection,
contradictions, zero accepted evidence, unassessed partial investigations, missing
data versus safety, unsupported numerical/clinical assertions, actual analysis
prerequisites, failure/budget/timeout handling and mandatory human review.
Offline tests establish software behaviour, not scientific validity or live readiness.
