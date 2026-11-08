# Agent 3 implementation and verification

Agent 3 is the External Evidence Investigator. It receives EvidenceRequest and
returns EvidenceReport without executing statistics or calling Agent 2 recursively.
Its Europe PMC client and Agent 1's registry adapter are wired into the default
runtime on feat/service-integration. See [integration verification](service-integration.md).
Agent 4 is deferred.

## What is implemented

- Model-selected publication searches, query refinement, publication inspection,
  opposing-evidence investigation and final structured reporting.
- Public Europe PMC core metadata/abstract search, exact metadata lookup and
  eligible open-access article-body retrieval.
- Shared registry search/inspection tools using Agent 1's existing Protocol. No
  duplicate registry client is implemented here; missing registry functionality
  becomes an explicit tool limitation.
- Actual successful and failed search attempts, retrieved sources, access levels,
  licences, hashes, timestamps and inspection locators.
- Final sources/searches assembled by application code, not invented by the model.
- A separate synthesis request sees only actual inspected passages, not the tool
  conversation. Its provider schema avoids recursive/untyped analysis dictionaries;
  optional suggestions are converted back to validated AnalysisRequest objects.
- Short exact excerpts checked against inspected passages. Uninspected previews,
  fake identifiers, wrong source locations and invented quotes are rejected.
- Abstract-only and metadata-only scope limitations. Metadata/title review can
  support background context, not a clinical safety inference.
- DOI/PMID/PMCID deduplication and warnings when inspected sources share an NCT ID.
- Suggested AnalysisRequests returned to Agent 2 for a decision; no Agent 3 maths.
- Bounded model/tool execution with the existing shared context and budget.

Provenance checking does not prove that a quoted passage entails a model's claim.
Study relevance, methods, effect interpretation and causality require researcher
review. A valid excerpt is a traceable basis for review, not clinical approval.

## Interfaces for the team

```text
app.agents.evidence.run_evidence(EvidenceRequest, ToolContext) -> EvidenceReport
app.services.europe_pmc.EuropePMCClient(budget, cache_dir=None, http_client=None)
```

The EuropePMCService Protocol is unchanged. The client implements:
- search_publications(query, page_size=5)
- fetch_publication_metadata(source, external_id)
- fetch_open_access_full_text(pmcid)

All three methods are async. The client constructor performs no IO. Pass the same
context.budget, not a new budget. http_client optionally injects an httpx client
for tests; its owner closes it. Default requests use a temporary managed client.

The normal runtime builds EuropePMCClient using its own run budget and
TRIALFAIR_DATA_DIR/cache/europe_pmc. It already dispatches run_evidence through the
existing evidence handler. Custom RuntimeServices passed by an integrator remain
respected. The default runtime now also wires Agent 1's registry and terminology
adapters and closes its shared run-owned HTTP client through context.aclose().

Do not append the EvidenceReport to context.evidence_reports inside Agent 3;
Agent 2's dispatcher validates and appends it once. Reports echo the request ID.
Sources contain actual retrieved metadata. Evidence IDs are namespaced per research
request by application code to avoid collisions between repeated model labels.
Evidence IDs and finding IDs must
resolve to the request and returned tool results.

## Budgets and failure behaviour

One research call uses at most four model turns from the existing shared budget
and reserves two available model turns for the outer Safety Investigator. It
allows up to three tool-selection turns plus a final structured-output turn.
At least three available local turns are needed for a search, inspection and report.
The last research turn exposes inspection tools only once candidates exist.
Unavailable registry tools are not offered to the model. This
is a bounded MVP investigation, not an exhaustive literature review.

Each tool turn accepts at most five calls; search page sizes are 1–5 and the
candidate pool is at most 20 distinct works. Publication inspection accepts returned source IDs or known retrieved PMID/PMCID/DOI
aliases and exposes one 12,000-character passage at a time with explicit offsets. Full articles are not
silently represented as entirely reviewed. If a requested full-text fetch is
unavailable, an existing abstract is inspected instead with an explicit fallback
limitation and partial status; the code never pretends to have read the body. Registry excerpts are also bounded.

HTTP requests use the hard remaining deadline, at most a 12-second network timeout,
no automatic retries/redirects and a 3 MB decoded-response limit. Each actual HTTP
attempt consumes external_request; cache hits do not. Search cache TTL is 24 hours.
Cached responses retain their original retrieval times and validated content hashes.
Caches are local, ignored by Git and not an assertion of redistribution permission.
A verified licence status means an explicit licence field was retrieved; it is not
an assessment of every downstream use.

Unavailable tools, low budgets or model errors retain source/search provenance and
return partial/unavailable instead of fabricating findings. No results never means
no risk. Fewer than two literature queries without retrieved contradictory evidence
is labelled an incomplete opposing-evidence search.

## Run the checks

From the repository root:

```sh
uv sync --locked --extra dev
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
```

If uv is not on PATH, use python3 -m uv. The installed environment can run tests
with `.venv/bin/python -m pytest -q` and Ruff with `.venv/bin/ruff`.
Ordinary tests use explicit synthetic source/model fakes, never live Gemini.
The inherited Starlette/httpx deprecation warning is not suppressed.

## Opt-in live verification

Your existing ignored .env should contain the actual authorised API key and model.
The shared model was smoke-tested with gemini-4-argon and google-genai 2.34.0.
No new key or model client is required. Never print or commit the key.

Check Europe PMC alone, with no paid model requests:

