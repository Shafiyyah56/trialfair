# Fixture provenance

synthetic/ contains schema-valid hand-authored examples generated on 2026-11-08.
They contain no real drug, participant, publication, trial result or model output.
The synthetic trial ID deliberately does not look like an NCT identifier. The
source content_hash hashes the source title/description exactly as UTF-8 text.
A zero duration is a placeholder indicating no execution, not a latency metric.

The example demonstrates missing sex-stratified AE evidence and no external
research. It must not be presented as a clinical finding, a successful model run,
or a live/cached search. The replay-labelled TrialInput requires a developer to
register the fixture bundle under its opaque dataset_ref; there is no implemented
fixture loader or pipeline in the scaffold.

public/ is reserved for appropriately sourced and redistributable registry/API
responses. replay/ is reserved for actual labelled saved runs. Both are empty
apart from explanatory files. No external retrieval was performed for this commit.
