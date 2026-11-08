# TrialFair

TrialFair helps pharmaceutical safety researchers investigate potential
sex-specific safety signals and missing subgroup evidence in completed clinical
trials, particularly before the next trial phase.

**Current status on feat/service-integration:** Agents 1–3 are merged and connected:
trial ingestion/statistics, safety investigation, ClinicalTrials.gov and Europe PMC.
The API, storage and dashboard use the shared model and budget. The complete path
has an offline integration check. The first combined live run timed out; revised
time allocation awaits a live retest. See [the audit](docs/verification/pipeline-live.md).
Agent 4 supports independent snapshot planning on `feat/agent-4-planner`; see
[planner usage](docs/agent-4-usage.md). Default pipeline scheduling remains pending. Agent 2's live Gemini/synthetic demonstration passed. Agent 3's live
research returned two audited items with partial status; see the
[live-check scope and limitations](docs/verification/agent-3-live.md).
See [Agent 3 usage](docs/agent-3-usage.md) and [Agent 2 usage](docs/agent-2-usage.md).
See [service integration and live verification](docs/service-integration.md).

## Start here for teammates and coding agents

Start with [the coding agent handoff](docs/HANDOFF.md), then read
[team setup and acknowledgement instructions](docs/TEAM_SETUP.md) before
implementation. Every coding agent must acknowledge its assignment, branch,
ownership and shared interfaces in its first response and record the acknowledgement
in its own `docs/handoffs/agent-N.md`. Do not mark another agent as acknowledged.

## Stack

Python 3.13, FastAPI, Streamlit, Pydantic v2, pandas, NumPy, SciPy, statsmodels,
httpx, SQLite and the official Google GenAI SDK. Model choice is configurable;
verify availability and SDK capabilities with the provided hackathon account.

## Setup

Install Python 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```sh
uv sync --locked --extra dev
# Create .env only if it does not already exist:
cp -n .env.example .env
```

Set `GEMINI_API_KEY` and `GEMINI_MODEL` only in the ignored `.env` when implementing
and testing live calls. Neither is required for contract tests or the scaffold API.
Do not commit keys, uploaded narratives or runtime caches.

**Dependency lock status:** `uv.lock` is committed. Use the locked install above;
coordinate dependency/lock changes with the integrator. The user reported 31 tests
passing in the local virtual environment; the Agent 2 implementation later passed
60 tests. A user-run live smoke check also passed; see the team readiness log.

## Verify the foundation

```sh
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

If the contract-test dependencies are already installed, `python3 -m pytest -q`
works without installing the full runtime. Live tests are excluded by default;
future opt-in live tests run with `uv run pytest -m live` and require credentials.

Start the API:

```sh
uv run uvicorn app.api:app --reload
```

`GET /health` reports partial pipeline readiness. `/docs` exposes the agreed API
shapes. `POST /investigations` accepts a prepared ScreeningOutput for independent
Agent 2 execution. Missing live configuration returns 503, invalid inputs 422,
and unknown stored run IDs 404. `POST /runs` accepts a completed trial identifier
and invokes all three agents with real source adapters. Health component flags
describe installed implementations, not validated credentials or source uptime;
overall health stays partial because Agent 4 is not scheduled in the default pipeline.

The dashboard uses `POST /runs/async` or `POST /investigations/async`, then polls
`GET /runs/{run_id}/progress` for sanitized agent events and completed stage outputs.
The original synchronous endpoints remain available. Active progress is local to
the API process; completed validated runs are persisted in SQLite.

Start the dashboard in a second terminal:

```sh
uv run streamlit run app/ui/dashboard.py
```

## Parallel branches

All developers must start from the same shared-foundation commit on `main`.
Each developer creates/selects only their assigned branch. While Agent 2 remains
unmerged into main, also merge origin/feat/agent-2-safety into that branch using
the instructions in docs/HANDOFF.md; main alone lacks the shared implementation:

```sh
git switch main
git pull --ff-only
# Choose one:
git switch -c feat/agent-1-interpreter
git switch -c feat/agent-2-safety
git switch -c feat/agent-3-evidence
```

If the branch already exists locally, use `git switch <branch>` instead. If it is
already on GitHub, use `git switch --track origin/<branch>` after `git fetch`.

| Branch | Responsibility | Assignment |
| --- | --- | --- |
| `feat/agent-1-interpreter` | Natural-language interpretation, registry parsing, Python statistics | [Agent 1](docs/agent-1.md) |
| `feat/agent-2-safety` | Safety investigation, shared Gemini adapter, orchestration, API and dashboard | [Agent 2](docs/agent-2.md) |
| `feat/agent-3-evidence` | Adaptive literature and related-trial investigation | [Agent 3](docs/agent-3.md) |

The Agent 2 developer is the integrator and owns shared files. Coordinate changes
in [integration notes](docs/integration.md) before changing a contract. Merge shared
changes early so the other branches can update. Do not merge competing interfaces
at the end of the hackathon.

## Shared contracts and examples

[Contracts](app/contracts.py) define all agent inputs and outputs.
[ToolContext](app/context.py) provides injected dependencies and a single cumulative
budget/deadline. [Validation](app/validation.py) checks cross-agent IDs and synthetic
labels. [Fixtures](fixtures/README.md) let developers build without the other agents.

Pipeline:

```text
TrialInput -> Agent 1 -> ScreeningOutput -> Agent 2 -> InvestigationReport
                                             |        ^
                                             v        |
                                         Agent 3: EvidenceReport
                                             |
                       validated outputs -> PlannerInput -> independent Agent 4 (optional caller)
```

Agent 2 can also request allowlisted statistical analyses through Agent 1's tools.
Additional accepted analyses must be appended to ScreeningOutput before building
PlannerInput. Agents call Python functions in process; only the dashboard uses HTTP.

Read [project context](docs/project_context.md), [architecture](docs/architecture.md)
and [data sources](docs/data_sources.md) before implementation.
