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

Second live follow-up (149.18 s): partial investigation/evidence reports survived,
but zero cited items. Research accumulated 20 publications without inspecting one,
hit the pool cap and aborted on an oversized tool batch. The integrator now caps
actual searches at three, closes search once two queries yield candidates and
requires publication inspection. Pools/batches retain accepted work instead of
aborting synthesis; every provider call receives a tool result. Safety skips more
tool selection when evidence returns with <=45 s. Sanitised error categories/status
now survive safety provider failures. No contracts/dependencies changed.
202 offline tests pass; live cited-output acceptance remains unmet.

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

## Agent 4 additive contract proposal — 2026-11-08

Owner: Agent 4; agreement status: explicitly approved by the user on 2026-11-08.
Implemented on feat/agent-4-planner. Pipeline integration remains with Agent 2.
The user now requests Agent 4; older deferral notes describe previous scope.
Starting baseline: reviewed main dfcfcf5, including service integration.

Proposed shared changes (no dependency/schema-version migration):

- Add PlannerRecommendation and PlannerReport to app/contracts.py, retaining
  PlannerInput unchanged. Report fields: trial_id, status (existing completion
  enum), recommendations (at most eight), unresolved_questions,
  input_limitations, limitations, human_review_required=true, is_synthetic.
- Recommendation fields: recommendation_id, action, rationale, priority,
  priority_rationale, category (additional_analysis/additional_data_collection/
  future_trial_design/interpretation_review), finding_ids, analysis_ids,
  evidence_ids, source_ids, hypothesis_ids, evidence_basis
  (observed_finding/evidence_gap/hypothesis), required_data, availability
  (available/missing/not_assessed), feasibility, prerequisites,
  resolves_question, limitations. IDs and provenance are checked against input;
  relevant contradictions must remain attached. Proposed analysis feasibility
  must reflect actual registered data and conservative Agent 1 preconditions.
- Add planner to AgentEvent.agent. Use existing event types and context.emit;
  no transport or stage-status extension.
- Add validate_planner_report(report, input) to shared validation. Reject unknown
  and unrelated links, incorrect trial/synthetic labels, suppressed contrary
  evidence and completed status with explicitly incomplete upstream inputs.
- First execution is independent run_planner(PlannerInput, ToolContext), with
  at most two inspection turns and one structured selection turn. Reuse shared
  budget/deadline and reserve the final turn. No automatic pipeline append.
  Insufficient budget returns unavailable. No global limit increase.
- Defer RunResult/API/storage/UI/pipeline scheduling changes to the integrator;
  a later opt-in pipeline integration must reserve time/turns before Agents 1–3,
  rather than append a planner after an exhausted deadline. Independent planning
  is explicitly a separately budgeted execution when given a new context.

Example proposed payload (synthetic illustration; IDs must resolve in actual input):

```json
{
  "schema_version": "1.0",
  "trial_id": "synthetic-trial",
  "status": "partial",
  "recommendations": [{
    "schema_version": "1.0",
    "recommendation_id": "plan-gap-1",
    "action": "Obtain affected-participant counts and corresponding denominators by reported sex for the same arm and reporting window.",
    "rationale": "The reported data do not support a sex-specific event-rate comparison.",
    "priority": "high",
    "priority_rationale": "Resolve the data prerequisite before interpreting a subgroup difference.",
    "category": "additional_data_collection",
    "finding_ids": ["gap-1"], "analysis_ids": [], "evidence_ids": [],
    "source_ids": ["synthetic-source"], "hypothesis_ids": [],
    "evidence_basis": "evidence_gap",
    "required_data": ["Affected participants and at-risk denominators by sex, arm and window"],
    "availability": "missing",
    "feasibility": "Requires source retrieval or sponsor data; no comparison was executed.",
    "prerequisites": ["Verify source-backed arm and reporting-window comparability"],
    "resolves_question": "Can comparable sex-specific adverse-event rates be calculated?",
    "limitations": ["Missing evidence does not establish safety."]
  }],
  "unresolved_questions": ["Upstream assessment requires completion."],
  "input_limitations": ["Investigation is partial; no accepted literature evidence."],
  "limitations": ["Human review must assess applicability and scientific support."],
  "human_review_required": true,
  "is_synthetic": true
}
```

Implementation approach after agreement: application-authored candidate actions
and numerical/clinical guardrails, with model selection/prioritisation over bounded
candidates, allowlisted read-only inspection tools, full continuation history and
a result for every tool call. This avoids accepting model-invented calculations
or clinical actions. Complete/partial synthetic examples and offline behavioural
tests accompany implementation. No full clinical/live readiness claim follows.


