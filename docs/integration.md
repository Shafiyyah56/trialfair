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
installation. The user-run live smoke check passed for gemini-4-argon with
google-genai 2.34.0 and models.generate_content: plain response, function calling
and structured output all succeeded. Details are in the team checklist and
Agent 2 handoff. Full multi-agent clinical workflow verification remains pending.

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

## Agent 2 integration changes on feat/agent-2-safety

Implemented against the existing version 1.0 scientific payloads. No dependency
or lock changes were needed. As the assigned integration owner, Agent 2 records
these additive shared changes for the other branches:

- ModelResponse adds optional continuation, an opaque run-local token. Only the
  Gemini adapter resolves it to the original provider content/signatures. Do not
  display it or transfer it between runs/clients.
- Use app.model_client.generate_with_budget(context, messages, tools=...,
  output_schema=...) for model calls in Agents 1 and 3. It consumes model_turn
  once and enforces the remaining deadline. Do not count the same turn again in
  the agent or adapter. The SDK adapter disables automatic calls/retries.
- HealthResponse adds optional components and permits partial/ready status. This
  is health metadata; the scientific cross-agent contracts remain unchanged.
- POST /investigations accepts {screening: ScreeningOutput, mode: live|replay}
  so Agent 2 can run before Agent 1 ingestion is finished. POST /runs still uses
  TrialInput. The default runtime only enables live execution; there is no fake
  or automatically substituted replay model.
- RuntimeServices in app/runtime.py is the explicit composition point for real
  registry, literature and terminology adapters from Agents 1 and 3. Build the
  API with create_app(context_factory=...) and call build_context(...,
  services=RuntimeServices(...)) with those implementations. Missing services
  raise explicit unavailability, never return synthetic production data.
- Agent 1's analyses may describe the actual statistical method in method. Added
  analysis responses must echo request_id and reference registered source IDs.
  The dispatcher rejects unknown datasets, cross-trial data and duplicate IDs.
- Agent 3's responses must echo request_id and preserve sources, contradictory
  evidence and limitations. Agent 2 validates references before retaining them.
  Suggested analyses are returned to Agent 2, not executed recursively.
- The dashboard's optional text entry supplies NarrativeEntry with a deterministic
  upload source ID and locator. Agent 1 must register a matching uploaded_data
  SourceRecord (hashing the original UTF-8 text) before producing TrialBundle.
- SQLite persistence validates both writes and reads. Top-level narrative entries
  and symptom mappings are omitted from saved snapshots. Findings, analysis
  source excerpts and external evidence remain; stored outputs can still be
  sensitive. This is local research storage, not an anonymisation guarantee.

Agent 1 and Agent 3 implementation files are untouched by Agent 2. Their default
stubs still block a fully live trial-to-report run until merged and wired. Health
component flags must be updated by the integrator when that wiring is verified.
