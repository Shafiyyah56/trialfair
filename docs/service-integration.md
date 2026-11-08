# Services and integrated verification

Integration branch: feat/service-integration, based on merged main bece131.
Agents 1–3 execute in process; only Streamlit calls the FastAPI backend over HTTP.
Agent 4 remains deferred; PlannerInput is prepared for it.

## Default runtime

`build_context` creates one GeminiModelClient and RunBudget for each run. It wires:

- ClinicalTrialsClient for trial retrieval and related-trial searches, using
  `.trialfair/cache/clinical_trials` and exact source provenance.
- EuropePMCClient for literature search and source inspection, using
  `.trialfair/cache/europe_pmc`.
- SuppliedTerminology with an empty mapping. Source-backed licensed mappings can
  be injected; absence of a terminology service is not permission to invent codes.
- Agent 1's deterministic analysis handler and Agent 3's evidence handler.

Registry and literature share one run-owned HTTP client and budget. API routes
close model/HTTP resources in finally; standalone callers must use
`await context.aclose()` in finally. It is idempotent and cleanup errors do not
erase results. Custom RuntimeServices remain supported; injected source client
lifetime stays with the caller unless registered in context.resource_closers.

The default runtime requires ignored local `.env` values GEMINI_API_KEY,
GEMINI_MODEL and TRIALFAIR_MODE=live. No extra service keys or database server
are needed. Replay execution still requires a separately injected captured runtime;
the default rejects it explicitly. Saved results can be reviewed without re-running.

`/health` marks interpreter, safety and evidence implementations present; planner
is false, so overall status remains partial. These are implementation flags, not
credential or source-uptime probes. No network/model calls occur on health requests.

## Result status and scientific limits

Interpretation failure, text limits, unresolved review mappings or unfinished
requested evidence keep the overall run partial even if the safety model says
completed. Already verified screening/analyses and PlannerInput remain available.
Missing sex-stratified results are valid evidence-gap findings, not automatically
a failed run or evidence that a drug is safe. PK comparisons remain conservative
where source-backed population/window comparability is unavailable.

## Run locally

From the repository root, restart the backend and dashboard after merging:

```sh
uv run --locked uvicorn app.api:app --reload
```

In another terminal:

```sh
uv run --locked streamlit run app/ui/dashboard.py
```

Use the completed-trial input to supply an NCT identifier with posted results.
The API path is `POST /runs` with `{"nct_id":"NCT04280705","mode":"live"}`.
The captured example has more than 100 distinct AE terms, so the bounded
interpreter correctly reports partial coverage. Trial choice changes what can be
analysed; no patient-level records are implied by a public registry identifier.

An opt-in combined check needs no local server:

```sh
uv run --locked python -m scripts.smoke_pipeline --live --nct-id NCT04280705
```

This makes actual source/model calls and may incur charges. It prints short
activity events, elapsed time, budgets and counts, and saves the validated report
in ignored `.trialfair/pipeline-smoke.json`. Exit 1 means the path did not return
screening, investigation and cited evidence; inspect the saved limitations.
Receiving citations does not by itself validate their scientific interpretation.

## Verification scope

`tests/integration/test_services.py` exercises the real interpreter, statistics,
safety and evidence functions, default runtime composition, both HTTP adapters,
API and SQLite. HTTP uses MockTransport: the original public NCT capture plus
explicitly fabricated publication prose. The model is scripted. No live or
medical accuracy claim follows from these tests.

Checks cover related-trial tools being available, inspected source citations,
additional analysis merging once, shared counters, source-cache reuse, partial
interpretation propagation, persistence, resource cleanup and a registry outage
making zero model calls. The interpreter regression previously marked strict
xfail is now required to pass normally.

Combined live latency and a real source-to-conclusion audit remain pending.
The earlier standalone Agent 3 check took 132.81 seconds, close to the shared
150-second deadline. Do not promise that the combined pipeline finishes within
the demo budget until measured. No deadlines or grounding rules were relaxed.

Integration checks: 195 tests passed, 1 opt-in live test deselected, no xfails.
Ruff lint and formatting, diff whitespace and locked offline installation passed.
The existing upstream TestClient warning remains; dependencies were not changed.
