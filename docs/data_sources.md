# Data sources and licences

The repository contains synthetic contract fixtures and synthetic HTTP/model tests,
not committed clinical observations or article bodies. On the evidence branch,
EuropePMCClient retrieves real metadata, abstracts and permitted open-access body
text into ignored local caches. The registry adapter is still an Agent 1 dependency.

| Source | Intended use | Licence handling |
| --- | --- | --- |
| ClinicalTrials.gov API v2 | Trial identity, baseline measures, outcomes and AEs | Check current terms; preserve source URL, retrieval date and hash. No blanket licence claim is made here. |
| Europe PMC REST API | Publication metadata, abstracts and accessible full text | Metadata access is distinct from article redistribution rights. Record article-specific licence or unknown. |
| User-uploaded CSV/JSON | Optional participant-level or PK analysis | Record supplied provenance and permissions; reject unsafe or invalid uploads. |
| fixtures/synthetic | Interface compatibility and missing-data demonstration | Project-generated synthetic examples; no clinical observations. Repository licensing has not been selected. |
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
