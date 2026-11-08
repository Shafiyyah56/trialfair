# Run and verify the Agent 2 workspace

Agent 2 implements the Safety Investigator, Gemini SDK adapter, bounded
orchestration, SQLite persistence, FastAPI routes and Streamlit dashboard. It
supports independent investigation of a prepared Agent 1 ScreeningOutput JSON.
Agent 4 is not implemented. Agents 1 and 3 are separate branch dependencies.

## Install and check

```sh
uv sync --locked --extra dev
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Automated tests use injected model and source services. They do not validate a
real clinical conclusion or an available live model. The synthetic fixtures are
interface examples and remain labelled. The upstream TestClient deprecation
warning is not suppressed and no dependency changes were made to address it.

## Configure and verify Gemini

Set GEMINI_API_KEY and GEMINI_MODEL in your ignored .env. Use the actual available
model ID for the hackathon account; no model is selected automatically. The adapter
uses the installed official SDK's models.generate_content API with manual function
calling, separate JSON output and no hidden retries. A configured model must support
that API. No guide-provided model name is assumed to work.

One opt-in check exercises a plain response, local ping tool selection, provider
continuation and structured output, using at most three model requests:

```sh
uv run --locked python scripts/smoke_gemini.py --live
```

This can incur model charges. Ordinary tests do not run it. The output reports
non-secret model/SDK/date/capabilities only. Record a successful actual check in
the Agent 2 handoff and team readiness log. Failed checks never trigger model
substitution or simulated results.

Provider state handling follows the official SDK and function-calling references:
https://github.com/googleapis/python-genai
https://ai.google.dev/gemini-api/docs/function-calling
Opaque provider content stays in run-local memory so tool-turn signatures are
preserved. Private thought text is not emitted into events or reports.

## Launch locally

Run in one terminal:

```sh
uv run --locked uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Run in another:

```sh
uv run --locked streamlit run app/ui/dashboard.py
```

Open http://localhost:8501. This is a local development application; public hosting
and account management are outside this task. The API reference is at
http://127.0.0.1:8000/docs.

- Prepared screening JSON: select an actual ScreeningOutput from Agent 1 or the
  explicitly synthetic fixtures/synthetic/screening.json. Executing it calls the
  live configured model. A simulated input does not become a real clinical result.
- Completed trial: accepts an NCT ID and optional symptom descriptions; requires
  Agent 1's implementation and real service composition. It is not fully wired yet.
- Review saved run: upload RunResult JSON or enter a stored run ID. This only
  displays a saved result; it does not pretend to call a model. The original
  fixtures/synthetic/run_result.json is a zero-execution interface example.

The UI displays data availability, prioritised findings, original deterministic
analysis outputs (including denominators), hypotheses, contradictory evidence,
source links/licences, recorded activity, limitations and a downloadable JSON
snapshot including PlannerInput when available. There are no invented planner
recommendations or fake live progress events.

## API and composition

- GET /health: Agent 2 available; full agent pipeline still partial.
- POST /runs: TrialInput -> run_trial. Missing Agent 1 remains an explicit failed
  run, not fake data. Missing credentials return HTTP 503 before execution.
- POST /investigations: {"screening": <ScreeningOutput>, "mode": "live"} ->
  investigate_screening. Research/tool failures preserve verified partial work.
- GET /runs/{run_id}: retrieve a validated stored result, or HTTP 404.

SQLite results live in TRIALFAIR_DATA_DIR/runs.sqlite and are ignored by Git. Initial
narrative entries and mappings are stripped from persisted snapshots, but source
excerpts/findings may contain supplied information. Preserve appropriate access
controls; do not claim anonymisation.

Agent integration is described in docs/integration.md. All agents share one
ToolContext, deadline and cumulative model/source/tool budget. Statistical output
provenance and model report references are checked before acceptance. A valid ID
is not proof that a paper supports a claim; researchers still review scientific
meaning and the source excerpts provided by Agent 3.

## Known verification limits

The coding environment cannot resolve external hosts or bind local listening
ports. SDK request/response shapes and continuation signatures are tested with an
injected transport, API routes with TestClient, and the actual dashboard with
Streamlit AppTest. These are not a browser-based live server or Gemini verification.
No real-input full-pipeline latency is claimed until Agents 1/3 and the model are
available and an actual end-to-end run is measured.
