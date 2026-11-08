# Agent 2 assignment and integration ownership

Branch: feat/agent-2-safety. Read AGENTS.md and shared architecture first.
Own shared contracts/context/config/model adapter and safety orchestration, API,
storage and dashboard. Coordinate contract changes before other branches depend
on them. Maintain the committed uv.lock and coordinate dependency changes with the team.

Before implementation, read docs/TEAM_SETUP.md, acknowledge it in your first
response and update docs/handoffs/agent-2.md on your feature branch. Merge current
origin/main, install the committed lock with uv sync --locked --extra dev, and
record actual checks and blockers. Reuse the shared model adapter and contracts.

## Safety agent

Implement run_safety(ScreeningOutput, ToolContext) -> InvestigationReport.
Select findings, form explicitly labelled hypotheses, request valid further
analyses and external evidence, inspect results, revise conclusions and stop.

Approved tools: inspect_finding, inspect_analysis, request_analysis and
request_evidence. Validate all tool arguments and IDs; never execute arbitrary code.
Requests go through injected handlers, not localhost services.

Useful loops include confirming missing subgroup data and checking an associated
publication, or investigating a numerical signal then weakening an exposure
hypothesis after finding formulation-mismatched or contradictory evidence.
Do not force a positive signal. Separate observed association, uncertainty,
confounding, mechanism and causality. Exposure/target engagement need evidence.
Do not recommend doses or decide phase progression.

## Integration

Implement the single google-genai ModelClient adapter after verifying the actual
account/model/API. Keep the model configurable. Validate structured outputs and
use supported function calling. Split final structured extraction if necessary.

Implement run_trial: interpreter -> safety -> bounded evidence/analysis requests
-> merge accepted analyses -> validate results -> assemble PlannerInput. Keep every
EvidenceReport, including partial/unavailable outcomes. Agent 3 suggests analysis;
Agent 2 decides. Enforce the shared budget, deadline and actual network timeouts.

Implement POST /runs and GET /runs/{run_id}, SQLite RunStore and the Streamlit UI.
Synchronous bounded execution is sufficient. Preserve partial results on failure.

UI: trial input, optional narrative, actual live/replay mode/model, availability,
representation, valid comparisons, prioritised findings, contradictory/supporting
sources, short tool activity timeline, limitations, follow-up questions and JSON
export including PlannerInput. Never show fake live progress or fake planner output.

## Validation and handoff

Test valid tool selection, hypothesis revision, rejected fake citations/tools,
missing evidence, service failures, cumulative budgets, API validation, storage
and the end-to-end pipeline with injected fakes. Add opt-in live smoke checks.
Run cross-record validation before persistence/display. Measure actual demo latency.
Document which dependencies/live paths were verified. Agent 4 remains deferred.
