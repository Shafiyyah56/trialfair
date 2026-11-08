# Agent 2 acknowledgement and handoff

Status: ACKNOWLEDGED; implementation complete for independent/injected operation.
Full live research and browser-server verification remain pending as detailed below.

## Startup acknowledgement

I read AGENTS.md, docs/TEAM_SETUP.md, my assignment, README.md, project context,
architecture and shared contracts. I implemented Agent 2 on feat/agent-2-safety,
starting from c18b5de. I own safety, the model adapter, orchestrator, API, storage,
dashboard and shared integration files. ModelClient, ToolContext and version 1.0
scientific payloads are reused. Provenance is preserved; credentials stay local.
This acknowledgement is for Agent 2 only.

- Cached origin/main at c18b5de was fast-forwarded into the feature branch.
- Fresh fetch failed: github.com DNS unavailable in the execution environment.
- Locked offline sync passed: uv 0.13.7, Python 3.13, google-genai 2.34.0.
- An ignored .env template was created only because none existed. No credentials
  were overwritten or printed. Neither key nor model was configured at verification.

## Implementation handoff

Implemented:
- safety.py: allowlisted model-selected tools, input/output validation, additional
  analyses, external research requests, hypothesis/report validation, contradiction
  retention, concise activity events and partial reports on failure/deadline.
- model_client.py: run-local SDK adapter, preserved provider content/signatures,
  manual tools, separate structured output, bounded calls and no hidden retries.
  generate_with_budget is the shared entry point for agent model calls.
- orchestrator.py: full and prepared-screening paths, one deadline, accepted analysis
  merging, evidence collection and validated PlannerInput. No Agent 4 output.
- runtime.py: explicit real-adapter injection; missing service implementations fail
  honestly. There is no production fake model or automatic replay substitution.
- api.py: /health, POST /runs, POST /investigations and GET /runs/{run_id}.
- storage.py: per-operation SQLite connections, validated reads/writes and stripping
  top-level narratives/mappings from persisted snapshots. Source excerpts/findings
  can still contain supplied information; this is not anonymisation.
- dashboard.py: trial/prepared screening input, optional trial symptom text, saved
  result review, availability, findings, analyses, evidence, sources, activity and
  JSON export. Synthetic and saved/replay inputs remain visibly labelled.
- scripts/smoke_gemini.py: explicit --live, at most three model requests testing a
  basic reply, local ping function call, continuation and structured response.

Integration changes are recorded in docs/integration.md. No scientific schema or
SDK dependency version was replaced. HealthResponse gained optional readiness
metadata and ModelResponse an opaque optional continuation token. Agents 1/3 must
use the shared helper/adapter, not create competing clients. Their implementation
files have not been edited.

## Actual validation on 2026-11-08

- `uv sync --locked --extra dev --offline`: passed.
- `.venv/bin/pytest -q`: 60 passed, one upstream Starlette/httpx deprecation warning,
  0.56 seconds for this local test run. This is not a live research latency metric.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: passed, 45 files formatted.
- `uv lock --check --offline`: passed, 68 packages; lockfile unchanged.
- `git diff --check`: passed.
- SDK integration used real installed SDK types plus a fake transport. Verified
  opaque signature preservation, response schema shape, timeout and retries.
- API integration used TestClient with injected services and temporary SQLite.
- Dashboard rendered successfully in Streamlit AppTest with a labelled synthetic
  saved-run example. No claim of a live clinical or model result.

## Unverified or blocked

- Live Gemini: NOT TESTED. GEMINI_API_KEY and GEMINI_MODEL are unconfigured;
  available account model, live tool calls and live structured output are pending.
- Local server launch: both Uvicorn and Streamlit attempted; sandbox refused bind
  on local ports. Browser-based live UI verification could not be performed here.
- External network/GitHub: DNS unavailable from the execution environment.
- Agents 1 and 3 remain stubs on this branch. Full NCT ingestion and actual external
  research require their implementations and RuntimeServices wiring. Evidence-tool
  unavailability returns a partial result rather than fabricated literature.
- Full real-input end-to-end latency: not measured.
- An unrelated untracked `uv 2.lock` appeared during work and was left untouched;
  the canonical dependency file remains uv.lock.

See docs/agent-2-usage.md for exact launch, smoke-check and integration instructions.
