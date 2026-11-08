# Synthetic participant upload demo

The datasets are SDTM-style CSV files, not a SQL patient database. SQLite stores
validated investigation results in .trialfair/runs.sqlite. Uploaded participant
values stay in server memory for analyses; raw CSV temporary files are removed
after loading. Restarting the backend removes participant-level analysis state.

## Dataset locations

| Folder | Demonstration class | Files |
| --- | --- | --- |
| fixtures/synthetic/syn401/data | Fictional hypnotic | dm.csv, ae.csv, pp.csv, narratives.csv |
| fixtures/synthetic/syn722/data | Fictional cardiac repolarization compound | dm.csv, ae.csv, pp.csv, eg.csv, narratives.csv |
| fixtures/synthetic/syn318/data | Fictional antiseizure compound | dm.csv, ae.csv, pp.csv, narratives.csv |

dm.csv contains participant demographics, arms and first-dose dates. ae.csv
contains event records and dates. pp.csv contains PK measurements. eg.csv adds
ECG/QTc measurements. narratives.csv contains free-text descriptions.
truth.json, evaluation outputs, data cards and generation parameters are NOT
uploaded or supplied to agents. Sample download bundles contain CSV domains only.
Use the separate evaluation tools to assess the generated findings against truth.

## Website flow

Start the existing backend/dashboard. Open http://localhost:8501 and select
**Synthetic CSV upload**.

1. Choose the matching class profile: SYN-401, SYN-722 or SYN-318.
2. Use the files already in the folder above, or click **Download sample CSV
   bundle** and unzip it locally.
3. Upload dm.csv and ae.csv together. Include pp.csv for PK, eg.csv for ECG/QTc
   where available, and narratives.csv for natural-language examples.
4. Confirm the records are simulated.
5. Click **Validate files without running AI**. This checks schema/study identity
   and shows the safety population, reported categories, domains and availability.
   No credentials or model calls are needed for validation.
6. Click **Investigate** to run all four agents using the actual uploaded values.
   This uses the configured model and can incur charges. Watch the live pipeline,
   then inspect analyses, sources, recommendations and the downloadable report.

Files must use the supplied SDTM-style columns, be UTF-8 CSV, and be at most 2 MB
each. Required domains, duplicates, study identity and source-profile compatibility
are checked before model creation. Only the three supplied synthetic study-prefix
families are supported by the curated upload profile. No arbitrary file paths,
JSON answer keys, ZIP extraction, pickle or executable uploads are accepted.

## Reviewing the report

The dashboard's main inputs are **Synthetic CSV upload**, **Completed trial**
and **Review saved run**. Additional curated/developer inputs are available via
the sidebar checkbox. Completed-trial mode accepts a public trial identifier;
the synthetic upload remains restricted to the supplied simulated study families.

Results open on **Final report**, with prioritised Agent 4 actions and their
rationale, required data and prerequisites. Use **Findings & analyses** for
statistics, **Evidence & sources** for inspected excerpts and provenance, and
**Run activity** for agent interactions. Simulation, curated evidence, partial
status and fallback notices remain visible.

**Download report** saves a standalone HTML report that can be opened in a
browser and printed to PDF. Markdown and validated JSON exports are also provided.
Reviewing a saved report and downloading it do not start another model run.

## Preselected evidence

Each profile uses two actual retrieved publication excerpts with original record
hashes/dates, source URLs, access and licence metadata. All are labelled curated
class-context evidence; none is a clinical study of the fictional compound.

- SYN-401: [zolpidem sex-related PK](https://europepmc.org/article/MED/34580385)
  and [lemborexant clinical context](https://europepmc.org/article/MED/42088939).
- SYN-722: [sotalol TdP analysis](https://europepmc.org/article/MED/8921798)
  and [exposure-adjusted ECG crossover study](https://europepmc.org/article/MED/26324176).
- SYN-318: [levetiracetam covariate study](https://europepmc.org/article/MED/29965883)
  and [population PK analysis](https://europepmc.org/article/MED/17518509).

The class context is deliberately not confirmation of a simulated mechanism.
Agents receive no expected answer or scenario label. Background evidence should
not override the uploaded measurements, create causal conclusions, or establish
absence of sex differences. Normal curated-demo labels, shared extended budget,
source checks, human review and explicitly labelled provider fallbacks remain.

## API and tests

POST /synthetic/preview validates a SyntheticUpload JSON envelope. POST
/synthetic/runs/async starts it and returns the existing run/progress identifiers.
The envelope contains profile, is_synthetic=true and allowed filename/base64-byte
pairs. Streamlit builds this body; humans do not need to create JSON.
The existing Agent 1 loader registers the aggregate bundle under an opaque run-local
reference and retains participant data for the existing statistics tools.

314 offline tests pass, including all three uploads through four-agent orchestration,
source matching, ECG/PK availability, rejection before model creation, storage,
changed uploaded values, ZIP answer-key exclusion and form rendering/confirmation.
These checks use injected models; they do not establish live model accuracy.
The actual browser form and missing-file validation were inspected. The browser
automation cannot select local repository files under its own access policy;
manual file selection is required for a full live browser upload check.
