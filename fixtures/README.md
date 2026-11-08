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

## synthetic/syn401 (participant-level, SYNTHETIC)

SYN-401-102 is a mechanistic synthetic Phase Ib/IIa trial of a fictional hypnotic,
calibrated to the published range across six approved hypnotics rather than any single
drug. It contains SDTM-style DM, AE, PP and narrative CSVs, `truth.json` (generating
parameters and expected conclusions), the generator, and a known-truth evaluation. See
`synthetic/syn401/DATACARD.md` for sources, limitations and the proposed licence. It
contains no real participant or trial data.
