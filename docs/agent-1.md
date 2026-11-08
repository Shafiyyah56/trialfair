# Agent 1 assignment

Branch: feat/agent-1-interpreter. Read AGENTS.md and the shared architecture first.
Implement the interpreter, registry client, terminology service and statistics.
Do not change shared schemas without agreement from the integrator.

Before implementation, read docs/HANDOFF.md and docs/TEAM_SETUP.md, acknowledge it in your first
response and update docs/handoffs/agent-1.md on your feature branch. Merge current
origin/main and (until merged there) origin/feat/agent-2-safety as described in the
handoff, install the committed lock with uv sync --locked --extra dev, and
record actual checks and blockers. Reuse the shared model adapter and contracts.

## Deliverables

Implement run_interpreter(TrialInput, ToolContext) -> ScreeningOutput and
execute_analysis(AnalysisRequest, ToolContext) -> AnalysisResult.

Fetch ClinicalTrials.gov API v2 records, preserve raw group IDs and source JSON
paths, and extract demographics, AEs and genuinely identifiable PK outcomes.
Handle no posted results and missing subgroup data as normal cases. Expose the
agreed related-trial search interface for Agent 3 to reuse.

Use Gemini to interpret natural-language symptoms and AE terms. Preserve negation,
uncertainty, timing, pre-existing symptoms and source wording. Use plain-language
normalisation unless a licensed vocabulary mapping is supplied. Never invent
MedDRA codes, counts, severity or causality. Permit context/terminology lookup for
ambiguous terms and return needs_review when unresolved.

Implement these deterministic tools only:
- summarise_representation: counts/proportions with real denominators and categories.
- audit_subgroup_availability: what the available sources do and do not report.
- compare_adverse_event_rates: compatible sex-stratified participant counts only;
  proportions, risk difference and an appropriate documented interval, exploratory
  Fisher exact test, risk ratio only when estimable, sparse-data and multiplicity
  limitations. Validate arm, population, endpoint and reporting window.
- summarise_pk_by_sex: comparable reported summaries with units/dose/formulation;
  no unsupported inference from insufficient summaries.

Return unavailable for unsupported confounder adjustment or patient-level models.
Baseline sex counts cannot supply sex-specific AE denominators. Event occurrences
cannot supply participants affected. No universal 50% enrolment target.

Register validated datasets under opaque context.datasets keys so later tools can
resolve them without arbitrary paths. Attach all analysis sources to TrialBundle.

## Validation and handoff

Add tests under tests/interpreter using a sourced public response when available
and labelled synthetic counts. Test absent subgroup data, sparse/zero counts,
incompatible denominators, occurrence-only events, negation and ambiguous terms.
Use independently specified numerical expectations. Do not run paid calls by default.

Return schema-valid ScreeningOutput, verify with validate_screening, and document
real-data limitations, commands, outputs and whether live calls were actually tested.
Do not implement a competing API, UI, Gemini client or Agent 4.
