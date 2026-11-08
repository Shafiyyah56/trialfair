# Agent 4 usage and integration

Agent 4 runs independently on an existing validated `PlannerInput`. The user
approved the additive contract/event/validation proposal on 2026-11-08.
It is integrated on feat/demo-integration: run_trial schedules planning with reserved
shared budget, RunResult.planner_report is validated and persisted, and the dashboard
displays planning progress and actions. Health flags describe installed implementations,
not clinical validity or provider availability. See [the demo runbook](DEMO.md).

## In-process execution

```python
from app.agents.planner import run_planner
from app.validation import validate_planner_report

# snapshot: PlannerInput obtained from a validated run.
# context: the caller's existing ToolContext, including its original budget.
try:
    report = await run_planner(snapshot, context)
    validate_planner_report(report, snapshot)
    payload = report.model_dump(mode="json")
finally:
    await context.aclose()  # when this caller owns the context
```

To plan from a saved snapshot in a NEW execution, callers may explicitly create
an owned context using `build_context(new_run_id, "live")`. This makes paid model
calls, uses a separate budget/run identity, and is not part of the saved original
run's elapsed time. An independent snapshot is not automatically registered as a
dataset: source-backed validation/registration is required before a proposed
analysis is labelled executable. Injected/replay models are test-only or explicitly
configured by the caller; no production fake/replay substitution is provided.
No model, network, credentials or filesystem operation happens at module import.

## Bounded planning behaviour

- Up to 24 candidate actions, screened high-priority findings first; up to eight
  selected recommendations. Omitted findings remain unresolved in the report.
- At most two read-only inspection turns, four executed lookups per turn, and
  one separate structured selection call. Every returned tool call gets a result,
  including unknown, duplicate or excess calls. Full model responses preserve
  opaque continuation tokens; provider contents are never logged.
- At most 30 seconds normally, or 90 in the explicit curated demo, always inside
  the existing shared deadline. A minimum of
  two remaining model turns and two seconds is required before model work.
  There is no budget reset, hidden retry or global limit increase. A provider
  attempt is counted by `generate_with_budget` exactly once.
- The model chooses which findings/evidence/hypotheses/data to inspect, selects
  actions and prioritises them with constrained reason codes. Recommendations
  require inspection of their finding. Inspection returns linked analysis results,
  accepted evidence, exact locators, source access metadata and hypotheses.
- Application code supplies action text, stable hashed IDs, rationale, required
  data, prerequisites and references. The model cannot add narrative, statistics,
  clinical assertions, source IDs, quotations or dose recommendations. Supplying
  extra fields, an unknown candidate or an uninspected selection rejects the plan.
- Actual rows and Agent 1's availability audit determine AE prerequisites;
  baseline denominators and event occurrences never substitute for participant
  counts. Identical registered snapshots are required for executable proposals.
  PK availability now requires every explicitly requested parameter (case/spacing
  normalisation only); AUC, Cmax, Tmax, clearance and AUC windows are not
  interchangeable. An unspecified parameter with existing rows requires review.
  PK summaries remain descriptive, preserve reported categories and do not imply
  subgroup adequacy; population/window comparability is unverified in v1.0. Planning never executes an analysis or starts research.
- Candidate families include interpretation review, source/data collection,
  compatible AE or descriptive PK analysis, evidence applicability review and
  future PK protocol reporting when a PK gap justifies that alternative. Known
  subgroup representation counts now produce a precision/recruitment-feasibility
  review using exact reported labels, counts, denominators, groups and populations;
  only genuinely missing fields trigger representation data collection. No target
  or statistical-adequacy threshold is inferred, and overlapping groups are not pooled.
  This first candidate vocabulary is deliberately limited; free-form experiment
  design and mechanistic explanations are outside it.

`context.emit` receives application-authored planner decision/tool_result/revision/
stop events. Events show observed actions, not hidden reasoning, provider text or
sensitive narratives. Existing event transport is unchanged.

## Status, validation and scientific limits

