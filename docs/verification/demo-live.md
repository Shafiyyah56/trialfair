# Curated four-agent browser check

Observed 2026-11-08 in the user's running local FastAPI/Streamlit application.
Run ID: 617c7b12-c1ff-4b28-85a7-085108f97c56; model gemini-4-argon.

- Duration: 95.87 seconds; status partial.
- Two screening findings, three cited curated items from three real sources.
- Safety and planner model inspections ran. Their final outputs were rejected
  by report/selection validation; a successful model-authored final assessment
  or selection is not established by this run.
- Explicit rules-based assessment and candidate-draft fallbacks produced four
  follow-up actions, preserving source links, uncertainty and human review.
- The report passed cross-reference validation, was saved in SQLite and was
  reopened successfully in the real browser through Review saved run.
- Browser displayed citation counts, planning actions, original limitations and
  Download validated run JSON. Saved review is labelled separately from execution.

This validates the curated demo's wiring, persistence and labelled fallback
behaviour. Literature selection and annotations were prepared; this is not a
successful autonomous literature discovery or complete live model investigation.
Scientific conclusions and proposed follow-ups still require expert review.

The browser check found two launcher/display bugs, now corrected: the Streamlit
console entry point omitted the repository root from the import path, and the
live activity-label map lacked planner. Regression checks now exercise isolated
launcher imports and a nonempty planner activity event, in addition to plan cards.

The unchanged validated report is saved locally in ignored
.trialfair/verification/demo-live-617c7b12.json and .trialfair/pipeline-demo.json.
Use the run ID above in Review saved run for the presentation backup. No second
paid execution is needed to display that report.
