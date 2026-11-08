# Data sources and licences

The repository contains labelled synthetic test fixtures, one captured public
trial response and three short real article excerpts for the explicit curated
demo. Real registry and Europe PMC adapters are wired. Complete retrieved article
records/bodies remain in ignored runtime caches. Public aggregate trial data must
not be confused with patient-level measurements.

| Source | Intended use | Licence handling |
| --- | --- | --- |
| ClinicalTrials.gov API v2 | Trial identity, baseline measures, outcomes and AEs | Check current terms; preserve source URL, retrieval date and hash. No blanket licence claim is made here. |
| Europe PMC REST API | Publication metadata, abstracts and accessible full text | Metadata access is distinct from article redistribution rights. Record article-specific licence or unknown. |
| User-uploaded CSV/JSON | Optional participant-level or PK analysis | Record supplied provenance and permissions; reject unsafe or invalid uploads. |
| fixtures/synthetic | Interface compatibility and missing-data demonstration | Project-generated synthetic examples; no clinical observations. Repository licensing has not been selected. |
| fixtures/curated | Explicit remdesivir demonstration with three real short excerpts | Original source metadata, licence labels, hashes/dates and excerpt hashes retained; not an autonomous search. |
| fixtures/replay | Future saved agent runs | Empty initially. Record model ID, actual sources, original retrieval times and replay status. |

Official starting points:
- https://clinicaltrials.gov/data-api/api
- https://www.ebi.ac.uk/europepmc/webservices/rest/
- https://github.com/googleapis/python-genai

Every SourceRecord must identify access level, content hash, retrieval time and
licence status. Unknown licences remain unknown. Do not scrape restricted text,
claim full-text review from metadata alone or expose sensitive uploaded data in
logs. Keep downloaded runtime files out of Git. Public fixtures added later need
provenance and a redistribution review appropriate to the actual source.
