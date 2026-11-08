# Agent 1: Trial Data Interpreter

## Public interfaces

- `app.agents.interpreter.run_interpreter(TrialInput, ToolContext) -> ScreeningOutput`
- `app.services.statistics.execute_analysis(AnalysisRequest, ToolContext) -> AnalysisResult`
- `ClinicalTrialsClient(client, budget, cache_dir=None, replay=False)` implements
  existing `fetch_trial(nct_id)` and `search_related_trials(query, page_size=5)`.
  Additive `fetch_cached_trial(nct_id)` never attempts HTTP, even on a live-capable
  client. `load_capture(raw_bytes, source_record)` registers a hash-verified capture
  with its original provenance. Replay interpreter runs require the cache-only
  entry point; adapters without it fail before their live fetch is called.
  The caller owns the injected `httpx.AsyncClient` lifetime and shared RunBudget.
- `SuppliedTerminology(mappings=None)` implements exact `lookup(text)` only.
  Mappings must be licensed/supplied and candidate source records must already
  appear in the bundle. Empty mappings are supported; no codes are guessed.

No shared schemas, dependencies, runtime, API or other agents were changed by
Agent 1. Agent 2's merged baseline supplies the single Gemini adapter and
`generate_with_budget`. All agents use the same budget; initial statistics do
not consume the dispatcher's additional-analysis allowance.

## Run

```sh
uv sync --locked --extra dev
uv run python -m app.agents.interpreter --bundle fixtures/synthetic/interpreter_counts.bundle.json
# Explicit live run: public HTTP plus potentially paid Gemini calls, configured in local .env
uv run python -m app.agents.interpreter --nct-id NCT04280705
```

The offline demo explicitly loads synthetic data in replay mode. It does not
substitute a fake model: interpretation is unavailable and flagged for review.
Its four analyses include 20/100 versus 10/100 synthetic participant counts,
risk difference 0.1, risk ratio 2, Newcombe/Wilson 95% difference interval and a
two-sided Fisher test. These are demonstration data, not clinical observations.
The real captured registry response has baseline sex counts but no extracted
sex-specific AE participant counts. Those baseline counts are never used as AE
denominators. Unassessed extraction produces a source-review gap, not a claim
that the registry or sponsor never reported subgroup data. The audit validates
actual comparison preconditions and distinguishes missing, unassessed, incomplete,
incompatible, available and not-applicable inputs in its JSON results.

Tool parameters are `{}` for summaries/audits, or `{"row_ids": ["row-a", "row-b"]}`
for explicit row selection. Only opaque keys already registered in
`context.datasets` resolve. Paths, executable expressions, duplicate row IDs and
unknown fields are invalid. The interpreter emits its registered dataset key in
the final stop event. Additional results echo request_id but are appended only by
Agent 2's dispatcher. Unsupported tool names are rejected by the shared contract.

## Participant-level data (SDTM-style DM/AE CSV)

`app.services.participant_data.load_participant_dataset(dm_path, ae_path, *,
is_synthetic, title=None, narratives_path=None) -> TrialBundle` derives aggregate
rows deterministically from one-row-per-participant `dm.csv` (STUDYID, USUBJID,
SEX, ARMCD, ARM, RFXSTDTC; ACTARMCD/ACTARM used when supplied) and
one-row-per-record `ae.csv` (STUDYID, USUBJID, AEDECOD, AESER, AESTDTC; optional
AETERM). An optional `narratives.csv` needs a TEXT column.

```sh
uv run python -m app.agents.interpreter --participant-dir path/to/dir --synthetic
# Live interpretation with the configured model (paid):
uv run python -m app.agents.interpreter --participant-dir path/to/dir --synthetic --with-gemini
```

Rules: safety population = participants with a first-dose date in a treated arm;
treatment-emergent = onset on/after first dose (same day included); pre-existing,
missing/partial onset and non-safety-population records are excluded and counted
in limitations, never treated as zero. participants_affected counts unique
participants; event_occurrences counts records. Serious/non-serious rows are
separate. SEX is decoded only through the CDISC SEX codelist; other values are
preserved and kept as separate categories, never merged into Female/Male. Zero
cells assume complete AE capture for treated participants. Counts use AEDECOD;
verbatim AETERM and narratives are interpretation inputs only and never alter
counts. CSV only, 10 MB per file, duplicate USUBJID rejected, one STUDYID.

