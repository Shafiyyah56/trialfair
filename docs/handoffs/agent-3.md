# Agent 3 acknowledgement and handoff

Status: ACKNOWLEDGED; standalone and nested implementation tested. Full live Agent 3
research verification is not yet claimed. Agent 1 remains an integration dependency.

## Startup acknowledgement

I read AGENTS.md, docs/HANDOFF.md, TEAM_SETUP.md, my assignment, README, project
context, architecture and contracts. I implemented Agent 3 on feat/agent-3-evidence,
starting from 8ea532c after fast-forwarding the shared Agent 2 work. I own the
research agent, Europe PMC adapter and evidence tests. I reuse the shared model,
generate_with_budget, ToolContext and the existing registry Protocol. No separate
Gemini client, registry adapter or statistics engine was introduced. This is not
an acknowledgement on behalf of Agent 1.

- Fresh fetch failed because github.com DNS was unavailable to the coding sandbox.
- Locked offline sync passed; scientific contracts and dependency lock are unchanged.
- Existing local credentials were not overwritten, printed or committed.
- Agent 2's earlier live model compatibility is recorded separately; it does not
  establish that Agent 3 has completed a live literature investigation.

## Files and public interfaces

- app/agents/evidence.py: run_evidence(EvidenceRequest, ToolContext) -> EvidenceReport.
  Bounded adaptive tool selection and query refinement; inspected-source grounding;
  source-assembled reports; abstract/full-text limitations; contradiction support;
  duplicate/overlap handling; suggested analyses and explicit partial/unavailable.
- app/services/europe_pmc.py: EuropePMCClient(budget, cache_dir=None, http_client=None).
  Implements the unchanged EuropePMCService Protocol for core searches, exact
  publication lookup and permitted open-access full text. Preserves DOI/PMID/PMCID,
  authors/year, hashes, dates, licences and access level. Bounded, allowlisted,
  cached requests with no implicit retries or redirects.
- tests/evidence: source transport tests, research behaviour tests and actual nested
  Agent 2/3 integration with injected synthetic literature/model results.
- scripts/smoke_evidence.py: explicit --live check, optional --sources-only, progress
  output and a saved report under ignored .trialfair/evidence-smoke.json.
- docs/agent-3-usage.md: source/runtime interfaces, limits, verification and commands.

Shared runtime changes included to make this component usable:
- app/runtime.py constructs EuropePMCClient with the existing per-run budget and
  ignored cache directory. Existing explicit RuntimeServices injection is respected.
- app/api.py marks evidence implementation present; the pipeline stays partial.
- Dashboard status text now says Agent 1 ingestion/registry are still required.
- Documentation records the integration point and updated component readiness.
- No Agent 1 implementation file or scientific payload schema was changed.

## Important integration rules

- Do not append the final report into context.evidence_reports inside Agent 3;
  Agent 2 validates and appends it once. Return the original request_id.
- Final sources and actual search attempts are assembled from tool state, not from
  model-written source metadata. A cited excerpt must match an inspected passage.
- Exact excerpt matching checks provenance, not semantic entailment or clinical
  validity. Researchers must review relevance, methods, effect sizes and claims.
- Evidence IDs are application-namespaced by request so repeated model labels do
  not collide when Agent 2 makes multiple investigations.
- Suggested analyses remain suggestions; Agent 2 decides and executes allowed tools.
- Registry tools use context.registry. Agent 1 must implement and wire it; Agent 3
  never substitutes a separate fake/live registry service.
- Runtime wiring for Europe PMC is included. Restart the backend after merging so
  handlers point to the new implementation. Merge the feature branch/main rather
  than manually copying only evidence.py and losing the service wiring.

## Actual verification on 2026-11-08

- Locked offline dependency sync: passed.
- Full pytest suite: 108 passed, one inherited Starlette/httpx deprecation warning.
- Agent 3-specific tests: 48 cover source, research and nested integration behaviour.
- Ruff lint/format and lock consistency: passed; no dependency changes.
- Documentation links and diff whitespace checks: passed.
- A real Europe PMC core response was retrieved through Chrome and parsed by the
  actual adapter's record parser: two abstracts and explicit cc by-nc metadata.
  The query was TITLE:zolpidem AND (sex OR gender) AND (pharmacokinetics OR impairment).
  The response remains under ignored .trialfair/verification; no article content
  was committed or presented as a verified clinical finding.
