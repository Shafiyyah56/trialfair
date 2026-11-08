# Agent 3 live verification and evidence audit

## Result

The user-run real-literature smoke check returned two accepted evidence items from
two cited sources using gemini-4-argon. Final synthesis succeeded. Status remained
partial with explicit abstract-only access, unavailable registry and rejected-item
limitations. This is a successful bounded component smoke check, not full clinical
validation, an exhaustive review or a completed multi-agent trial investigation.

Reported metrics: 5 searches, 20 retrieved source records, 6 inspected passages,
2 accepted items, 2 cited sources, 4 model turns, 8 external requests, 132.81 seconds.
The report request ID is 36bd9cd2-8f26-4289-9ef7-af834200c21b. Retrieved source records
are dated 2026-11-08. Source counts are not independent-study counts.

## Audit against actual source responses

The assistant inspected the saved report and the matching raw Europe PMC cache.
For each accepted item, the original record was found using its exact canonical
JSON content hash. Both quoted excerpts occur verbatim in the normalised abstract:

| Source | Access inspected | Excerpt length | Verification |
| --- | --- | --- | --- |
| [PMID 34580385](https://pubmed.ncbi.nlm.nih.gov/34580385/) | Abstract | 230 characters | Metadata hash and exact excerpt matched the retrieved response; PubMed abstract also checked. |
| [PMID 42088939](https://europepmc.org/article/MED/42088939) | Abstract | 150 characters | Metadata hash and exact excerpt matched the retrieved Europe PMC response. |

The first item's principal summary agrees with its abstract and preserves small-
sample uncertainty. The second is correctly labelled background and states that
sex-stratified results were not provided in the inspected abstract. Neither item
establishes general safety equivalence or justifies a patient-specific dose.
The accepted relation labels are inconclusive and background; no direct supporting/
contradicting pair was established in this particular live run. That interaction
continues to be covered by injected integration tests.

One comparison phrase in the second item's relevance refers to immediate-release
healthy-volunteer studies. The two cited abstracts do not establish that release
formulation for the oral single-dose comparison. Treat that phrase as unverified
unless another inspected source explicitly supports it. The synthesis prompt was
subsequently tightened to prohibit inferring formulation from dose or oral route.
The original observed report was not edited to hide this review finding.

## Rejected items and limits

Four proposed items were rejected by source/excerpt/reference checks. The observed
report recorded only the aggregate count, so their individual rejection reasons
cannot be reconstructed from that file. Subsequent code reports safe reason counts
for source, locator, excerpt, finding-reference, duplicate-ID and metadata-scope
failures. The original validation criteria were preserved, not loosened.

Full-text retrieval returned HTTP 500, so the agent explicitly used abstracts.
Repeated failed full-text requests are now remembered only within the same run,
preventing repeated requests for the same unavailable body; future runs can try
again. No measured speed improvement is claimed from that follow-up change.

The standalone run took 132.81 seconds against a 150-second backend deadline. A
combined Agent 1/2/3 run still needs real-input testing and latency allocation;
this measurement does not prove the combined application meets its demo target.

## Verification history

| Check | Observed outcome |
| --- | --- |
| Initial research run | 6 searches, 20 sources, zero accepted items, 57.1 s. Failed live evidence check. |
| After inspection/fallback fix | 4 passages inspected, zero items, final synthesis HTTP 400, 88.94 s. Failed live evidence check. |
| Compact schema-only probe | Accepted=true; schema 1527 bytes; one model turn. No literature search. |
| Real-literature run after compact schema | Two accepted, audited items; 132.81 s; partial with declared limitations. |

The observed live run used the compact transport checkpoint. Subsequent changes
add rejection diagnostics, per-run failed-body memoisation and the formulation
prompt constraint. Current automated tests cover these changes; they have not
been represented as a new paid/live run.

Raw report/cache/audit copies remain in ignored .trialfair files. Published paper
bodies and full abstracts were not committed as test fixtures. Live credentials
were neither printed nor committed.
