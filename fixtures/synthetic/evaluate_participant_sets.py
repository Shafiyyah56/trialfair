"""Known-truth Monte Carlo evaluation of TrialFair's deterministic statistics (no LLM).

Generates K synthetic trials per scenario for SYN-722 (QT) or SYN-318 (antiepileptic),
runs TrialFair's real participant loader and analyses on each, and reports how often a
95% interval excludes the null. Because each scenario's truth is known, these are
detection rates for real effects and false-positive rates for nulls.

Run from the repository root:
  uv run python fixtures/synthetic/evaluate_participant_sets.py syn722 --sims 300
  uv run python fixtures/synthetic/evaluate_participant_sets.py syn318 --sims 300
Writes <dataset>/evaluation.json.
"""

import argparse
import importlib.util
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # repository root

from app.services.participant_data import load_participant_dataset  # noqa: E402
from app.services.statistics import (  # noqa: E402
    NoParameters,
    compare_adverse_event_rates,
    summarise_pk_by_sex,
    summarise_qtc_by_sex,
)


def load_generator(name):
    spec = importlib.util.spec_from_file_location(f"{name}_generate", HERE / name / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def excludes(interval, null):
    return interval is not None and (interval[0] > null or interval[1] < null)


def ae_comparisons(bundle):
    rows = defaultdict(dict)
    for r in bundle.adverse_event_rows:
        rows[(r.source_term, r.group_id, r.event_seriousness)][r.reported_sex_category] = r
    for (term, arm, _), by_sex in rows.items():
        if "Female" in by_sex and "Male" in by_sex:
            result, _ = compare_adverse_event_rates(bundle, [by_sex["Female"], by_sex["Male"]])
            yield term, arm, excludes(result["risk_difference_ci95"], 0)


def run(name, scenario, sims, seed0, true_ae_terms):
    gen = load_generator(name)
    counts = defaultdict(int)
    seen = defaultdict(int)
    with tempfile.TemporaryDirectory() as tmp:
        for k in range(sims):
            folder = Path(tmp) / str(k)
            gen.generate(scenario, seed0 + k, folder)
            eg = folder / "eg.csv"
            bundle = load_participant_dataset(
                folder / "dm.csv",
                folder / "ae.csv",
                is_synthetic=True,
                pp_path=folder / "pp.csv",
                eg_path=eg if eg.exists() else None,
            )
            false_hit = False
            for term, arm, hit in ae_comparisons(bundle):
                seen[f"AE {term} {arm}"] += 1
                counts[f"AE {term} {arm}"] += hit
                if hit and not (term in true_ae_terms and arm != "PBO"):
                    false_hit = True
            counts["trials with >=1 AE comparison flagged outside true effects"] += false_hit
            pk, _ = summarise_pk_by_sex(bundle, bundle.pk_rows)
            for ratio in pk["participant_level_ratios"]:
                if ratio["status"] == "completed" and ratio["parameter"] == "AUCIFO":
                    key = f"PK AUC ratio CI excludes 1 ({ratio['group_id']})"
                    seen[key] += 1
                    counts[key] += excludes(ratio["ratio_ci95"], 1)
                    counts[f"_gmr_sum {ratio['group_id']}"] += ratio["geometric_mean_ratio"]
            if eg.exists():
                qtc, _ = summarise_qtc_by_sex(bundle, NoParameters())
                model = qtc["concentration_qtc"]
                if model:
                    for key, interval in (
                        ("QTc female offset CI excludes 0", model["offset_ci95"]),
                        ("QTc slope difference CI excludes 0", model["slope_difference_ci95"]),
                    ):
                        seen[key] += 1
                        counts[key] += excludes(interval, 0)
                for comp in qtc["female_male_comparisons"]:
                    key = f"QTc max-change difference CI excludes 0 ({comp['group_id']})"
                    seen[key] += 1
                    counts[key] += excludes(comp["difference_ci95"], 0)
    out = {"sims": sims}
    for key, value in sorted(counts.items()):
        if key.startswith("_gmr_sum"):
            arm = key.split()[-1]
            n = seen[f"PK AUC ratio CI excludes 1 ({arm})"]
            out[f"PK AUC ratio mean ({arm})"] = round(value / n, 3) if n else None
        elif key.startswith("trials with"):
            out[key] = round(value / sims, 3)
        else:
            out[key] = round(value / seen[key], 3) if seen[key] else None
    return out


TRUE_AE_TERMS = {
    # Terms where a real female excess exists in active arms under the default scenario.
    "syn722": {"Electrocardiogram QT prolonged", "Torsade de pointes"},
    "syn318": set(),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", choices=sorted(TRUE_AE_TERMS))
    ap.add_argument("--sims", type=int, default=300)
    ap.add_argument("--seed0", type=int, default=10_000)
    args = ap.parse_args()
    gen = load_generator(args.dataset)
    results = {
        s: run(
            args.dataset,
            s,
            args.sims,
            args.seed0,
            TRUE_AE_TERMS[args.dataset] if s != "null" else set(),
        )
        for s in gen.SCENARIOS
    }
    (HERE / args.dataset / "evaluation.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
