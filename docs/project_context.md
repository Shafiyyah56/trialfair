# TrialFair project context

## User and purpose

The user is a pharmaceutical safety researcher analysing a completed clinical
trial before a subsequent trial phase, particularly Phase I to Phase II. TrialFair
should surface potentially overlooked sex-specific safety risks and gaps in the
available evidence, investigate them collaboratively and support human review.

## Current scope

1. Trial Data Interpreter: interprets natural-language symptoms and AE terminology,
   preserves ambiguity and provenance, and prepares data for conventional Python
   statistical screening.
2. Safety Investigator: prioritises findings, forms and challenges hypotheses,
   requests additional valid analyses and incorporates external evidence.
3. External Evidence Investigator: autonomously refines literature/related-trial
   searches, evaluates supporting and contradictory findings and returns sourced
   evidence and unresolved questions.
4. Trial Improvement Planner: consumes PlannerInput and produces PlannerReport
   for human review. Full orchestration/API/storage/UI integration is available on
   feat/demo-integration. Live scientific/provider readiness remains unverified.

The first stage is partly agentic. All arithmetic and inferential analysis remain
ordinary reproducible Python operations. An LLM interpreting symptoms cannot
manufacture event counts or patient-level records.

## Data realism and reliability

Use real public ClinicalTrials.gov results and published literature as the
foundation. Individual-patient PK and AE measurements may be unavailable.
Synthetic examples can demonstrate advanced analysis but must remain labelled.
A missing subgroup analysis in an available record is an evidence gap, not proof
that no analysis exists elsewhere or proof of differential harm.

Distinguish associations, hypotheses and causal evidence. Preserve uncertainty,
limitations, event denominators, source locations and data licences. Hypotheses
about exposure, target engagement or tissue distribution need actual evidence.
No automated clinical decisions or patient-specific doses are in scope.

## Hackathon demonstration

Show working software, real inputs, live model-selected tool use and a verification
loop in under three minutes. Aim for an end-to-end run deadline of 150 seconds.
Show readable decision summaries, not hidden model reasoning. Clearly identify
cached source responses, replay mode, model identity and partial results.

Judge-oriented design priorities supplied by the user are biological plausibility,
a named user and affordable next investigation, traceable licensed data, honest
evaluation and an opening explanation understandable without specialist biology.
Judge biographies and predictions have not been independently verified.

The supplied builder guide discusses connected modalities for a prize. A second
modality has not been selected for this MVP; multiple text agents or ordinary
charts alone must not be advertised as multimodal reasoning.

Temporary hackathon accounts may expire soon after the event. Preserve code and
non-sensitive assets outside them. Keep keys out of source control. Model IDs and
SDK examples in provided documents require verification against the actual account.

## Out of scope

Endometriosis drug discovery, candidate ranking, AlphaFold structure display,
patient diagnosis, prescribing, autonomous phase-progression decisions, full lab
planning, user accounts, billing, voice and generative media are not initial tasks.