```sh
.venv/bin/python -m scripts.smoke_evidence --live --sources-only
```

Run the full Agent 3 research loop using real published literature and live Gemini:

```sh
.venv/bin/python -m scripts.smoke_evidence --live
```

The default is a research question about published human zolpidem exposure and
next-day impairment evidence. It is an example investigation, not advice to take
or change a medicine. You can override --drug, --symptom and --question together
for another research question. --query changes the sources-only check's query.

The CLI prints progress, actual search/source/evidence counts, duration, budget
use and limitations. It saves EvidenceReport to .trialfair/evidence-smoke.json.
A partial result is possible when registry access, source inspection or research
coverage is incomplete. Report status alone is not proof of scientific correctness.
No grounded evidence produces an unsuccessful smoke result, with limitations saved.
The default standalone input has no participant-level dataset for further analysis.

## Use from the dashboard

Restart the backend after changing branches/merging, then run the usual API/UI
commands in docs/agent-2-usage.md. Agent 2 now calls the real evidence implementation.
Use prepared screening with an actual drug/intervention and research question for
meaningful literature investigation. The existing synthetic missing-data fixture
has no real drug/trial and is not a realistic publication-search benchmark. Public
searches for its fictitious trial identifier are rejected.

Completed-trial input now runs the merged Agent 1 interpreter/statistics. JSON
result review is separate from live execution. Health reports the first three
agents present and the full four-agent pipeline partial.

## Actual verification so far

- Full suite: 110 tests passed before final documentation; 50 cover Agent 3 source,
  research and integration behaviour. See the handoff for final check results.
- The actual nested Agent 2 -> Agent 3 -> revised hypothesis path passes with
  injected synthetic publications/model responses, one shared budget and valid
  PlannerInput. Supporting and contradictory sources remain visible.
- The source API could not be reached from the coding sandbox's HTTP client.
- A real Europe PMC core response was independently retrieved through Chrome.
  The actual parser accepted two records with abstracts and returned their explicit
  cc by-nc licence metadata. That validates response shape, not claim interpretation.
- A subsequent live run returned two accepted, source-audited items with partial
  status. See [live verification and audit](verification/agent-3-live.md) for scope,
  limitations, scientific review notes and the preceding failed attempts.

Official source API reference: https://dev.europepmc.org/RestfulWebService
The implementation uses resultType=core for abstracts and the permitted
/{PMCID}/fullTextXML endpoint for open-access body text. Article-specific licences
and abstract/full-text access remain explicit.

## First live attempt and follow-up fix

The user-run initial research attempt reached Europe PMC and executed searches,
but returned zero evidence items: 6 successful searches, 20 retrieved sources,
4 model turns, 7 external requests and 57.1 seconds. Registry lookup was unavailable,
one publication inspection failed, and a generic final-report error prevented an
answer. This was not a successful source-grounded live investigation.

The follow-up fixes reserve the last research turn for inspection, hide unavailable
registry tools, accept aliases only for already-retrieved publications, explicitly
fall back to abstracts, and isolate final synthesis in a simpler provider schema
and fresh grounded context. Error categories/HTTP codes are exposed without raw
provider messages. The initial generic exception did not establish the exact
provider failure; live confirmation of the new path remains required.

Regression tests cover those paths. Rerun the same --live command and inspect both
evidence_items and cited_sources. Partial can be scientifically honest; no grounded
items still means this live smoke test has not passed.

## Schema-only check after the second live attempt

The next user-run attempt successfully inspected four passages but final synthesis
still returned ClientError HTTP 400: 3 search attempts, 5 sources, zero evidence,
4 model calls, 7 external requests and 88.94 seconds. Europe PMC 503/500 responses
also occurred; they are independent of the final model request rejection.

The provider response schema now uses flat required-only claim fields, without
optional clinical metadata branches, const schema-version fields, array bounds or
nested source locators. Local conversion still builds the unchanged EvidenceItem/
SourceLocator and all source, relation, excerpt and request checks remain enforced.
Optional study context belongs in relevance/limitations when supported; it is not
invented to fill structured metadata fields. The schema is inlined for transport.

Google documents schema complexity as a possible source of 400 errors:
https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/control-generated-output
The original generic error is insufficient to prove the precise rejected field.

Before another full research run, test only that exact schema:

```sh
.venv/bin/python -m scripts.smoke_evidence --live --schema-only
```

This makes one model request with synthetic input and no source searches. It
prints accepted=true when the provider accepts the schema and returns a valid
object. On rejection, only the provider's separately redacted validation message
is shown; no exception details, headers, prompts or credentials are dumped. This
explicit diagnostic is restricted to synthetic schema-check input.

If accepted, rerun the normal --live research check and inspect its evidence. A
successful schema probe is not proof of a successful research investigation.

## Latest live-check status

The compact schema probe passed. The subsequent real-literature run returned two
accepted items from two sources, after six inspections, in 132.81 seconds. Both
excerpts and metadata hashes were audited against the source cache. Status partial
is retained because the research remained abstract-only and incomplete. This is
bounded component verification, not full clinical or integrated-pipeline acceptance.
See [the audit](verification/agent-3-live.md), including a formulation comparison
that needs explicit source confirmation and the limited combined-run time budget.

The observed four rejected items have no per-item reasons recorded in that older
report. New runs include aggregate rejection reason codes without exposing raw
rejected claim text. Failed full-text requests are memoised only within their run.
