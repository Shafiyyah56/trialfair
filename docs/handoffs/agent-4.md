# Agent 4 handoff — 2026-11-08

## Startup acknowledgement

I am implementing Agent 4 on feat/agent-4-planner, starting from
 dfcfcf5e0f28513f925541fadc89008411e03f94 (also fetched origin/main).
Read AGENTS.md, TEAM_SETUP, HANDOFF, README, project context, architecture,
the supplied assignment, integration/readiness documentation and shared contracts.
Service integration commits dc2b886, 8ab8457 and 6cd41c8 are ancestors.
No additional Agent 2 branch merge is needed: its implementation is on main.
Owned scope: app/agents/planner.py, planner tests, agent-4 assignment/usage and
this handoff. Shared contracts, validation and event/API/runtime changes require
integrator agreement. Reuse ModelClient, generate_with_budget, ToolContext,
PlannerInput, the existing run budget and context.emit. No independent clients,
services, research, calculations or clinical actions. No email by any route.

Setup: fetched origin successfully; locked dev sync passed using
UV_CACHE_DIR=/private/tmp/trialfair-uv-cache (default cache is sandbox restricted).
Untracked .vscode/ is preserved. No secrets read or live calls made.
Full live cited-report acceptance remains unmet; offline checks cannot establish it.

## Initial coordination (subsequently approved)

See the Agent 4 proposal in docs/integration.md. The user explicitly approved the proposed shared edits on 2026-11-08;
implementation proceeded within that agreed scope.

## Baseline verification

- uv sync --locked --extra dev: passed (temporary writable UV_CACHE_DIR).
- uv run --locked pytest -q: 202 passed, 1 live test deselected; one existing
  Starlette TestClient deprecation warning.
- uv run --locked ruff check .: passed.
- uv run --locked ruff format --check .: passed (69 files).
- No live planning or paid/network research checks performed.

Added docs/agent-4.md and the concrete schema/example proposal in integration.md.
These were baseline checks before implementation. The implementation results
and shared changes below supersede the initial pending status.


## Implemented scope and shared changes

- app/agents/planner.py: independent async run_planner, deterministic candidate
  actions/prerequisites, model-selected inspections/priorities, full continuation
  history, read-only allowlist, per-call rejected results, constrained structured
  selection, honest partial/unavailable fallbacks, planner events via context.emit.
- Shared app/contracts.py: additive PlannerRecommendation/PlannerReport and
  planner AgentEvent identity. Existing PlannerInput, RunResult and version 1.0
  are unchanged. User approved the documented proposal before these shared edits.
- Shared app/validation.py: additive planner input-limitations helper and output
  reference-edge, synthetic/status, hypothesis/contradiction validation. Existing
  Agents 1–3 validation behaviour is unchanged.
- tests/planner/test_planner.py: offline behaviour and fixture checks.
- Four fixtures/synthetic/planner_{complete,partial}_{input,output}.json examples:
  fabricated/scripted, explicitly synthetic; validated complete/partial snapshots.
- docs/agent-4.md, agent-4-usage.md, this handoff and integration proposal; current
  status pointers in README/onboarding/architecture/service/project docs updated.
  Historical teammate handoffs were not rewritten.

Uses Agent 1's existing audit_subgroup_availability only for prerequisites. No
analyses, literature searches, recursive agent calls or clinical decisions execute.
Up to 24 candidates, eight recommendations, two inspection turns plus one selection
turn, four executed lookups per inspection turn and 30 seconds within the ORIGINAL
shared budget. The same model/context/deadline/run ID/event sink are retained.
Contexts remain caller-owned and must be closed in finally by the owning caller.
Application-authored text plus constrained selection prevents model-proposed
statistics, dosing, citations or medical assertions from entering generated actions.
Schema/reference validation alone cannot certify arbitrary externally authored
prose, source support, applicability or scientific truth; human review is mandatory.

## Verification and remaining work

- Full offline suite: 243 passed, 1 live test deselected; existing Starlette
  TestClient deprecation warning remains. Includes 41 new planner cases.
- Locked dev sync passed. Ruff lint and format checks passed. Diff whitespace passed.
- No dependency/lock changes; no edits to Agents 1–3, SDK/model adapter, context,
  global budgets, runtime, API, storage, dashboard or orchestration.
- No live planner/provider/schema check, real recommendation-usefulness evaluation
  or combined clinical cited-report success was performed or claimed.
- Default pipeline does not call planner. No new RunResult/API/storage/UI fields.
  Integrator must agree scheduling with reserved time/turns before Agents 1–3,
  persistence/read validation and real-event UI integration. Existing health flag
  remains false for the default pipeline, as documented.
- Candidate vocabulary is limited; it does not create arbitrary mechanistic or
  experimental plans. Missing/contradictory/abstract-only evidence remains explicit.
- Existing .vscode/ untracked files are preserved; credentials remain local and
  unread. No email or external communications were sent.


## Functional fixes after merging main — 2026-11-08

Starting from merge 14bbd36 (main through 9c117d9). The user authorised the four
functional corrections with TDD, synthetic-only checks and no publishing/merge.
Regression tests were written first: 23 failed, 5 passed against the old code.
After the fixes and extra scope checks, 32 new cases pass (73 planner cases total).
Full suite: 289 passed, 1 live test deselected; Ruff lint/format and diff whitespace
passed. One pre-existing 100 ms evidence timing test failed once, then passed in
isolation and in the full rerun without any upstream change; the existing
Starlette TestClient deprecation warning remains.

Changes: parameter-specific PK prerequisites; source-reported representation
review and targeted missing-field collection; retained cross-finding hypotheses
and exact scoped evidence with applicability limits; typed finding dispositions
and complete output coverage. The additive Agent 4 disposition model/defaulted
field is necessary to distinguish workflow completion from scientific resolution.
Existing functions, input contracts, schema_version and dependencies are unchanged.
The complete synthetic output now carries an explicit follow-up disposition.

Ten synthetic scripted planner executions repeated all four functional scenarios
plus denominator/window/registration/missing-evidence/dosing rejection checks.
All pass with the corrected expected behaviour. An injected real-code Agents 1–4
exercise still accepts upstream PlannerInput, retains two evidence items and adds
two model attempts (8 to 10) using the same context and original deadline.
All model and literature behaviour is scripted/synthetic; no paid or live calls.
See verification/agent-4-fixes.md and tests/planner/test_functional_regressions.py.
No code in Agents 1–3, runtime, model adapter, API, storage or UI changed.
No commits, pushes, PR operations or merges were performed for these corrections.
Existing .vscode/ and previously created synthetic fixture data remain preserved.
Live provider compatibility/usefulness and default pipeline integration remain
unverified/pending. Legacy completed planner payloads need dispositions; semantic
support and clinical applicability still require human review.