Implementation details after approval: the model returns a compact Selection
(candidate ID, priority, constrained reason code), not arbitrary report prose.
Application code compiles PlannerReport from inspected candidates. Up to 24
candidates, eight recommendations, two inspection turns and one extraction turn,
with a 30-second local cap inside the unchanged original deadline. Existing
Agent 1 audit_subgroup_availability supplies deterministic prerequisite checks;
no statistics, source requests or recursive agents are executed. Explicit upstream
limitations keep the report partial; failed selection returns unavailable.
Only shared Python edits are additive contracts/event identity and validation.
RunResult, runtime, context, model adapter, config, API, storage, UI and dependencies
remain unchanged. Live/provider and combined clinical acceptance are unverified.

## Shared changes: participant-level analyses (2026-11-08, pushed to main)

Owner: Agent 1 (Shafiyyah). Pushed directly to main at the user's request; please review.

- `app/contracts.py`: `ToolName` gains `exposure_response` and `summarise_qtc_by_sex`.
  Additive only; schema version stays 1.0. Agents 2 and 3 can request them through the
  existing `AnalysisRequest`; unsupported names are still rejected.
- `app/model_client.py`: `ModelClient.generate` and `generate_with_budget` accept an
  optional `thinking_level`. The Gemini adapter sends `ThinkingConfig` only when it is
  set, so default behaviour is unchanged. Test fakes using `**kwargs` need no change.
- `app/config.py`: optional `TRIALFAIR_INTERPRETER_THINKING_LEVEL` (blank = unset).
  Measured on gemini-4-argon with 39 interpretation texts: about 27-32 s at `low`
  versus 37-39 s at the default. Both are close to the 35 s first-pass cap, so it is
  left off by default.
- Participant-level values (per-participant exposure, AE and QTc) stay in process
  memory (`participant_table_for(bundle)`) and are never added to TrialBundle,
  RunResult or SQLite. The new tools return `unavailable` when that data is not loaded
  in the current server process, for example when a stored run is reopened later.
## Agent 4 additive contract proposal — 2026-11-08

Owner: Agent 4; agreement status: explicitly approved by the user on 2026-11-08.
Implemented on feat/agent-4-planner. Pipeline integration remains with Agent 2.
The user now requests Agent 4; older deferral notes describe previous scope.
Starting baseline: reviewed main dfcfcf5, including service integration.

Proposed shared changes (no dependency/schema-version migration):

- Add PlannerRecommendation and PlannerReport to app/contracts.py, retaining
  PlannerInput unchanged. Report fields: trial_id, status (existing completion
  enum), recommendations (at most eight), unresolved_questions,
  input_limitations, limitations, human_review_required=true, is_synthetic.
- Recommendation fields: recommendation_id, action, rationale, priority,
  priority_rationale, category (additional_analysis/additional_data_collection/
  future_trial_design/interpretation_review), finding_ids, analysis_ids,
  evidence_ids, source_ids, hypothesis_ids, evidence_basis
  (observed_finding/evidence_gap/hypothesis), required_data, availability
  (available/missing/not_assessed), feasibility, prerequisites,
  resolves_question, limitations. IDs and provenance are checked against input;
  relevant contradictions must remain attached. Proposed analysis feasibility
  must reflect actual registered data and conservative Agent 1 preconditions.
- Add planner to AgentEvent.agent. Use existing event types and context.emit;
  no transport or stage-status extension.
- Add validate_planner_report(report, input) to shared validation. Reject unknown
  and unrelated links, incorrect trial/synthetic labels, suppressed contrary
  evidence and completed status with explicitly incomplete upstream inputs.
- First execution is independent run_planner(PlannerInput, ToolContext), with
  at most two inspection turns and one structured selection turn. Reuse shared
  budget/deadline and reserve the final turn. No automatic pipeline append.
  Insufficient budget returns unavailable. No global limit increase.
- Defer RunResult/API/storage/UI/pipeline scheduling changes to the integrator;
  a later opt-in pipeline integration must reserve time/turns before Agents 1–3,
  rather than append a planner after an exhausted deadline. Independent planning
  is explicitly a separately budgeted execution when given a new context.

Example proposed payload (synthetic illustration; IDs must resolve in actual input):

```json
{
  "schema_version": "1.0",
  "trial_id": "synthetic-trial",
  "status": "partial",
  "recommendations": [{
    "schema_version": "1.0",
    "recommendation_id": "plan-gap-1",
    "action": "Obtain affected-participant counts and corresponding denominators by reported sex for the same arm and reporting window.",
    "rationale": "The reported data do not support a sex-specific event-rate comparison.",
    "priority": "high",
    "priority_rationale": "Resolve the data prerequisite before interpreting a subgroup difference.",
    "category": "additional_data_collection",
    "finding_ids": ["gap-1"], "analysis_ids": [], "evidence_ids": [],
    "source_ids": ["synthetic-source"], "hypothesis_ids": [],
    "evidence_basis": "evidence_gap",
    "required_data": ["Affected participants and at-risk denominators by sex, arm and window"],
    "availability": "missing",
    "feasibility": "Requires source retrieval or sponsor data; no comparison was executed.",
    "prerequisites": ["Verify source-backed arm and reporting-window comparability"],
    "resolves_question": "Can comparable sex-specific adverse-event rates be calculated?",
    "limitations": ["Missing evidence does not establish safety."]
  }],
  "unresolved_questions": ["Upstream assessment requires completion."],
  "input_limitations": ["Investigation is partial; no accepted literature evidence."],
  "limitations": ["Human review must assess applicability and scientific support."],
  "human_review_required": true,
  "is_synthetic": true
}
```