## Participant-level PK, exposure-response and QTc

Optional files in the same `--participant-dir` are picked up automatically:

- `pp.csv` (STUDYID, USUBJID, PPTESTCD, PPSTRESN, PPSTRESU; one visit per file).
  AUCIFO/AUCINF/AUCLST/AUCTAU/CMAX become per arm x sex geometric-mean PKRows.
- `eg.csv` (STUDYID, USUBJID, EGTESTCD, EGSTRESN, EGBLFL). QTCF records with exactly
  one baseline (EGBLFL=Y) give each participant's maximum post-baseline value and change.

Per-participant values are kept only in server memory. These tools use them:

- `summarise_pk_by_sex`: also reports within-arm Female/Male geometric mean ratios with
  Welch 95% CIs on log values. Ratios are never computed from aggregate summaries alone.
- `exposure_response` (`{"term": "<AEDECOD>", "exposure_parameter": "AUCIFO"}`): runs
  logistic regressions of AE on exposure (placebo = 0), on sex, and on exposure plus
  sex. Compare the female odds ratio before and after exposure adjustment. Separation
  or non-convergence makes that model unavailable; sparse events are flagged.
- `summarise_qtc_by_sex` (`{}`): reports mean maximum QTcF change by arm and sex,
  ICH E14 categorical counts (>450/480/500 ms; increase >30/60 ms), Female/Male
  comparisons, and a linear concentration-QTc model with a sex interaction (uses Cmax).

Screening now runs these automatically when the data exists. Findings were also
reprioritised. A Female/Male AE comparison becomes a `potential_signal` only when its
95% CI excludes zero, and it states the multiplicity. The remaining comparisons are
summarised in one `evidence_gap` finding: "No conclusive Female/Male difference in N
of M comparisons". All analyses are exploratory and unadjusted for body size.

## Interpretation flow

Texts identical apart from letter case and whitespace (within the same kind:
narrative vs reported AE term) are judged once; every entry still receives its own
SymptomMapping with its exact original wording and locator. Punctuation and
wording are never normalised. The model returns only judgements (term, assertion,
temporality, severity, attribution, needs_review, explanation); Python attaches
original text and locators. One structured call handles the batch (default 20
distinct texts; TRIALFAIR_MAX_INTERPRETATION_TEXTS accepts 1–100). Only texts the model flags for review get one bounded follow-up
in which the model may select source_context or terminology_lookup; if that fails,
first-pass judgements are kept and remain flagged. Unverified terminology codes,
missing/duplicate/invented entry IDs and unsupported tools are rejected.

## Source handling and scientific limits

