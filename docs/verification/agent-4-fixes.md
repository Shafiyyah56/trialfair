# Agent 4 functional fixes — 2026-11-08

Target: feat/agent-4-planner after merging reviewed main into 14bbd36.
The user authorised these four fixes and regression tests, with synthetic inputs
only and no push, PR creation/update or merge. Changes remain local/uncommitted.

## TDD evidence

First added tests/planner/test_functional_regressions.py (initially named
`test_regressions.py`): **23 failed, 5 passed** against the old implementation.
The initial red-run log is `/private/tmp/agent4-regressions-before.txt`.
The filename was made unique after full collection found a collision with the
existing interpreter test module; no interpreter tests/config were changed.
Added further scope/availability checks as part of verification. Final regression
suite: **32 passed**; all planner tests: **73 passed**.

Full suite: **289 passed, 1 live test deselected**. Ruff lint/format and whitespace
checks passed. The existing Starlette TestClient deprecation warning remains.
The first full run encountered the existing 100 ms evidence-timing test deadline
failure; that exact test passed in isolation and the full rerun passed without
modifying upstream code. This timing sensitivity remains a test limitation.

## Before/after and root causes

| Issue | Root cause / before | Corrected behaviour |
| --- | --- | --- |
| PK matching | Any sex-labelled PK row from a linked source made a specific PK gap available. AUC-only input satisfied Cmax. | Match each explicit requested parameter; all requested parameters must be present. Case/spacing normalisation preserves distinct parameters and AUC windows. Unspecified parameters with rows require review. Matching rows remain descriptive and their reported categories/limitations are retained. |
| Representation | No representation-specific candidate family; the generic evidence-gap fallback ignored supplied demographics. | Use exact reported counts/denominators and group/population context for representation, precision and recruitment-feasibility review. Retrieve only missing fields. No thresholds, adequacy conclusions, enrolment targets or pooling. |
| Hypotheses | A cross-finding evidence edge reset the entire hypothesis list, losing valid local hypotheses too. | Retain local/shared hypotheses and all their support/contradiction edges. Indirect evidence keeps original finding IDs and an applicability warning; validators only accept cross-finding links through a relevant hypothesis. Inspection returns the same evidence/source context used by the recommendation. |
| Completion | The public validator checked for at least one recommendation, not full finding coverage or disposition. | Every finding needs a valid typed disposition before completed planning. Further investigation references an actual related action; unresolved needs a rationale; resolved needs related accepted evidence/completed-analysis review support. Missing, duplicate, unknown, unrelated or unsupported dispositions are rejected. Completed planning may leave scientific questions explicitly unresolved. |

## Minimal shared interface change

Added only `PlannerFindingDisposition` and a defaulted
`PlannerReport.finding_dispositions` field. This provides explicit typed states
instead of extracting completion meaning from arbitrary narrative strings.
`PlannerInput`, Agents 1–3 payloads, RunResult, public function signatures,
schema_version 1.0 and dependencies remain unchanged.

Existing partial reports without dispositions remain valid. Older completed
planner outputs must supply dispositions before the stricter validator accepts
them. The complete synthetic fixture was updated. Generated plans do not claim
resolved scientific findings: selected findings require follow-up; unselected
findings remain unresolved and keep the bounded plan partial. External human
review can record resolved or explicitly unresolved planning dispositions.
Reference/structure checks do not certify the medical truth of review prose.

## Synthetic functional verification

Used fixtures/synthetic/phase1_agent4/planner_input.json: fabricated Phase I
compound, 36 aggregate participants (reported Female 6/Male 30), compatible nausea
counts 3/6 and 5/30, missing Cmax/PK data and fabricated opposing abstract evidence.
No actual patient records, clinical observations or publications are represented.
Source-file hashes and mock quoted excerpts were checked against local texts.

Ten scripted planner runs covered baseline; absent denominator; occurrences-only
counts; different reporting window; empty evidence; unregistered data; unsupported
dosing-field injection; AUC-only PK; overlapping hypotheses; and a controlled
completed review. Repeated all four functional scenarios with corrected assertions:

- AUC-only rows leave Cmax missing and preserve a future-data collection option.
- Existing 6/30 counts produce representation/precision review, not generic data
  collection; count labels/group context and missingness remain explicit.
- Both local PK and shared hypotheses, evidence edges and applicability limits
  survive; indirect evidence is not relabelled as direct support.
- Removing a follow-up action rejects a completed report. Recording a valid
  explicitly unresolved disposition permits completed review without a claim
  that scientific uncertainty disappeared.
- Missing participant denominators, event occurrences, mismatched windows and
  absent registration do not become executable AE comparisons. Zero accepted
  evidence stays empty. Unsupported dosing prose is rejected with no plan.

All generated outputs passed typed JSON round-trip and cross-reference checks.
Inputs were not mutated; planning consumed only the existing model_turn counter.
Outputs and the repeated audit summary are in
`/private/tmp/trialfair-agent4-fixed-check/`. The script is
`/private/tmp/trialfair-synthetic-data-check/check_fixed.py` and uses the earlier
scripted audit helper. Permanent regression tests do not depend on temporary files.

Also repeated the real-code interpreter/statistics -> safety -> evidence ->
PlannerInput -> planner exercise using injected synthetic literature and a scripted
model. Two accepted evidence items reached the planner; three recommendations and
partial status survived. The same context/deadline was used; model turns rose from
8 to 10. These are code-flow checks, not live or autonomous scientific reasoning.

## Files and scope

- app/agents/planner.py: candidate/inspection fixes and generated dispositions.
- app/contracts.py: additive Agent 4 disposition output model/defaulted field.
- app/validation.py: planner-only evidence-scope and disposition validation.
- tests/planner/test_functional_regressions.py: 32 synthetic regression cases.
- fixtures/synthetic/planner_complete_output.json: explicit follow-up disposition.
- fixtures/synthetic/phase1_agent4/: existing synthetic input/source corpus used
  by tests; its README now describes the corrected regression scope.
- docs/agent-4-usage.md, docs/integration.md, docs/handoffs/agent-4.md and this report:
  semantics, root causes, compatibility, verification and remaining limitations.

No Agents 1–3 code, model adapter, global budgets, runtime, API, storage, UI,
dependencies or lockfiles were changed. Existing untracked .vscode/ is preserved.
No paid calls, live-source requests, email, commit, push or PR operation occurred.

## Readiness and remaining limits

Ready for review of the independent Agent 4 corrections. Live Gemini tool/schema
compatibility, autonomous prioritisation and real-world scientific usefulness are
unverified. Default original-pipeline scheduling, reserved turns/time, API/storage
and UI integration remain integrator-owned follow-ups. The output contract change
and stricter validation for old completed payloads must be reviewed explicitly.
PK label matching is conservative: it normalises case/spacing rather than inventing
synonyms, parameter equivalences or sampling/population comparability. Representation
review does not calculate power, adequacy, thresholds or recruitment targets.
