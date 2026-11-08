# TrialFair development instructions

Read docs/TEAM_SETUP.md, README.md, docs/project_context.md,
docs/architecture.md, your docs/agent-N.md assignment and app/contracts.py
before implementation. Respect the user's standing no-email
policy: never transmit or schedule email by any route.

## Required startup acknowledgement

Before implementation, explicitly acknowledge the onboarding checklist in your
first response: assigned agent/branch, starting commit, file ownership, shared
interfaces and verified setup or blockers. Record this in your own
`docs/handoffs/agent-N.md` on your feature branch. Do not acknowledge for others.
Merge the latest `origin/main` into your feature branch to obtain uv.lock and
these instructions, preserving existing work. Use `uv sync --locked --extra dev`.
Coordinate shared dependency/contract changes with Agent 2. Agents 1 and 3 reuse
the one ModelClient; Agent 2 owns an early, opt-in live smoke check and records the
actual available model and capabilities. Keep credentials in ignored local .env
files. If access is missing, state the blocker and continue with injected fakes.

## Shared foundation

- Python 3.13; FastAPI, Streamlit, Pydantic v2 and the official google-genai SDK.
- Shared contracts are version 1.0. Coordinate schema changes with the integrator.
- Keep imports free of API calls, credential requirements and filesystem writes.
- This commit is a scaffold. Explicit NotImplementedError/HTTP 501 placeholders
  must not be described as implemented agents or live research.
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