The adapter's consumed field types were checked against the official
[OpenAPI specification](https://clinicaltrials.gov/api/oas/v2), version 2.0.5,
and [field metadata](https://clinicaltrials.gov/api/v2/studies/metadata).
Typed adapter models validate the consumed identity, baseline, AE and outcome
subtrees; this is not full validation of every field in the registry schema.
Extra fields remain in the exact raw cache. Cache entries include original UTF-8
response, SHA-256 and retrieval metadata; cache reads verify the hash and retain
the original retrieval time. `cache_hits` exposes reused trial IDs. Related-trial
searches are cached in memory; replay search without a captured result is unavailable.
Cache directories must be server-controlled and should not contain sensitive uploads.

Preserved JSON paths locate measurements/stats; AE terms are retained in locator
excerpts. Baseline class denominators override measure and module denominators.
Continuous baseline measures are not misrepresented as counts. Overlapping total
and arm groups are never pooled. Group titles do not establish sex strata, and
registry group IDs are not joined across baseline and AE modules.

AE comparisons require explicit Female/Male participant counts, the same group,
intervention (including recorded dose details), population, endpoint, seriousness
and reporting window. Different group IDs are conservatively unavailable even
when a human might later establish compatibility. Other sex/gender categories
remain reported descriptively. No arbitrary clinical threshold, universal 50%
representation target, continuity correction, adjusted model or interaction test
is introduced. Potential signals are low-priority descriptive review candidates;
non-significance does not establish equivalence or safety.

PK recognition is deliberately narrow: explicitly named Cmax/Tmax/AUC outcomes
with concentration/exposure/PK context and units. Non-numeric summaries and
ambiguous outcomes require review. Explicit Sex/Gender class categories may be
preserved; group names never manufacture sex labels. Dose/formulation are not
inferred. Contract v1.0 lacks population and sampling-window fields, so PK ratios
are withheld; reported summaries remain available. Group/class participant counts
are not assigned to Sex/Gender category measurements as subgroup sample sizes.
Reported uncertainty is retained in `variability` as a JSON string with the original
`dispersionType`, `spread`, `lowerLimit` and `upperLimit` values when supplied.
No individual exposure or inferential PK statistics are manufactured.

A descriptive PK ratio is scientifically possible without changing the JSON
contracts *if* trusted source inspection separately establishes comparable
population, sampling window, endpoint, summary statistic, dose, formulation and
units. A positive reference value is also required. Sample sizes or SDs are not
needed for a purely descriptive ratio, but cannot be fabricated to support inference.
`PKRow` alone does not establish all those facts: matching group IDs and numbers
are insufficient. SourceLocator permits later retrieval of that context, but the
current tool has no verified source-context resolver for PK comparisons. Therefore
it still returns `descriptive_ratio=null` rather than accepting model-supplied
compatibility claims. This original requirement remains incomplete; it is not
mathematically impossible and does not inherently require a contract change.

Narrative sources hash exact UTF-8 text. Reusing an upload source ID for different
text is invalid. Model extraction preserves original text and locators exactly;
only codes returned by supplied terminology tools with registered sources are
accepted. Negation/temporality interpretation still requires model and human
review: deterministic fakes verify interface behaviour, not model accuracy.
The batch uses the configured text limit; excess entries remain in source rows
and are flagged for review. First-pass interpretation and refinement also have
local time limits to leave time for downstream research/reporting; see
service-integration.md. Failed/budget-limited interpretation returns uncertain,
needs_review mappings without guessed terms. SDK API/transport errors also retain
completed statistical work; error events do not expose provider messages. External
task cancellation still propagates. Narrative and registry-AE tool IDs use separate
namespaces, so user entry IDs cannot overwrite AE entries. No hidden reasoning or raw narratives
are emitted in activity events. Registry/model/source text cannot grant new tools.

## Verification

```sh
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
# Explicit paid model test, excluded by default:
TRIALFAIR_RUN_LIVE_INTERPRETER=1 uv run python -m pytest -m live tests/interpreter/test_live.py -q
```

The live test uses synthetic narrative input and the configured shared ModelClient.
On 2026-11-08 it passed against actual gemini-4-argon (google-genai 2.34.0) in
14.76 seconds: three successful responses, one model-selected tool call and one
structured output. The synthetic negation was mapped to absent dizziness without
a review flag; shared contracts and provenance validation passed. Independent
synthetic statistics were unchanged before/after inference. See the Agent 1 handoff
for scope. Ordinary tests still use HTTP/model fakes; this narrow live result does
not establish general model accuracy or full multi-agent clinical integration.

## Integrator follow-up

Agent 2 should wire `ClinicalTrialsClient` and `SuppliedTerminology` into its
context factory after creating the shared budget, and manage HTTP client lifetime.
Agent 3 reuses this registry client. Default API MissingService wiring remains
unchanged and must not be described as a ready live pipeline. Agent 2 should
propagate interpreter-incomplete limitations to run-level partial status; the
current ScreeningOutput contract has no status field. Source IDs resolving and
Pydantic validation do not prove scientific support.

## Pre-merge regression status

Five review defects are fixed in Agent 1. The sixth, run-level partial status,
cannot be enforced by the current ScreeningOutput contract and unchanged
orchestrator. A strict expected-failure regression demonstrates that an incomplete
interpreter can still be followed by a completed investigation/run. This is a
known merge blocker, not a passing acceptance check. Run it without the marker:

```sh
uv run python -m pytest --runxfail tests/interpreter/test_regressions.py::test_incomplete_interpretation_must_make_run_partial -q
```

That command currently fails at the expected `completed` versus `partial` assertion.
Fixing it requires an integrator-owned status propagation change. No budget
manipulation, forced failure, monkeypatching of production code, or disabling
Agent 2 is used to conceal it. Runtime service wiring and live verification remain
pending; do not describe this branch as a ready complete live pipeline.
