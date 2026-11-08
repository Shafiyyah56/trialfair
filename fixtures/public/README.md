# Public data fixtures

`NCT04280705.json` is an unmodified ClinicalTrials.gov API v2 response retrieved
for Agent 1 offline regression tests. The adjacent provenance JSON records URL,
retrieval timestamp and SHA-256. It contains public registry metadata and aggregate
results, including public contact metadata; no contact actions are performed.
It is not synthetic, patient-level data or an agent/model replay.

The baseline reports sex counts, while the extracted AE groups are treatment
arms, not explicit sex strata. Tests must preserve this distinction. Licence
status remains unknown; access to a public endpoint is not a blanket licence
claim. Source terms: https://clinicaltrials.gov/about-site/terms-conditions.
No restricted publication full text is included.