Implementation approach after agreement: application-authored candidate actions
and numerical/clinical guardrails, with model selection/prioritisation over bounded
candidates, allowlisted read-only inspection tools, full continuation history and
a result for every tool call. This avoids accepting model-invented calculations
or clinical actions. Complete/partial synthetic examples and offline behavioural
tests accompany implementation. No full clinical/live readiness claim follows.


Implementation details after approval: the model returns a compact Selection
(candidate ID, priority, constrained reason code), not arbitrary report prose.
Application code compiles PlannerReport from inspected candidates. Up to 24
candidates, eight recommendations, two inspection turns and one extraction turn,
with a 30-second local cap inside the unchanged original deadline. Existing
Agent 1 audit_subgroup_availability supplies deterministic prerequisite checks;
no statistics, source requests or recursive agents are executed. Explicit upstream
limitations keep the report partial; failed selection returns unavailable.
Only shared Python edits are additive contracts/event identity and validation.
RunResult, runtime, context, model adapter, config, API, storage, UI and dependencies
remain unchanged. Live/provider and combined clinical acceptance are unverified.

## All four agents and curated demo integration

Owner: Agent 2/integrator on feat/demo-integration; authorised by the user's urgent
full-demo request. Agent 4 commit 0281f17 was imported from GitHub with original
author preserved; only an integration-document conflict required resolution,
preserving both the participant-analysis and planner sections.

Shared additive changes: optional RunResult.planner_report; ToolContext planner
handler and stage snapshots; planner progress identity/output; schema/reference
validation of planner outputs before storage/display. Normal runtime now wires
run_planner. Budget reservation allocates three original model turns and a portion
of the original deadline before Agents 1–3; counters are never reset. All four
implementations appear in health metadata, independently of provider uptime.

Explicit /demo/runs/async uses captured NCT04280705 and three real curated article
excerpts/annotations with labels and hashes. This does not invent source requests
or autonomous searches. Only this explicit profile has a longer configured shared
budget and visible source-based assessment/candidate-draft fallbacks when a model
fails. Normal autonomous mode remains available. Read DEMO.md. No dependencies or
schema-version migration; teammates should update clients for optional planner
report/progress fields. 265 offline tests pass; actual live demo retest is pending.

## Agent 4 functional corrections — 2026-11-08

Authorisation: the user explicitly requested fixes for the four verified issues,
with Agent 4-only scope except a shared output-contract addition if necessary.
The minimal addition is PlannerFindingDisposition plus a defaulted
PlannerReport.finding_dispositions list, required by the corrected completion
validation to distinguish resolved, explicitly unresolved and follow-up states
without interpreting free-form prose. This changes only the Agent 4 output; no
Agent 1–3 payload, PlannerInput, RunResult or function signature changes. No
schema-version, dependency or lock changes. Older partial reports still parse;
older completed planner reports need explicit dispositions before validation.
The complete synthetic fixture has been updated. No persisted planner migration
is currently needed because planner output is not integrated into storage.

Planner-only generation now matches requested PK parameters, preserves hypotheses
with scoped evidence, and uses existing representation counts before suggesting
new collection. Shared validation changes apply only inside validate_planner_report:
accept indirect evidence only through a relevant retained hypothesis; retain all
relevant hypotheses; validate related dispositions and full completed coverage.
No changes to validate_run, validate_planner_input, Agents 1–3 or their implementations.
See verification/agent-4-fixes.md for TDD evidence, scenario results and limits.
Default pipeline scheduling, new API/storage/UI integration and live acceptance
remain the integrator's follow-up. Changes are local; no push/PR update/merge.

## Resolved main merge after Agent 4 fixes

The integrator merged origin/main at 64cf634 into feat/demo-integration, retaining
all new Agent 4 implementation/validation fixes, dispositions and updated synthetic
fixtures, plus the existing four-agent API/storage/progress/UI/demo integration.
The incoming planner code is unchanged except for the existing explicit demo-only
90-second cap; ordinary planning remains 30 seconds. RunResult.planner_report and
its run-level validation checks are retained alongside the new output fields.

The stronger completed-plan disposition rules remain enforced. Existing partial
saved demo reports still validate; the previously observed 95.87-second report
with four draft actions was checked successfully. Old notes saying planner output
is not stored describe the pre-integration implementation. All 298 offline tests,
Ruff lint/format and whitespace checks pass. No paid/live call was made for this merge.
