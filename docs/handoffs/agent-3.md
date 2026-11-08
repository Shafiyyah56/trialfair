# Agent 3 acknowledgement and handoff

Status: ACKNOWLEDGED. Implementation and nested integration tests pass. A real
literature/Gemini smoke run returned two source-audited items with partial status.
Agent 1 and full real-trial integration remain pending.

## Startup and branch

I read AGENTS.md, HANDOFF.md, TEAM_SETUP.md, my assignment, README, project context,
architecture and contracts. Work is on feat/agent-3-evidence, starting from 8ea532c
with the shared Agent 2 implementation. No Agent 1 implementation file or shared
scientific contract was changed. This acknowledges Agent 3 only.

Fresh fetch/push from the coding sandbox failed due to restricted networking.
The user's Terminal can reach the model/source APIs. Existing credentials were
not overwritten, printed or committed. The unrelated untracked uv 2.lock duplicate
was left untouched.

## Public interfaces and ownership

- app.agents.evidence.run_evidence(EvidenceRequest, ToolContext) -> EvidenceReport.
- app.services.europe_pmc.EuropePMCClient(budget, cache_dir=None, http_client=None),
  implementing the unchanged EuropePMCService Protocol: search_publications,
  fetch_publication_metadata and fetch_open_access_full_text (all async).
- app/runtime.py creates the real Europe PMC adapter with the same run budget and
  configured ignored cache. Explicit RuntimeServices injection is respected.
  Registry/terminology still use Agent 1's interfaces; no duplicate client exists.
- API readiness and UI wording reflect the implemented evidence component and
  outstanding Agent 1 work. No planner output is implemented.

## Behaviour and integration requirements

The model selects searches, refines weak queries, inspects sources and synthesises
claims. The last research turn is reserved for inspection. Search attempts, actual
sources, access/licence metadata, hashes, dates and exact passages are retained.
Registry tools are hidden when MissingService.is_available=False.

Final generation uses the compact flat required-only provider schema. Its transport
claims are converted into unchanged EvidenceItem/SourceLocator models and checked
against actual inspected passages. Invalid relations, sources, excerpts or finding
references remain rejected. Valid excerpts establish provenance, not full semantic
entailment, clinical causality or regulatory approval.

Agent 2's dispatcher validates/appends the returned report once. Agent 3 does not
append it itself, reset the shared budget, execute statistics or call Agent 2
recursively. Suggested analyses return as validated AnalysisRequest objects for
Agent 2 to decide. IDs are namespaced per request to avoid collisions.

Full-text failure explicitly falls back to an available abstract, preserving its
scope and partial status. Failed body requests are not repeated for that source
within the same run. Missingness and search failure never become proof of safety.
Cache hits retain original retrieval times. No hidden SDK retries or fake replay.

Restart the backend after merging so imported handlers use this implementation.
Read docs/agent-3-usage.md for exact constructor and runtime details. Merge the
feature branch/updated main rather than copying only evidence.py and omitting wiring.

## Actual verification

- Locked offline dependency sync and lock consistency passed; no dependency changes.
- Full suite: 110 tests passed, including 50 evidence tests; one inherited
  Starlette/httpx deprecation warning. Ruff lint/format and whitespace checks pass.
- Injected tests exercise the actual Agent 2 -> Agent 3 -> revised hypothesis path,
  source transport/cache/error handling, supporting/contradicting evidence,
  deduplication, quote rejection, budget cancellation and valid PlannerInput.
- The user-run compact schema probe returned accepted=true for gemini-4-argon,
  1527 schema bytes, one model turn. Earlier schema-rejected runs are not counted
  as successes.
- The subsequent user-run research returned two accepted items from two cited
  sources, six inspected passages, 132.81 s and partial status. Both accepted
  excerpts and their metadata hashes were checked against the actual source cache.
- See docs/verification/agent-3-live.md for the source audit, unverified formulation
  comparison, rejected-item limits and exact live-check history.

The latest small changes add rejection reason counts, failed-body memoisation and
a prompt rule against inferring release formulation from dose/route. Automated
checks cover them; the earlier observed live run is not relabelled as their live test.

## Remaining acceptance work

1. Human-review scientific meaning and source comparability. Abstract grounding
   does not substitute for full-text review. A formulation comparison in the
   observed report needs explicit source confirmation, as noted in the audit.
2. Implement/wire Agent 1 registry, terminology, ingestion and deterministic tools.
3. Run a real completed NCT record through all three agents and verify the combined
   report, contradictions, uncertainty, failure handling and shared deadline.
4. Measure integrated latency: the 132.81 s standalone research run leaves little
   time for other stages. No integrated timing success is claimed.
5. Implement Agent 4 only after stable actual outputs are available.

Optional repeat checks (not ordinary automated tests):
- Sources only: .venv/bin/python -m scripts.smoke_evidence --live --sources-only
- Schema only: .venv/bin/python -m scripts.smoke_evidence --live --schema-only
- Research: .venv/bin/python -m scripts.smoke_evidence --live

The original synthetic missing-data fixture has no real drug/trial and is not a
publication-search benchmark. The optional knowledge graph remains deferred.
