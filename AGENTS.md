# TrialFair development instructions

Read docs/HANDOFF.md, docs/TEAM_SETUP.md, README.md, docs/project_context.md,
docs/architecture.md, your docs/agent-N.md assignment and app/contracts.py
before implementation. Respect the user's standing no-email
policy: never transmit or schedule email by any route.

## Required startup acknowledgement

Before implementation, explicitly acknowledge the onboarding checklist in your
first response: assigned agent/branch, starting commit, file ownership, shared
interfaces and verified setup or blockers. Record this in your own
`docs/handoffs/agent-N.md` on your feature branch. Do not acknowledge for others.
Follow docs/HANDOFF.md to merge current shared work into your feature branch,
preserving existing work. Until Agent 2 is merged into main, merge
`origin/feat/agent-2-safety` as well as `origin/main`; main alone lacks its adapter. Use `uv sync --locked --extra dev`.
Coordinate shared dependency/contract changes with Agent 2. Agents 1 and 3 reuse
the one ModelClient. Its gemini-4-argon smoke check and live synthetic Agent 2 run
have passed; see the handoff for scope and remaining real-data integration checks. Keep credentials in ignored local .env
files. If access is missing, state the blocker and continue with injected fakes.

## Shared foundation

- Python 3.13; FastAPI, Streamlit, Pydantic v2 and the official google-genai SDK.
- Shared contracts are version 1.0. Coordinate schema changes with the integrator.
- Keep imports free of API calls, credential requirements and filesystem writes.
- On the evidence branch, Agents 2/3 are implemented; Agent 1 is still pending.
  Explicit unavailable adapters/stubs must not be described as live research.
- Do not run paid/network tests by default. Live tests must be opt-in.
- Do not implement the fourth Trial Improvement Planner yet.

## File ownership

- Agent 1: interpreter, registry client, statistics, terminology, interpreter tests.
- Agent 2/integrator: shared contracts, context, config, model adapter, API,
  orchestrator, storage, dashboard, safety and integration tests.
- Agent 3: evidence agent, Europe PMC adapter, evidence tests.
- Propose cross-cutting changes in docs/integration.md; do not create competing
  contracts, provider clients or localhost agent services.

## Scientific requirements

Preserve source wording and locations, reported sex/gender categories, missing
values, participant denominators and uncertainty. Never convert event occurrences
into participant counts or infer sex-specific event rates from baseline sex counts.
LLMs interpret and investigate; Python calculates. Do not invent terminology codes,
source citations, patient-level records, clinical thresholds or safety conclusions.
Label synthetic and replayed data explicitly. Evidence-gap findings are useful
outputs, not errors. Do not give patient-specific treatment or dose recommendations.

## Validation

Run `python -m pytest -q` and, when available, `ruff check .` and `ruff format --check .`.
Run cross-record validation before presenting persisted results. Schema validation
and resolving a source ID do not prove a scientific claim is supported by that source.