Valid gaps can produce useful partial plans, including when safety is unassessed
or accepted literature evidence is empty. Any upstream limitations, unavailable
analyses, unassessed findings, unresolved interpretation, unfinished evidence work
or zero accepted evidence keep planning partial. This is intentionally conservative:
`completed` means the bounded planning task completed with no explicit input
limitations; it never means the drug is safe or the trial can progress.
A failed/rejected/timed-out selection returns unavailable with no invented plan.
Invalid input references are rejected before any model call.

`PlannerReport.finding_dispositions` is an additive, defaulted list of typed
`PlannerFindingDisposition` objects. A completed report must explicitly dispose
of every screened finding (including every assessed finding). States are:

- `requires_further_investigation`: links valid, related recommendation IDs.
- `unresolved`: gives a nonempty rationale without claiming scientific resolution.
- `resolved`: records a human-reviewed planning disposition with related accepted
  evidence or a completed analysis as review support. This is not a drug-safety
  conclusion; reference validity still does not establish semantic support.

Generated plans mark selected findings as requiring further investigation and
omitted findings as unresolved, keeping bounded omissions partial. External human
review can complete planning while explicitly recording unresolved questions.
The planner does not autonomously assert that a finding is resolved. Existing
partial payloads can omit this new field, but older completed planner payloads
must add valid dispositions before passing the stronger output validator. The
complete synthetic output fixture demonstrates this. `PlannerInput`, Agents 1–3,
`RunResult` and function signatures are unchanged; schema_version remains 1.0.

Hypotheses and their supporting/contradicting evidence are retained across finding
boundaries. Indirect evidence retains its original finding IDs, exact source support
and an explicit applicability limitation; it is not promoted into direct support
for a different finding. Data feasibility uses directly linked source rows only.

`validate_planner_report` checks trial and synthetic labels, duplicate IDs, known
and related finding/analysis/evidence/hypothesis/source edges, preservation of
input limitations, hypothesis evidence and relevant contradictions. It validates
references to unavailable analyses as context, without treating them as completed.
It does not prove that source wording supports a medical claim or independently
certify arbitrary externally authored recommendation prose. `run_planner` adds
its constrained-candidate generation guarantees. Human review must verify accepted
evidence claims, applicability, uncertainty and feasible next investigations.
Abstract-only evidence stays labelled. Metadata/search previews never become
accepted evidence. Source access/licence metadata stays with upstream sources.
Every report requires human review; nothing triggers experiments, protocol changes,
external messages, email or clinical decisions.

## Examples and offline checks

`fixtures/synthetic/planner_complete_input.json` and `planner_complete_output.json`
are a fully scripted synthetic software example, including a fabricated source.
`planner_partial_input.json` and `planner_partial_output.json` show an unassessed
upstream fallback with zero accepted evidence and a useful data-gap follow-up.
All four are explicitly synthetic; none is a real or live model/clinical result.
Both pairs pass schema and cross-record validation in tests.

```sh
uv sync --locked --extra dev
uv run --locked pytest -q tests/planner
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

No paid/live checks run by default. Offline tests cover selection/priorities,
source chains, contradictions, missing data, incompatible comparisons, review,
partial/unavailable status, rejection, continuation history, shared counters,
timeouts, bounded candidates and the complete/partial examples. Live planner
provider compatibility, real-world recommendation usefulness and the combined
cited clinical pipeline remain unverified.

## Integrated pipeline

Planning receives reserved turns/time before Agents 1–3 run; counters are not reset.
RunResult.planner_report is checked against its final PlannerInput on API/storage
boundaries. The UI displays actual planner events and output. Only the explicit
curated demo allows a longer configured shared budget and a labelled rules-based
candidate draft if model selection fails. Normal mode retains unavailable status.
The latest functional PK, representation, hypothesis and disposition checks are
preserved. Completed planning requires explicit dispositions; older partial saved
reports remain readable. See DEMO.md and verification/agent-4-fixes.md.
