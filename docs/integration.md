# Integration coordination

Read [team setup and acknowledgement instructions](TEAM_SETUP.md). Each coding
agent must acknowledge before implementation and update only its own handoff file.

## Baseline ownership

Agent 2's developer is the integrator. They own contracts.py, context.py, config.py,
model_client.py, validation.py, API, orchestration, storage and dashboard.
Other developers propose shared changes here before altering these interfaces.

## Before parallel development

1. Merge current origin/main into each feature branch, including committed uv.lock.
2. Install with uv sync --locked --extra dev and run tests and Ruff.
3. Verify which model and SDK API the temporary account actually supports.
4. Everyone starts from the same main commit and selects their assigned branch.
5. Keep credentials local; never share .env through Git.

The dependency lock was committed in dae3c5b. The user reported 31 tests passing
in the local locked virtual environment. Each developer must verify their own
installation. Live Gemini execution is still unverified: Agent 2 owns the single
adapter and early opt-in smoke check. Record its actual model/capabilities in the
team checklist and Agent 2 handoff; never record credentials.

## Merge sequence

1. Shared scaffold and verified dependency lock.
2. Agent 1 data/statistics and Agent 3 evidence implementations independently.
3. Agent 2 integration, live adapter, storage and dashboard.
4. Real-input end-to-end checks, latency measurement and failure rehearsal.
5. Agent 4 planning implementation only once PlannerInput is stable.

## Shared change proposals

Add proposals with: owner, affected interfaces, reason, migration, agreement status
and example payload. Keep schema version 1.0 until an agreed compatibility change
requires a new version. Do not leave a proposal as an unexplained breaking edit.

No proposals pending in the initial scaffold.
