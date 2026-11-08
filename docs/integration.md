# Integration coordination

## Current integration status — feat/service-integration

Agent 2/integrator connects merged Agents 1–3 from main bece131. The existing
RuntimeServices signature and scientific contracts stay compatible. build_context
now constructs ClinicalTrialsClient and EuropePMCClient with one shared budget and
HTTP client, plus empty SuppliedTerminology (no guessed licensed codes).
ToolContext adds resource_closers and idempotent async aclose; the API and smoke
scripts call it in finally. Injected source clients remain caller-owned.

Agreement: implemented by the assigned integration owner; no schema/dependency
migration. Incomplete/limited interpretation, review mappings and incomplete
evidence prevent run-level completed status. Scientific subgroup evidence gaps
alone remain valid findings. The strict expected-failure completion regression
is now a normal passing test. Agent 1's population/window PK constraints remain.
See [integration verification](service-integration.md) and Agent 2's handoff.

The sections below retain the component-by-component implementation history.

Follow-up after the first combined live run: it timed out after 149.85 seconds,
with roughly 93 seconds spent in interpretation. The integration owner bounded
interpretation calls and added a configurable default 20-text batch (1–100).
All source rows still enter statistics. Research preserves source state on local
timeout and reserves time for outer reporting; overall timeout returns explicitly
unassessed partial investigation/planner input. Shared counters/deadline and v1.0
contracts are unchanged. This narrowly adjusts Agent 1/3 execution timing as part
of integration; their scientific extraction/grounding rules remain intact.
198 offline tests pass; paid/live retest remains pending.

Start with [the coding agent handoff](HANDOFF.md). Read [team setup and acknowledgement instructions](TEAM_SETUP.md). Each coding
agent must acknowledge before implementation and update only its own handoff file.

## Baseline ownership

Agent 2's developer is the integrator. They own contracts.py, context.py, config.py,
model_client.py, validation.py, API, orchestration, storage and dashboard.
Other developers propose shared changes here before altering these interfaces.

## Before parallel development

1. Merge current origin/main and, until merged there, origin/feat/agent-2-safety
   into your feature branch. See HANDOFF.md; main alone lacks the shared adapter.
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
2. Review/merge Agent 2 shared adapter, safety, storage and dashboard; or merge
   that remote feature branch into each teammate branch while review is pending.
3. Agent 1 data/statistics and Agent 3 evidence independently, followed by real
   service wiring in app/runtime.py and integration checks.
4. Real-input end-to-end checks, latency measurement and failure rehearsal.
5. Agent 4 planning implementation only once PlannerInput is stable.

## Shared change proposals

Add proposals with: owner, affected interfaces, reason, migration, agreement status
and example payload. Keep schema version 1.0 until an agreed compatibility change
requires a new version. Do not leave a proposal as an unexplained breaking edit.

No unresolved contract-change proposal is recorded. The additive shared changes
below are implemented by Agent 2 and must be incorporated before integration.

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

## Agent 3 implementation on feat/agent-3-evidence

Agent 3 implements run_evidence and EuropePMCClient while preserving the existing
scientific contracts and EuropePMCService/registry Protocols. It uses the shared
ModelClient, generate_with_budget and ToolContext. No dependencies/lock versions
were changed and Agent 1's code was not edited.

Runtime integration included with this branch:
- app/runtime.py now creates the real EuropePMCClient with the same RunBudget as
  context and the configured ignored cache directory. Custom RuntimeServices still
  work. Registry/terminology remain Agent 1 dependencies.
- app/api.py reports evidence implementation present; the full pipeline stays
  partial until Agent 1 is implemented/wired. UI status text reflects this.
- Agent 2's existing dispatcher invokes the new run_evidence and records its result.
  Agent 3 does not append its own result a second time or execute statistics.

See docs/agent-3-usage.md for constructor signatures, constraints, source handling,
CLI verification commands and limitations. Agents 1/2 should incorporate this
feature branch (or the merged main) before testing the full evidence path.
Restart the backend so imported handlers come from the newly merged implementation.

Agent 3 follow-up after the first live attempt: the public EvidenceReport and
AnalysisRequest contracts remain unchanged. The internal provider DTO is now
EvidenceSynthesis; optional parameters are JSON strings at that provider boundary
and become validated AnalysisRequest dictionaries before return. MissingService
adds is_available=False so the evidence agent does not offer unconfigured registry
tools. This is a runtime capability flag, not a replacement registry implementation.
Full-text failure may return a clearly labelled abstract fallback, with limitations.
The first live attempt had zero grounded items; see the Agent 3 handoff for the
corrective changes and pending retest. It is not recorded as a live success.

The second live attempt inspected passages but encountered HTTP 400 in final
synthesis. Only the internal provider transport changed: flat required claim fields
and inline schema, then local conversion to the existing EvidenceItem/SourceLocator.
The optional study context is reported in relevance/limitations when supported.
No public scientific schema or source-grounding validation was relaxed. An explicit
synthetic --schema-only diagnostic now isolates provider acceptance in one call.
## Agent 1 implementation handoff — 2026-11-08

Owner: Agent 1. Existing shared signatures and dependencies are unchanged.
`ClinicalTrialsClient(httpx_client, shared_budget, cache_dir=None, replay=False)`
and `SuppliedTerminology(mappings=None)` are ready for Agent 2 runtime composition.
See [Agent 1 usage](agent-1-usage.md) for tool parameters and conservative limits.

Pending coordination, not an agreed schema change:

- AE comparisons require the same group_id and recorded intervention/population/
  reporting window. Separate source sex-subgroup IDs cannot be proved to share
  an arm using v1.0 alone; they return unavailable. A future arm/dose linkage must
  carry actual source provenance, not model-supplied compatibility flags.
- PKRow lacks population and sampling-window fields. Reported summaries work;
  cross-category ratios are withheld pending a provenance-backed extension.
- ScreeningOutput has no partial status. Agent 2 should propagate explicit
  interpreter-incomplete limitations/review events to run-level partial status.
- Related-trial search retains the existing list[TrialSearchHit] signature;
  source provenance is obtained by fetch_trial for selected hits. Search hits
  alone are not evidence claims. Persistent captured search replay is not provided.

Agreement status: review by Agent 2 pending. No migration or version change was
applied. Agent 2/3 implementation files and shared contracts were not edited.


## Agent 1 pre-merge corrections (integration review required)

Agent 1 now enforces cache-only registry access for replay using its concrete
client's additive fetch_cached_trial method; load_capture registers exact captured
bytes with original hash/retrieval metadata. Shared Protocol signatures are unchanged.
SDK errors preserve screening; availability audits distinguish extraction uncertainty
from source absence. PK uncertainty and subgroup denominators are preserved safely.

Run-level completion remains blocked: test_incomplete_interpretation_must_make_run_partial
in tests/interpreter/test_regressions.py is a strict expected failure against the
unchanged real orchestrator and Agent 2. Agent 2/integrator must propagate incomplete
interpreter work into RunResult partial status. Agent 1 cannot enforce that with
ScreeningOutput alone. No such shared-code change was applied or agreed here.
PK descriptive ratios still need provenance-backed population/window comparability;
source context could supply it without necessarily changing scientific contracts.
