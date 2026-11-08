# Agent 3 assignment

Branch: feat/agent-3-evidence. Read AGENTS.md and shared architecture first.
Own evidence.py, europe_pmc.py and tests/evidence. Reuse Agent 1's registry service.

Before implementation, read docs/TEAM_SETUP.md, acknowledge it in your first
response and update docs/handoffs/agent-3.md on your feature branch. Merge current
origin/main, install the committed lock with uv sync --locked --extra dev, and
record actual checks and blockers. Reuse the shared model adapter and contracts.

## Deliverables

Implement run_evidence(EvidenceRequest, ToolContext) -> EvidenceReport.
Implement the agreed EuropePMCService methods for search, metadata and permitted
open-access full text. Record titles, stable IDs, authors/year, URLs, retrieved
content, access level, hashes and licence metadata. Unknown licences remain unknown.
Cache repeated requests and bound results, timeouts and request counts.

The model should select a focused query, inspect results, refine weak searches,
look for contradictory findings or an alternative explanation, inspect selected
records and stop with supported conclusions or explicit unresolved questions.
Do not merely summarise the first fixed search response.

Approved tools: search_publications, inspect_publication, search_related_trials,
inspect_trial_record. Use the shared registry adapter for related trials.

Compare drug, formulation, dose, study design, population, endpoints and follow-up.
Animal/in-vitro evidence is not human clinical safety evidence. Class-level findings
are background unless applicability is justified. Pregnancy/reproductive safety
must not be substituted for the general sex-specific AE question.

Each EvidenceItem must link to an actual retrieved source with a short excerpt or
locator and a justified supports/contradicts/inconclusive/background relation.
Validate source identifiers and content support. Abstract-only review stays labelled
abstract-only. Do not fabricate titles, quotes, PMIDs or conclusions from unavailable
full text. No search results does not establish no risk or no evidence anywhere.

Deduplicate stable IDs and identify registry/publication overlap so one study is not
counted as independent replication. Preserve contradictory evidence. Suggested
AnalysisRequests go back to Agent 2; do not execute statistics or call Agent 2
recursively. Respect the one shared budget/deadline.

## Validation and handoff

Test support, contradiction, query refinement, irrelevant results, abstract-only
limits, duplicate sources, no results, unknown licences, service errors, fabricated
citations and exhausted budgets. Use deterministic HTTP/model fakes; live search is
opt-in. Document actual queries, sources, limitations and whether live calls ran.

Optional only after the core loop: source-backed JSON graph edges connecting trials,
findings, analyses and evidence. Do not invent biological relationships or add a
new graph database. Do not build Agent 4 or a competing UI/model client.
