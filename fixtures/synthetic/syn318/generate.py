"""SYN-318-201: mechanistic SYNTHETIC Phase Ib/IIa trial of a fictional antiepileptic drug.

SYNTHETIC DATA. SYN-318 is a fictional adjunctive antiseizure medicine. No real participant,
trial or result is represented. It is calibrated to the published range across four
antiseizure medicines (CLASS_REFERENCE), never to a single drug.

Default truth ("weight_only"): women have slightly higher exposure ONLY because they are
lighter (clearance scales with body weight; no residual sex effect), and drug sensitivity
is identical. Labels for this class report either no sex difference or one explained by
body weight. The correct conclusion is "no sex difference beyond body size" and a correct
screen should not raise sex-specific AE signals beyond chance.

Usage:
  python generate.py                                    # default scenario, seed 318
  python generate.py --scenario hidden_sex_effect --seed 5 --out /tmp/syn318_hidden
Writes dm.csv, ae.csv, pp.csv, narratives.csv and truth.json into --out.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdtm_sim import (  # noqa: E402
    WEIGHT,
    WEIGHT_BOUNDS,
    WEIGHT_EXPOSURE_RATIO,
    TrialWriter,
    expit,
    logit,
    one_compartment,
)

GENERATOR_VERSION = "1.0.0"
STUDY = "SYN-318-201"
ARMS = [
    ("PBO", "Placebo", 0.0),
    ("SYN100", "SYN-318 100 mg", 100.0),
    ("SYN200", "SYN-318 200 mg", 200.0),
]
N_PER_ARM = 40
P_FEMALE = 0.45  # illustrative; epilepsy affects both sexes and Phase II shares near 48%
AGE = (38, 12)  # illustrative adult focal-epilepsy population
AGE_BOUNDS = (18, 65)

CL_TYP, V_TYP, KA, F_ORAL = 4.0, 50.0, 1.5, 0.95  # typical half-life ~9 h (illustrative)
OMEGA_CL, OMEGA_V = 0.25, 0.20

SCENARIOS = {
    "weight_only": {"female_exposure_ratio": WEIGHT_EXPOSURE_RATIO, "equal_weights": False},
    # A residual sex effect TrialFair should be able to detect if present.
    "hidden_sex_effect": {"female_exposure_ratio": 1.30, "equal_weights": False},
    "null": {"female_exposure_ratio": 1.0, "equal_weights": True},
}

CLASS_REFERENCE = {
    "levetiracetam": {
        "sex_pk": "Cmax and AUC ~20% higher in women, but clearance adjusted "
        "for body weight comparable",
        "somnolence": (15, 8),
        "dizziness": (9, 4),
        "fatigue": (15, 9),
        "year": "label (approved 1999)",
        "sources": [
            "Keppra US PI, pooled adjunctive adult table",
            "levetiracetam PI 12.3 (gender)",
        ],
    },
    "brivaracetam": {
        "sex_pk": "No differences between male and female subjects",
        "somnolence": (16, 8),
        "dizziness": (12, 7),
        "fatigue": (9, 4),
        "year": "label (approved 2016)",
        "sources": ["Briviact US PI", "FDA Drug Trials Snapshot: Briviact"],
    },
    "lacosamide": {
        "sex_pk": "No clinically relevant influence of gender; higher female "
        "concentrations explained by smaller V/F",
        "somnolence": (8, 5),
        "dizziness": (30, 8),
        "fatigue": None,
        "year": "label (approved 2008)",
        "sources": ["Vimpat US PI (400 mg/day row)", "population PK by age and gender (PAGE 2005)"],
    },
    "topiramate": {
        "sex_pk": "Clearance not affected by gender (adults 18-67)",
        "somnolence": None,
        "dizziness": None,
        "fatigue": None,
        "year": "label (approved 1996; older label versions)",
        "sources": ["Topamax US PI (archived versions)"],
    },
}


def _median(key, index):
    values = [v[key][index] for v in CLASS_REFERENCE.values() if v.get(key)]
    return float(np.median(values)) / 100.0


AE_MODEL = {
    "Somnolence": {
        "p0": _median("somnolence", 1),
        "target_top_dose": _median("somnolence", 0),
        "soc": "Nervous system disorders",
        "verbatims": [
            "drowsiness",
            "sleepy during the day",
            "somnolence",
            "drowsy after morning dose",
        ],
    },
    "Dizziness": {
        "p0": _median("dizziness", 1),
        "target_top_dose": _median("dizziness", 0),
        "soc": "Nervous system disorders",
        "verbatims": ["dizziness", "dizzy", "unsteady", "light-headed"],
    },
    "Fatigue": {
        "p0": _median("fatigue", 1),
        "target_top_dose": _median("fatigue", 0),
        "soc": "General disorders and administration site conditions",
        "verbatims": ["fatigue", "tiredness", "lethargic", "no energy"],
    },
}
BACKGROUND = {  # illustrative rates, no drug or sex effect
    "Headache": (0.10, "Nervous system disorders", ["headache", "HA", "head pain"]),
    "Nausea": (0.05, "Gastrointestinal disorders", ["nausea", "queasy", "felt sick"]),
    "Upper respiratory tract infection": (
        0.05,
        "Infections and infestations",
        ["common cold", "URTI", "cold symptoms"],
    ),
    "Back pain": (
        0.03,
        "Musculoskeletal and connective tissue disorders",
        ["back pain", "lower back ache"],
    ),
}


def theta_for(cfg):
    weight_ratio = 1.0 if cfg["equal_weights"] else WEIGHT_EXPOSURE_RATIO
    return weight_ratio / cfg["female_exposure_ratio"]


AUC_REF = F_ORAL * 200.0 * 1000.0 / (CL_TYP * (WEIGHT["M"][0] / 70) ** 0.75)


def _calibrate_betas():
    """Slopes so the expected 200 mg rate in the reference population is the class median."""
    rng = np.random.default_rng(20261108)
    n = 20000
    female = rng.random(n) < P_FEMALE
    weight = np.clip(
        rng.normal(
            np.where(female, WEIGHT["F"][0], WEIGHT["M"][0]),
            np.where(female, WEIGHT["F"][1], WEIGHT["M"][1]),
        ),
        *WEIGHT_BOUNDS,
    )
    cl = (
        CL_TYP
        * (weight / 70) ** 0.75
        * np.where(female, theta_for(SCENARIOS["weight_only"]), 1.0)
        * np.exp(rng.normal(0, OMEGA_CL, n))
    )
    exposure = F_ORAL * 200.0 * 1000.0 / cl / AUC_REF
    return {
        term: brentq(
            lambda b, a=logit(m["p0"]), t=m["target_top_dose"]: (
                float(np.mean(1 / (1 + np.exp(-(a + b * exposure))))) - t
            ),
            0.0,
            20.0,
        )
        for term, m in AE_MODEL.items()
    }


def generate(scenario, seed, out):
    cfg = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    trial = TrialWriter(STUDY, rng)
    dosed = trial.enrol(
        ARMS, N_PER_ARM, P_FEMALE, AGE, AGE_BOUNDS, equal_weights=cfg["equal_weights"]
    )
    theta, betas = theta_for(cfg), _calibrate_betas()
    for p in dosed:
        female = p.sex == "F"
        exposure = 0.0
        if p.dose:
            cl = CL_TYP * (p.weight / 70) ** 0.75 * (theta if female else 1.0)
            cl *= math.exp(rng.normal(0, OMEGA_CL))
            v = V_TYP * (p.weight / 70) * math.exp(rng.normal(0, OMEGA_V))
            trial.add_pk(p, *one_compartment(p.dose, cl, v, KA, F_ORAL))
            exposure = p.auc / AUC_REF
        for term, m in AE_MODEL.items():
            if rng.random() < expit(logit(m["p0"]) + betas[term] * exposure):
                withdrawn = exposure > 1.4 and rng.random() < 0.15
                trial.add_ae(
                    p,
                    term,
                    m["soc"],
                    m["verbatims"],
                    day=int(rng.integers(1, min(p.nights, 7) + 1)),
                    related=bool(p.dose),
                    action="DRUG WITHDRAWN" if withdrawn else "DOSE NOT CHANGED",
                )
        for term, (rate, soc, verbatims) in BACKGROUND.items():
            if rng.random() < rate:
                trial.add_ae(p, term, soc, verbatims, day=int(rng.integers(1, p.nights + 4)))
    trial.add_realism(
        dosed,
        [
            ("Headache", BACKGROUND["Headache"][1], BACKGROUND["Headache"][2]),
            (
                "Upper respiratory tract infection",
                BACKGROUND["Upper respiratory tract infection"][1],
                BACKGROUND["Upper respiratory tract infection"][2],
            ),
        ],
        ("Back pain", BACKGROUND["Back pain"][1], "back pain"),
    )
    trial.add_notes(
        dosed,
        [
            "No seizures or dizziness reported at the Day 7 visit.",
            "Possible drowsiness after the evening dose; participant unsure.",
            "History of migraine before enrolment, unchanged on study.",
            "Felt a bit off on Day 2, resolved without action.",
            "Participant denies mood change or irritability.",
            "Moderate daytime somnolence, considered related to study drug by the investigator.",
        ],
    )
    trial.write(out)
    truth = {
        "study": STUDY,
        "is_synthetic": True,
        "generator_version": GENERATOR_VERSION,
        "scenario": scenario,
        "seed": seed,
        "scenario_parameters": cfg,
        "design": {
            "arms": [a[:2] for a in ARMS],
            "randomised_per_arm": N_PER_ARM,
            "p_female": P_FEMALE,
        },
        "pk_model": {
            "CL_typ": CL_TYP,
            "V_typ": V_TYP,
            "ka": KA,
            "F": F_ORAL,
            "omega_CL": OMEGA_CL,
            "omega_V": OMEGA_V,
            "auc_ref": AUC_REF,
            "theta_sex_after_weight": theta,
        },
        "ae_model": {
            k: {kk: vv for kk, vv in v.items() if kk != "verbatims"} for k, v in AE_MODEL.items()
        },
        "calibrated_exposure_slopes": betas,
        "true_effects": true_effects(scenario),
        "class_reference": CLASS_REFERENCE,
    }
    (out / "truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    return len(trial.dm), len(dosed), len(trial.ae)


def true_effects(scenario):
    cfg = SCENARIOS[scenario]
    return {
        "female_to_male_AUC_ratio_typical": round(cfg["female_exposure_ratio"], 3),
        "explained_by_body_weight": scenario != "hidden_sex_effect",
        "female_pd_sensitivity": 1.0,
        "expected_conclusion": {
            "weight_only": "Any female exposure excess (~1.13x) is explained by body weight; "
            "AE sex differences are small and should not reach clear signals beyond chance. "
            "No sex-specific dosing question.",
            "hidden_sex_effect": "Female exposure ~1.30x, only partly explained by weight; "
            "a weight-adjusted analysis should show a residual sex effect.",
            "null": "No sex difference in exposure or AEs.",
        }[scenario],
        "background_terms": "Headache, nausea, URTI, back pain: no drug or sex effect "
        "(illustrative rates)",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="weight_only")
    ap.add_argument("--seed", type=int, default=318)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    args = ap.parse_args()
    total, dosed, records = generate(args.scenario, args.seed, args.out)
    print(
        f"{STUDY} [{args.scenario}, seed {args.seed}]: {total} DM rows, {dosed} dosed, "
        f"{records} AE records -> {args.out}"
    )


if __name__ == "__main__":
    main()
