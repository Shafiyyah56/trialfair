# Agent 1: Trial Data Interpreter

## Public interfaces

- `app.agents.interpreter.run_interpreter(TrialInput, ToolContext) -> ScreeningOutput`
- `app.services.statistics.execute_analysis(AnalysisRequest, ToolContext) -> AnalysisResult`
- `ClinicalTrialsClient(client, budget, cache_dir=None, replay=False)` implements
  existing `fetch_trial(nct_id)` and `search_related_trials(query, page_size=5)`.
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
denominators. Missing subgroup evidence produces an evidence-gap finding.

Tool parameters are `{}` for summaries/audits, or `{"row_ids": ["row-a", "row-b"]}`
for explicit row selection. Only opaque keys already registered in
`context.datasets` resolve. Paths, executable expressions, duplicate row IDs and
unknown fields are invalid. The interpreter emits its registered dataset key in
the final stop event. Additional results echo request_id but are appended only by
Agent 2's dispatcher. Unsupported tool names are rejected by the shared contract.

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
are withheld; reported summaries remain available. No individual exposure or
inferential PK statistics are manufactured.

Narrative sources hash exact UTF-8 text. Reusing an upload source ID for different
text is invalid. Model extraction preserves original text and locators exactly;
only codes returned by supplied terminology tools with registered sources are
accepted. Negation/temporality interpretation still requires model and human
review: deterministic fakes verify interface behaviour, not model accuracy.
The batch is bounded at 100 entries; excess entries remain in source rows and are
flagged for review. Failed/budget-limited interpretation returns uncertain,
needs_review mappings without guessed terms. No hidden reasoning or raw narratives
are emitted in activity events. Registry/model/source text cannot grant new tools.

## Verification

```sh
uv run python -m pytest -q
uv run ruff check .
uv run ruff format --check .
# Explicit paid model test, excluded by default:
TRIALFAIR_RUN_LIVE_INTERPRETER=1 uv run python -m pytest -m live tests/interpreter/test_live.py -q
```

The live test uses synthetic narrative input and configured shared ModelClient;
it has not been run by Agent 1. Ordinary tests use HTTP/model fakes. Public HTTP
fixture retrieval was performed; this is not a live model or full-pipeline test.

## Integrator follow-up

Agent 2 should wire `ClinicalTrialsClient` and `SuppliedTerminology` into its
context factory after creating the shared budget, and manage HTTP client lifetime.
Agent 3 reuses this registry client. Default API MissingService wiring remains
unchanged and must not be described as a ready live pipeline. Agent 2 should
propagate interpreter-incomplete limitations to run-level partial status; the
current ScreeningOutput contract has no status field. Source IDs resolving and
Pydantic validation do not prove scientific support.
