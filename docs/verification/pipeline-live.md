# Combined live run — 2026-11-08

## Second combined run — preserved partial results, still no cited evidence

After timing correction 8ab8457: 149.18 seconds, partial, screening/investigation
available, one evidence report, zero items/cited sources. Eight model turns and
seven external requests; no top-level errors. This is not a completed research demo.

The saved timeline shows interpretation fell from roughly 93 to 29 seconds.
Six successful literature-search calls preceded two failed searches. No publication
was inspected; only the input registry was inspected. The source pool held 20
publications plus the registry record, consistent with the pool-limit exception.
Recorded limitations: `search_publications failed (ValueError)` and
`Evidence research: too_many_tool_calls_in_one_turn`. The final oversized tool
batch aborted research before synthesis. Safety then spent roughly 16 seconds
selecting tools before its final report attempt failed. The original provider
category/status was not recorded, so that last failure's cause is unknown.

Further corrections: cap actual literature searches at three; close search after
two queries yield candidates and require publication inspection; prompt selection
of one or two abstracts. Full pools retain accepted results without an exception.
Oversized batches execute at most five calls and return a result for every call,
including explicit rejections for the excess, preserving provider continuation
and allowing synthesis. They still force a partial report. If evidence returns
with 45 seconds or less, safety goes directly to final assessment. Sanitised
provider error class/status are now retained without raw provider messages.

202 offline tests pass, including oversized-batch synthesis, search caps, full
pools, publication-first tools, complete tool history and late-evidence reporting.
Another live retest remains pending; offline tests do not establish a timely,
scientifically supported real report. No grounding rules or deadlines were relaxed.

## First combined run

User-run `scripts.smoke_pipeline --live --nct-id NCT04280705`, before the timing
correction. Observed output: gemini-4-argon, 149.85 seconds, partial. Screening
was retained, investigation unavailable, zero evidence reports/items/cited sources.
Six model turns, three external requests and one evidence request were consumed.
The run ended at the existing 150-second deadline. This is a failed acceptance
check for the complete trial-to-cited-report path, not a completed live demo.

The assistant inspected the saved `.trialfair/pipeline-smoke.json` event timeline:

- Interpretation of 100 distinct terms started at 11:00:56 UTC; screening returned
  at 11:02:29, roughly 93 seconds later. Two terms remained flagged for review.
- Safety inspected analyses/findings; requested external evidence at 11:02:56.
- The evidence agent inspected the input registry record and attempted literature
  searches. The first search failed with LiteratureUnavailable after roughly
  12 seconds. No HTTP status was recorded; the precise failure cause is unproven.
- The overall deadline cancelled the next search. Nested research state and final
  assessment were not retained in the old execution path.

The original saved report was not rewritten to imply successful research.

## Implemented corrections, awaiting live retest

The default interpretation batch is 20 distinct texts, configurable up to 100.
All source rows remain available to statistics. Interpretation/refinement calls
have local time limits and preserve uncertain mappings/statistics on timeout.
The report explicitly states when text interpretation is limited.

Research has a local time cap and reserves time for the investigator's final
assessment. A local timeout preserves actual retrieved sources and recorded
searches, without synthesising unsupported claims. Safety tool selection also
reserves time for its report. If the overall deadline expires, the orchestrator
retains an explicitly unassessed partial investigation and PlannerInput.

The total deadline, cumulative budgets and evidence-grounding requirements were
not relaxed. Offline tests cover the revised cancellation paths; the revised
combined path has not been verified live. A real cited report and source audit
remain required before claiming the full demonstration works.

Retest from the repository root:

```sh
.venv/bin/python -m scripts.smoke_pipeline --live --nct-id NCT04280705
```

This incurs source/model calls. Review both limitations and citation support;
partial status remains expected when interpretation coverage is deliberately bounded.
