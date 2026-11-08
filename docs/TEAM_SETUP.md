# Team setup and coding agent onboarding

Every teammate and their coding agent must read [the handoff](HANDOFF.md) and this
file before implementation.
The repository-root AGENTS.md makes this checklist part of each agent's startup
instructions. Read your assignment and shared contracts as well.

## Acknowledge before starting

In your first response, state your assigned agent, branch, owned files, shared
interfaces and relevant limitations. Use this form, filled with actual observations:

> I have read AGENTS.md, docs/TEAM_SETUP.md, my assignment, and the shared
> architecture/contracts. I am implementing Agent [number] on [branch], starting
> from [commit]. I own [modules]. I will reuse the shared ModelClient, ToolContext
> and contracts, coordinate shared changes with Agent 2, preserve scientific
> provenance, and keep credentials local. Setup status: [verified / blockers].

Record this acknowledgement in your own docs/handoffs/agent-N.md on your feature
branch. Do not acknowledge on behalf of another developer or claim a check passed
without running it. Keep the handoff current as you implement and test your work.

Missing network access or credentials does not prevent work with injected fakes
and synthetic fixtures. State the blocker and continue independent work. Do not
silently replace live execution with replay or request unrelated approvals.

## Repository access and branches

Each teammate needs GitHub access to clone the repository and push their feature
branch. A team member with repository administration rights manages collaborator
access; do not assume access from being able to view a public repository.

Run from a clean checkout. First inspect git status. Preserve any existing work;
never reset, force-push or overwrite another teammate's changes.

```sh
git fetch origin
git switch <your-assigned-branch>
git merge origin/main
# Until Agent 2 is merged into main, also incorporate its shared implementation:
git merge origin/feat/agent-2-safety
```

For a branch only on GitHub, use `git switch --track origin/<branch>` instead.
Resolve genuine conflicts with the affected owner. All three feature branches
must incorporate the dependency-lock commit and these onboarding instructions;
their original scaffold commit alone is insufficient. Main alone also lacks
Agent 2 until that feature branch is merged. See HANDOFF.md for the current path.

| Branch | Owner and assignment | Acknowledgement record |
| --- | --- | --- |
| feat/agent-1-interpreter | Agent 1: docs/agent-1.md | docs/handoffs/agent-1.md |
| feat/agent-2-safety | Agent 2/integrator: docs/agent-2.md | docs/handoffs/agent-2.md |
| feat/agent-3-evidence | Agent 3: docs/agent-3.md | docs/handoffs/agent-3.md |

Work and push on your own branch. The integrator coordinates merges into main.
Do not rewrite a shared branch merely to make it match another branch.

## Reproducible local setup

Use Python 3.13 and the committed uv.lock. Do not regenerate the lockfile simply to
install dependencies. Coordinate dependency changes with the integrator.

```sh
uv sync --locked --extra dev
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Record actual results. The scaffold initially passed 31 tests; Agent 2 now
passed 60 tests; the evidence branch now passes 105. Automated and live checks
are separate evidence. An upstream
TestClient deprecation warning was observed. Do not change shared dependencies or
silence warnings without investigating them and coordinating any needed change.

Create .env from .env.example only if .env does not already exist. Never overwrite
existing credentials. Use the agreed GEMINI_MODEL and your authorised
GEMINI_API_KEY. Do not paste secrets into acknowledgements, logs, Git, prompts or
handoff files. Privately arrange authorised API access with the human team.

No database server, cloud hosting, authentication system or extra agent framework
is needed to start. SQLite and the local FastAPI/Streamlit stack are sufficient.

## Shared model adapter and first live call

Agent 2 owns the single implementation of app/model_client.py. Agents 1 and 3
code against ModelClient and injected fakes until the adapter is ready. Do not
create separate Gemini clients in each agent or choose independent model IDs.

Agent 2 should verify an available model and its SDK/API capabilities with the
actual hackathon account, then make one minimal opt-in live smoke call early.
Record the date, actual model ID, SDK version, checked capabilities and outcome in
docs/handoffs/agent-2.md. Never include keys or fabricate a successful call. A basic
response alone does not verify tool calling or structured-output capabilities;
record which of these were actually exercised. Availability claims from the
supplied event guides are not sufficient verification.

Once verified, communicate the non-secret configuration to the team and record it
in the shared change log below. Keep live and paid calls out of ordinary tests.
No Gemini smoke call is performed by reading these instructions.

## Ownership and integration rules

Agent 2 is the integration owner for contracts.py, context.py, config.py,
model_client.py, validation.py, pyproject.toml, uv.lock, orchestration, storage,
API and UI. Agent 1 owns interpretation, registry, terminology and statistics.
Agent 3 owns external evidence and Europe PMC. See individual assignments.

Propose shared interface/dependency changes in docs/integration.md, agree them
with the integrator and merge them early. Do not duplicate shared interfaces or
make incompatible schemas on separate branches. Functions communicate in process
through Pydantic contracts and ToolContext, not agent-specific HTTP servers.

Agent 1 -> ScreeningOutput -> Agent 2 -> InvestigationReport.
Agent 2 requests AnalysisResult from Agent 1's tools and EvidenceReport from
Agent 3. All accepted outputs become PlannerInput. Agent 4 is deferred.

Statistical calculations remain deterministic Python. Preserve source wording,
source locations, missing values, denominators, uncertainty and contradictory
evidence. Label synthetic/replay data. Do not infer patient-level records or
sex-specific AE rates from baseline demographics. No patient-specific dosing or
automated clinical decisions. Respect the standing no-email policy.

## Shared non-secret readiness log

- Dependency lock: uv.lock committed in dae3c5b.
- Agent implementations: Agents 2/3 and Europe PMC wiring are present on the evidence branch;
  Agent 1 ingestion/statistics/registry are still pending.
- Shared Gemini adapter: live smoke check passed, user-run on 2026-11-08.
- Verified model ID for this account: gemini-4-argon, google-genai 2.34.0, models.generate_content.
- Basic response, function calling and structured output: all true in the user-supplied smoke output.
- Smoke run timestamp: 2026-11-08T03:25:05.097808+00:00. This is not a full clinical workflow test.
- Live Agent 2 UI: observed in Chrome, 34.63 s with live Gemini and synthetic input;
  partial was expected because Agent 3 was not integrated. Real-data pipeline remains unverified.
- Individual acknowledgements: Agents 2/3 acknowledged; Agent 1 updates its own handoff file.

The integrator updates this log as facts change. A pending item must not be marked
complete merely because a teammate was given its assignment.
