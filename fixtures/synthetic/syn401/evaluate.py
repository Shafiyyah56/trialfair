"""Monte Carlo evaluation of TrialFair's deterministic screening on SYN-401 (no Gemini).

For each scenario, generates K independent synthetic trials, runs TrialFair's real
participant loader and Female-vs-Male AE comparison on every one, and records how often
each comparison's 95% CI excludes zero. Because the generating truth is known, this
gives detection rates for true effects and false-positive rates for true nulls.

PK: TrialFair does not yet compare participant-level PK, so a Welch t-test on log AUC
(per active arm) is computed here as a reference analysis and reported separately.

Baseline: a registry-style view (arm totals only, no sex split), as on
ClinicalTrials.gov, cannot form any sex comparison, so its detection rate is 0 by
construction; the TrialFair registry path reports an evidence gap instead.

Run from the repository root:
  uv run python fixtures/synthetic/syn401/evaluate.py --sims 500
"""

import argparse
import json
import math
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))  # repository root

from generate import SCENARIOS, generate  # noqa: E402

from app.services.participant_data import load_participant_dataset  # noqa: E402
from app.services.statistics import compare_adverse_event_rates  # noqa: E402

FOCUS = ["Somnolence", "Dizziness", "Headache", "Nausea", "Fatigue"]


def pk_test(folder):
    import csv

    sex, arm = {}, {}
    with open(folder / "dm.csv") as fh:
        for r in csv.DictReader(fh):
            sex[r["USUBJID"]], arm[r["USUBJID"]] = r["SEX"], r["ACTARMCD"]
    auc = defaultdict(lambda: defaultdict(list))
    with open(folder / "pp.csv") as fh:
        for r in csv.DictReader(fh):
            if r["PPTESTCD"] == "AUCIFO":
                auc[arm[r["USUBJID"]]][sex[r["USUBJID"]]].append(math.log(float(r["PPSTRESN"])))
    out = {}
    for a, by_sex in auc.items():
        f, m = np.array(by_sex["F"]), np.array(by_sex["M"])
        if len(f) < 2 or len(m) < 2:
            continue
        t = stats.ttest_ind(f, m, equal_var=False)
        ci = t.confidence_interval(0.95)
        out[a] = {
            "gmr": math.exp(f.mean() - m.mean()),
            "lo": math.exp(ci.low),
            "hi": math.exp(ci.high),
        }
    return out


def run(scenario, sims, seed0):
    hits = defaultdict(int)
    seen = defaultdict(int)
    pk_hits = defaultdict(int)
    pk_gmr = defaultdict(list)
    any_null_hit = 0
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(sims):
            folder = Path(tmp) / str(k)
            generate(scenario, seed0 + k, folder)
            bundle = load_participant_dataset(
                folder / "dm.csv", folder / "ae.csv", is_synthetic=True
            )
            rows = defaultdict(dict)
            for r in bundle.adverse_event_rows:
                rows[(r.source_term, r.group_id, r.event_seriousness)][r.reported_sex_category] = r
            null_hit = False
            for (term, arm, _), by_sex in rows.items():
                if "Female" not in by_sex or "Male" not in by_sex:
                    continue
                res, _ = compare_adverse_event_rates(bundle, [by_sex["Female"], by_sex["Male"]])
                lo, hi = res["risk_difference_ci95"]
                seen[(term, arm)] += 1
                if lo > 0 or hi < 0:
                    hits[(term, arm)] += 1
                    exposure_driven = scenario not in {"null"}
                    is_true = (
                        term in {"Somnolence", "Dizziness", "Somnambulism"}
                        and arm != "PBO"
                        and exposure_driven
                    ) or (term == "Headache" and SCENARIOS[scenario]["headache_sex_effect"])
                    null_hit |= not is_true
            any_null_hit += null_hit
            for arm, r in pk_test(folder).items():
                pk_gmr[arm].append(r["gmr"])
                pk_hits[arm] += r["lo"] > 1 or r["hi"] < 1
    ae_rates = {
        f"{t} {a}": round(hits[(t, a)] / sims, 3)
        for t in FOCUS
        for a in ("PBO", "SYN5", "SYN10")
        if seen[(t, a)]
    }
    return {
        "sims": sims,
        "ae_ci_excludes_zero_rate": ae_rates,
        "any_false_positive_per_trial": round(any_null_hit / sims, 3),
        "pk_auc_gmr_median": {a: round(float(np.median(v)), 3) for a, v in pk_gmr.items()},
        "pk_ci_excludes_one_rate": {a: round(pk_hits[a] / sims, 3) for a in pk_gmr},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=300)
    ap.add_argument("--seed0", type=int, default=10_000)
    ap.add_argument("--scenarios", nargs="*", default=sorted(SCENARIOS))
    args = ap.parse_args()
    results = {s: run(s, args.sims, args.seed0) for s in args.scenarios}
    (HERE / "evaluation.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
