# Integration coordination

## Baseline ownership

Agent 2's developer is the integrator. They own contracts.py, context.py, config.py,
model_client.py, validation.py, API, orchestration, storage and dashboard.
Other developers propose shared changes here before altering these interfaces.

## Before parallel development

1. Generate uv.lock in a network-enabled environment and commit it to main.
2. Install with uv sync --locked --extra dev and run tests and Ruff.
3. Verify which model and SDK API the temporary account actually supports.
4. Everyone starts from the same main commit and selects their assigned branch.
5. Keep credentials local; never share .env through Git.

Dependency locking could not be completed in the scaffold environment because
external DNS resolution failed. Existing Python 3.13 packages were used for the
contract checks. Full dependency installation and live Gemini execution have not
been verified. Do not describe this as a fully locked or live-tested environment.

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
