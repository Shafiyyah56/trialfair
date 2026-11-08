# TrialFair four agent demonstration

For the participant-level synthetic datasets, use the new **Synthetic CSV upload**
form and [its instructions](SYNTHETIC_UPLOAD.md). That path analyses uploaded CSVs
and uses matched real class-context publications. The ACTT-1 path below remains
available separately as **Curated demo**.

Branch: feat/demo-integration. Agent 4's actual implementation from 0281f17 was
imported with author attribution preserved, then integrated with the shared run.
The normal autonomous path remains available. The explicitly selected curated
demo prioritises reproducible source review over live literature discovery.

## Start and run

From the repository root, in separate terminals:

```sh
.venv/bin/uvicorn app.api:app --reload
```

```sh
.venv/bin/streamlit run app/ui/dashboard.py
```

Open http://localhost:8501. Select **Curated demo**, then **Investigate**.
No JSON upload is required. Keep both terminal processes running.
The backend uses the existing ignored local key/model. No extra source API keys
or database server are needed. Restart older servers after pulling if reload is off.

To verify all four agents without starting servers:

```sh
.venv/bin/python -m scripts.smoke_pipeline --live --demo --nct-id NCT04280705
```

This makes live model calls and can incur charges. It saves the validated result
to ignored `.trialfair/pipeline-demo.json`; autonomous smoke reports are separate.
The CLI requires screening, investigation, cited evidence and follow-up actions
for a successful exit. Partial scientific status can still satisfy this software
check: incomplete evidence is not a claim that a drug is unsafe or safe.

## What is live and what is prepared

- Registry input: the original captured public ACTT-1 trial record, with its
  original retrieval date and content hash. No synthetic patients are substituted.
- Agent 1: live interpretation plus deterministic statistical screening. The
  default 20-term interpretation cap is explicit; all rows remain in statistics.
- Agent 3: three developer-selected real literature excerpts and prepared
  annotations, checked through the shared evidence validators. There is no fake
  internet search or claim of exhaustive discovery. Human clinical and animal
  evidence are explicitly separated. The UI and report label the curated profile.
- Agent 2: live tool-based review with the curated evidence available. If the
  provider cannot finish, a rules-based review of the actual screening findings
  is retained and explicitly labelled; it is not a successful model assessment.
- Agent 4: the teammate's real planner inspects findings and selects application-
  authored candidate actions. If provider selection fails in demo mode, the same
  validated candidates are presented as an explicitly labelled rules-based draft
  requiring researcher selection/prioritisation. Normal autonomous mode does not
  silently substitute this draft.

The demo uses one configurable 600-second run deadline and at least 18 model
turns, shared by all agents. The normal default remains 150 seconds/12 turns.
Planning receives reserved time/turns inside the original run budget; counters
are never reset. Demo planning has a 90-second local cap; ordinary planning 30.
Progress polling follows actual emitted events, with active agent highlighting.
Workflow percentages mark stages, not estimates of model completion.

## Suggested demonstration story

1. Explain the user: a safety scientist preparing the next research investigation.
2. Start ACTT-1 and show the screening output arriving before the run finishes.
   The trial is a completed COVID-19 treatment trial, not a Phase I case.
3. Show representation as reported and the availability limitations. These public
   results do not supply an extracted compatible female/male AE comparison;
   baseline sex counts must not be used as sex-specific event denominators.
4. Explain the curated evidence contrast: overall randomized cardiac evidence,
   a human QT study, and a mechanistic animal finding. The animal result does not
   establish increased risk in women. Clinical applicability remains a question.
5. Show concrete follow-up actions, required data, prerequisites and source IDs.
   Researchers review and approve actions; no action is executed automatically.
6. Open a cited excerpt/source and download the complete validated JSON report.

If the provider fails, keep the labelled fallback visible. If the live run is
slow, review the actual saved pipeline-demo.json through **Review saved run** and
state it is a previous run. Do not relabel prepared or saved outputs as live.

## Verification

265 offline tests currently pass, including normal and curated four-agent
orchestration, shared budget reservations, planner cross-reference validation,
actual async progress/API/storage, source-based demo output, fail-safe reports
and the rendered Streamlit four-agent visual. Ruff lint/format checks pass.
These tests use injected models and do not establish scientific validity.
An actual four-agent browser/model run still needs measurement and source review.
The coding sandbox cannot bind local ports; start servers in the user's Terminal.
