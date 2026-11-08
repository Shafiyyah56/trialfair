# Entirely synthetic Phase I evidence for Agent 4

Every count, compound, source, finding and assessment here is fabricated for
software testing. No real trial, publication, participant record or clinical
observation is represented. This is a hand-authored upstream snapshot, not an
output produced by Agents 1–3 or a live model.

Use `planner_input.json` as the typed `PlannerInput` for independent Agent 4 runs.
The `sources/` folder contains the exact fabricated source texts, with SHA-256
hashes matching the source records. Source IDs are local identifiers, not real
citations. Abstract-only support and contradiction are both fabricated.

| Scenario input | Synthetic value |
| --- | --- |
| Trial | Phase I fixed-dose cohort; fabricated SYN-ALPHA compound |
| Total participants | 36 |
| Reported Female / Male | 6 / 30 |
| Non-serious nausea, Female | 3 affected / 6 at risk |
| Non-serious nausea, Male | 5 affected / 30 at risk |
| Reporting window | Days 1–14, same synthetic arm and safety population |
| Sex-specific PK | Missing, including Cmax and AUC |
| Participant-level data | Not provided |
| Mock evidence | Supporting and contradictory abstract-only sources |

The snapshot includes an exploratory nausea finding, a representation gap and a
missing-PK gap. The investigation/evidence status is partial. It intentionally
exercises unresolved questions: missing data must not establish safety, subgroup
associations must not establish causality, and different study contexts require
applicability review. No numerical dose, clinical threshold, power calculation or
future sample-size target is supplied or recommended.

Useful planning actions could include researcher review of subgroup precision and
representation, review of contradictory evidence, compatible exploratory analysis,
retrieval of sex-specific PK summaries, or future protocol data collection after
review. These are evaluation expectations, not completed analyses or clinical advice.
This dataset drives the Agent 4 functional regression tests and before/after
verification for PK matching, representation, hypothesis scope and completion
coverage. The implementation fixes and validation scope are documented in
`docs/verification/agent-4-fixes.md`.

```python
from pathlib import Path
from app.contracts import PlannerInput
from app.validation import validate_planner_input

snapshot = PlannerInput.model_validate_json(
    Path("fixtures/synthetic/phase1_agent4/planner_input.json").read_text()
)
validate_planner_input(snapshot)
```

Loading and validating this data makes no paid calls. Executing Agent 4 with a
live model is a separate action requiring explicit permission. Independent callers
must close their owned ToolContext in finally. No execution or output plan is
included here.
