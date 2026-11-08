# TrialFair coding agent handoff

Read this document, AGENTS.md, your assignment and app/contracts.py before coding.
This is the entry point for Agents 1 and 3 integrating with the completed Agent 2.

## Get the right code first

As checked directly in GitHub on 2026-11-08, Agent 2 implementation and live-smoke
notes were pushed through 74f81d9 on feat/agent-2-safety. main was still at c18b5de;
Agents 1 and 3 were still at the initial scaffold 9c65ea0. These are observations,
not permanently current branch pointers. Fetch and inspect the current remote.

Merging main alone will not obtain the safety adapter while Agent 2 is unmerged.
Stay on your own assigned branch and incorporate the shared work:

```sh
git status
git fetch origin
git switch <your-assigned-branch>
git merge origin/main
git merge origin/feat/agent-2-safety
uv sync --locked --extra dev
```

If the branch is only on GitHub, first select it with
`git switch --track origin/<your-assigned-branch>`. Preserve uncommitted work before
switching or merging; do not reset, overwrite files or force-push. Resolve conflicts
by preserving each owner's implementation and agreeing shared changes. Once Agent 2
is merged into main, merging current main will bring it in and the extra feature
branch merge is unnecessary. Do not merge into main without the team's review.

If uv is not on PATH, use `python3 -m uv` instead. If it is not installed, install
it using the team's chosen setup method. Do not replace the committed lockfile
merely to make an installation work.

## Current working state

- Agent 2: implemented safety tool loop, model adapter, bounded orchestration,
  FastAPI, SQLite, Streamlit and PlannerInput assembly.
- Agent 3: implemented on feat/agent-3-evidence with a real Europe PMC client
  wired into the runtime. See [Agent 3 usage](agent-3-usage.md). A live research
  check returned two audited items with partial status; see
  [the verification scope](verification/agent-3-live.md).
- Agent 1: still required for real trial ingestion, statistics and registry/
  terminology adapters. Do not infer completion from the working UI.
- Agent 4: deferred. PlannerInput is available; no planner output is implemented.
- Automated checks on the evidence branch: 110 tests pass; Ruff lint/format and
  lock consistency pass. Agent 2's earlier milestone had 60 tests.
- Live Gemini smoke: user-run on 2026-11-08, gemini-4-argon, google-genai 2.34.0,
  models.generate_content; plain reply, function calling and JSON output passed.
- Live Agent 2 browser check: user launched local servers; Chrome showed a 34.63 s
  investigation with live Gemini and synthetic screening. It inspected a finding
  and analysis, requested external evidence and returned partial because Agent 3
  was unavailable. The report preserved that limitation and synthetic labelling.
- Not verified: real trial ingestion -> real statistical results -> actual
  literature retrieval -> integrated clinical report. This remains the next
  shared acceptance check after Agent 1 is implemented and wired to Agents 2/3.

The coding sandbox cannot reach external hosts or bind ports, but the user's
Terminal and Chrome successfully ran the local application. This is a sandbox
restriction, not a requirement that teammates change their normal machines.

## Read the right assignment

| Role | Implement | Reuse | Detailed assignment |
| --- | --- | --- | --- |
| Agent 1 | Interpreter, registry adapter, terminology lookup, deterministic statistics | ModelClient, ToolContext, contracts | [Agent 1](agent-1.md) |
| Agent 2/integrator | Safety agent, shared interfaces/model, runtime, API, storage, UI | Agent 1/3 functions and source services | [Agent 2](agent-2.md) |
| Agent 3 | Adaptive evidence investigator and Europe PMC adapter | Agent 1 registry adapter, shared model/context | [Agent 3](agent-3.md) |

Only update your own acknowledgement in docs/handoffs/agent-N.md. First tell your
human the actual branch/commit, owned files, shared interfaces and setup blockers.
Agent 2 has acknowledged; do not mark Agents 1 or 3 as acknowledged for them.

## Integration contract

| Function | Input | Output | Owner |
| --- | --- | --- | --- |
| run_interpreter | TrialInput, ToolContext | ScreeningOutput | Agent 1 |
| execute_analysis | AnalysisRequest, ToolContext | AnalysisResult | Agent 1 |
| run_safety | ScreeningOutput, ToolContext | InvestigationReport | Agent 2 |
| run_evidence | EvidenceRequest, ToolContext | EvidenceReport | Agent 3 |
| run_trial | TrialInput, ToolContext | RunResult including PlannerInput when available | Agent 2 |

All functions are async, in process and defined at the existing module paths.
The scientific JSON contracts remain version 1.0. Do not replace them with your own
schemas or add agent-specific HTTP servers. Service Protocols in app/services/
are interface declarations, not working network adapters.

### Model calls and tool history

Use the injected context.model through the shared budget helper:

```python
from app.model_client import ModelMessage, generate_with_budget

response = await generate_with_budget(context, messages, tools=tool_definitions)
messages.append(ModelMessage(role="assistant", content=response.model_dump(mode="json")))
# For each allowlisted, validated tool call that your agent executes:
messages.append(
    ModelMessage(
        role="tool",
        content={
            "call_id": call.call_id,
            "name": call.name,
            "result": validated_tool_result,
        },
    )
)
```

This snippet illustrates message construction; call, messages and the result are
local variables in your actual tool loop. Keep the entire response payload in the
assistant message so continuation survives. Do not rebuild the history from plain
text or share opaque continuation tokens between clients/runs. Do not expose
provider thought text or signatures in logs/UI. Request final structured output in
a separate helper call with tools=[] and output_schema=YourContract.model_json_schema().
Validate returned structured_output with the destination Pydantic model.

The helper consumes model_turn; do not count the same turn again. Service adapters
consume external_request once per actual source HTTP attempt, use remaining_seconds
for timeouts and return cached responses without pretending to refetch them. Do not
reset budgets when one agent calls another. SDK retries/automatic tools are disabled.

### Agent 1 output requirements

- Populate TrialBundle.sources and preserve source locations, group IDs, reported
  categories, analysis populations, missingness and event denominators.
- Register validated data in context.datasets under opaque IDs. Never interpret a
  dataset_ref as a path. AnalysisRequest references must resolve to the same trial.
- Additional AnalysisResult must echo request_id, use a new analysis_id and carry
  valid source locators. method describes the actual statistical method; it need
  not equal tool_name. Return unavailable/invalid when preconditions fail.
- Do not append the same additional result yourself when called through Agent 2;
  its dispatcher validates and records it. Initial screening remains Agent 1's work.
- The current allowlist is summarise_representation, audit_subgroup_availability,
  compare_adverse_event_rates and summarise_pk_by_sex. No arbitrary code execution.
- For uploaded narrative entries, create matching uploaded_data SourceRecords
  before returning ScreeningOutput. Missing subgroup data is an evidence gap,
  never evidence of a numerical sex difference.

### Agent 3 output requirements

- Echo EvidenceRequest.request_id and return EvidenceReport, including unavailable
  or partial status when appropriate; do not invent a successful search.
- Every cited publication must be retrieved by a source tool, retain access level,
  licence status, source location and claim support. Metadata-only review is not
  full-text review. Resolving an ID alone does not verify a scientific claim.
- Preserve supporting, contradictory, inconclusive and background evidence.
  Relevant contradictory items remain linked to the assessed finding/hypothesis.
- Return suggested_analysis_requests to Agent 2. Do not execute statistics, reset
  the budget or recursively call the safety agent.
- Reuse the registry service's fetch_trial/search_related_trials interfaces.
  Deduplicate a registry record and publication describing the same trial.

### Compose real services after merging

Agent 2 owns app/runtime.py and updates it with the concrete adapters supplied by
Agents 1 and 3. The Europe PMC client is wired on the evidence branch. Remaining MissingService
instances for registry/terminology are deliberate and must be replaced by Agent 1.
Implementing an adapter without wiring it will still produce unavailable results.

For adapters that need the shared per-run budget, create the context first, then
attach adapters constructed with that same context.budget. For example, an
integrator's context_factory(run_id, mode) can call build_context(run_id, mode),
assign context.registry/literature/terminology to real adapters and return context.
Pass this factory to create_app(context_factory=...). Do not construct a fresh
budget inside each adapter. The actual adapter class names/constructors are agreed
with their owners; none are claimed to exist in the current Protocol-only modules.
For the implemented EuropePMCClient constructor and its budget/cache handling,
see agent-3-usage.md. Restart the backend after merging so imports use the new handler implementations.
Update health component flags only once the real services are wired and checked.

## Acceptance and delivery

1. Run locked installation, pytest, Ruff lint and Ruff formatting from repo root.
2. Add scientific/behavioural tests for your component, using injected model/source
   fakes for ordinary tests. Keep paid/live checks opt-in.
3. Check the fixture payloads and cross-record validation without modifying tests
   merely to accept incompatible outputs.
4. Update your handoff with implemented files, exported adapter constructors,
   example payloads, tests actually run, live checks and remaining limitations.
5. Push your own branch and provide a reviewable PR. Keep .env and caches out of
   Git; share authorised credentials privately. Shared changes go through Agent 2.
6. After integration, test a real completed NCT record with posted results and real
   literature. Missing subgroup evidence is a valid output. Measure actual latency,
   verify sources and preserve uncertainty before implementing Agent 4.

No database server, cloud hosting, vector store or additional agent framework is
required. Evidence transparency and a working research loop take priority.
