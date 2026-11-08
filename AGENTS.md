# TrialFair development instructions

Read README.md, docs/project_context.md, docs/architecture.md and
app/contracts.py before implementation. Respect the user's standing no-email
policy: never transmit or schedule email by any route.

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