- Direct sources-only CLI request from the coding sandbox failed with
  LiteratureUnavailable. Live HTTP/Gemini execution from that environment is not
  established. Chrome access does not mean the command-line HTTP client can connect.
- No full live Agent 3/Gemini result is claimed unless recorded in a subsequent
  verification entry from the actual user's environment.

## Remaining work and acceptance

1. Run `.venv/bin/python -m scripts.smoke_evidence --live --sources-only` from the
   repo root in a network-enabled Terminal.
2. Run `.venv/bin/python -m scripts.smoke_evidence --live` for the actual Gemini
   investigation. Review .trialfair/evidence-smoke.json, not just its status label.
3. Verify relevance, short excerpts, contradictions, access/licence metadata and
   independent-study counts. A partial result may truthfully reflect limited
   coverage or missing registry access. Do not replace it with hardcoded evidence.
4. Implement/wire Agent 1; test real trial ingestion, valid statistics, actual
   literature investigation and the combined report under the shared deadline.
5. Measure real end-to-end latency and keep uncertainty visible before Agent 4.

The synthetic missing-data fixture has no real drug/trial and is not a realistic
literature-search benchmark. It remains useful for contract/error-path tests.
The optional knowledge graph was deferred in favour of a working grounded loop.
The unrelated untracked uv 2.lock duplicate was left untouched.

## Initial live failure and corrective follow-up

The user supplied an initial actual run with live gemini-4-argon: 6 successful
literature searches, 20 source records, zero evidence items, 4 model turns,
7 external requests and 57.1 seconds. The result was partial and the CLI correctly
reported no source-grounded evidence. This does not count as a successful live
research check. The saved report confirmed these counts; the failed artifact was
preserved under ignored .trialfair/verification before retry.

Inspection showed the final research turn was spent searching rather than reading
and exceptions were too generic to diagnose the exact final provider failure.
Corrective changes:
- Reserve the last research turn for source inspection and require enough shared
  turns to search, inspect and synthesise.
- MissingService declares is_available=False; unavailable registry tools are hidden.
- Resolve PMID/PMCID/DOI aliases only within the actual retrieved publication pool.
- If full text is unavailable, inspect an existing abstract with an explicit
  fallback limitation. No body review is claimed.
- Final synthesis is a fresh, no-tool extraction over exact inspected packets,
  using EvidenceSynthesis without recursive/untyped analysis parameter schemas.
  Analysis suggestions are converted back to the unchanged shared AnalysisRequest.
- Record safe error classes, field locations and HTTP status codes, never provider
  error text, URLs or credentials. The original provider failure is not asserted
  as conclusively diagnosed from the old generic log.
- CLI now prints synthesis passage count and cited-source count.

Current automated verification: 108 tests pass, including 48 evidence tests. The
new regressions cover inspection reservation, abstract fallback, alias resolution,
provider schema shape, safe final-error diagnostics and unavailable registry tools.
The full live check needs a rerun of the same smoke command; it is not yet marked
passed. No findings were hardcoded or fabricated to make the smoke test succeed.

## Second live failure and compact transport schema

The user reran research: four passages were inspected, but final synthesis failed
with ClientError HTTP 400. The run had 3 search attempts, 5 sources, zero grounded
items, 4 model turns, 7 external requests and 88.94 seconds. HTTP 503/500 responses
from Europe PMC were recovered with limited results/abstract fallback; they do not
explain the model's final schema rejection. This live test is not marked passed.

The provider-only synthesis transport now uses flat, required-only fields and no
array cardinality bounds/optional clinical metadata branching. References are
inlined before transport. The returned claims still become EvidenceItem through
Pydantic and retain all exact-quote, source, finding-ID and relation checks. Invalid
claims are rejected without discarding other valid claims. Public contracts and
Agent 1 analysis interfaces are unchanged.

scripts/evidence_schema_check.py implements a one-call --schema-only path in the
existing smoke CLI. It sends synthetic input and no papers, and can report an
explicitly redacted provider validation message without exposing exception details
or secrets. Regression checks verify flat required schema shape, retained local
scientific validation and diagnostic key/URL redaction. Current full test count:108.

Next live validation: run the --schema-only command first. If accepted, rerun
--live and review actual grounded claims. Full live Agent 3 success remains pending.
