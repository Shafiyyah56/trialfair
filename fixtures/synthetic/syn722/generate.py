"""SYN-722-201: mechanistic SYNTHETIC Phase Ib/IIa trial of a fictional QT-prolonging drug.

SYNTHETIC DATA. SYN-722 is a fictional class III-type antiarrhythmic. No real participant,
trial or result is represented. It is calibrated to the published range across several
QT-prolonging antiarrhythmics (CLASS_REFERENCE), never to a single drug.

Default truth ("baseline_vulnerability"):
- Exposure differs by sex only through body weight; no residual sex effect on clearance.
- The drug's QTcF effect per unit concentration is the SAME in women and men
  (Vicente et al. 2015 found no sex difference in exposure-adjusted QTc prolongation).
- Women start with a longer baseline QTcF (~8 ms) and have higher odds of torsade de
  pointes at the same QTc (Lehmann et al. 1996: about threefold after adjustment).
So women cross ICH E14 outlier categories more often because of baseline vulnerability,
not because they receive more drug or respond more per unit of drug.

Usage:
  python generate.py                                  # default scenario, seed 722
  python generate.py --scenario null --seed 3 --out /tmp/syn722_null
Writes dm.csv, ae.csv, pp.csv, eg.csv, narratives.csv and truth.json into --out.
"""

import argparse
import json
import math
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sdtm_sim import (  # noqa: E402
    WEIGHT,
    WEIGHT_EXPOSURE_RATIO,
    TrialWriter,
    expit,
    logit,
    one_compartment,
)

GENERATOR_VERSION = "1.0.0"
STUDY = "SYN-722-201"
ARMS = [
    ("PBO", "Placebo", 0.0),
    ("SYN100", "SYN-722 100 mg", 100.0),
    ("SYN200", "SYN-722 200 mg", 200.0),
]
N_PER_ARM = 40
P_FEMALE = 0.35  # illustrative; within the published Phase I-II range (Labots 2018)
AGE = (62, 9)  # illustrative for adults with paroxysmal atrial fibrillation
AGE_BOUNDS = (40, 79)

# PK (fictional; absolute scale illustrative). Typical half-life ~8 h.
CL_TYP, V_TYP, KA, F_ORAL = 12.0, 140.0, 1.0, 0.90
OMEGA_CL, OMEGA_V = 0.30, 0.20

# QTcF model (ms). Calibrated to patient cohorts starting sotalol/dofetilide: QTc change
# +19 +/- 30 ms after the initial dose, and mean maximum QTc 471 ms during initiation with
# standard dosing. Male baseline is set so the expected maximum on the top dose is ~471 ms.
BASELINE_QTCF = {"M": 448.0}  # female baseline = male + scenario offset
BASELINE_SD = 18.0  # illustrative
ECG_NOISE_SD = 8.0  # within-participant measurement/day-to-day variability (illustrative)
TYPICAL_MALE_TOP_DOSE_DQTC = 20.0  # ms; initiation cohort mean +19 ms
RESPONSE_SD_AT_REF = 25.0  # between-participant drug-response SD; total spread ~ +/-30 ms
ECG_DAYS = (1, 7, 14)

# Torsade de pointes (drug-induced only): logistic in the participant's maximum QTcF with a
# female odds ratio at equal QTc. Calibrated numerically so the top dose gives ~1.9% of men
# and ~4.1% of women (Lehmann 1996 sotalol crude rates). Because the female baseline offset
# is modelled explicitly, an extra OR of ~1.6 at equal QTc reproduces the 4.1% (Lehmann's
# ~3x adjusted odds did not separate baseline QTc). Steepness is illustrative.
TDP_BASE_AT_450 = 0.0019
TDP_LOG_OR_PER_10MS = 0.5
SCENARIOS = {
    "baseline_vulnerability": {
        "female_offset_ms": 8.0,
        "female_slope_ratio": 1.0,
        "female_tdp_or": 1.6,
        "equal_weights": False,
    },
    # Women also respond more per unit concentration (Rodriguez 2001 reported a larger
    # ibutilide QTc increase in women, without exposure adjustment).
    "slope_difference": {
        "female_offset_ms": 8.0,
        "female_slope_ratio": 1.3,
        "female_tdp_or": 1.6,
        "equal_weights": False,
    },
    "null": {
        "female_offset_ms": 0.0,
        "female_slope_ratio": 1.0,
        "female_tdp_or": 1.0,
        "equal_weights": True,
    },
}

CLASS_REFERENCE = {
    "sotalol": {
        "finding": "TdP 4.1% of women vs 1.9% of men; ~3x adjusted odds, not explained "
        "by dose or bradycardia",
        "year": 1996,
        "sources": ["Lehmann MH et al. Circulation 1996 (22 trials, 3,135 adults)"],
    },
    "ibutilide": {
        "finding": "TdP 5.6% of women vs 3.0% of men; larger QTc increase in women "
        "(59-63 vs 46 ms, low dose)",
        "year": 2001,
        "sources": ["Gowda RM et al. 2004 (pooled)", "Rodriguez I et al. JAMA 2001"],
    },
    "dofetilide": {
        "finding": "Women dose-reduced or stopped more often (55% vs 32%); TdP more "
        "frequent in women; no sex difference in exposure-adjusted QTc in healthy "
        "volunteers",
        "year": 2015,
        "sources": [
            "Duke dofetilide initiation cohort",
            "DIAMOND analyses",
            "Vicente J et al. J Electrocardiol 2015;48(6):1081-7",
        ],
    },
    "quinidine": {
        "finding": "No sex difference in exposure-adjusted QTc prolongation",
        "year": 2015,
        "sources": ["Vicente J et al. J Electrocardiol 2015"],
    },
    "class_overview": {
        "finding": "70% (95% CI 64-75%) of 332 published cardiovascular-drug TdP "
        "cases were women (case reports; reporting bias)",
        "year": 1993,
        "sources": ["Makkar RR et al. JAMA 1993;270:2590-7"],
    },
    "baseline_qtc": {
        "finding": "Post-pubertal women have longer baseline QTc than men "
        "(about 8-10 ms in one multi-formula study)",
        "year": 1992,
        "sources": ["Rautaharju PM et al. Can J Cardiol 1992", "PMC6932456"],
    },
    "dqtc_magnitude": {
        "finding": "Mean QTc +19 +/- 30 ms after initial sotalol/dofetilide dose; "
        "+11 +/- 37 ms for sotalol at >=48 h",
        "year": 2014,
        "sources": ["PMC3888125", "initiation cohort (140 patients)"],
    },
    "max_qtc_initiation": {
        "finding": "Mean maximal QTc 471 ms during sotalol/dofetilide "
        "initiation with standard dosing (517 ms with non-standard)",
        "year": 2020,
        "sources": ["PMC7313317 (379 patients)"],
    },
    "regulatory_categories": {
        "finding": "QTcF > 450/480/500 ms and increase > 30/60 ms "
        "categorical analysis; >500 or >60 commonly used to stop dosing",
        "year": 2005,
        "sources": ["ICH E14 guidance"],
    },
}

BACKGROUND = {  # illustrative rates, no drug or sex effect
    "Dizziness": (
        0.06,
        "Nervous system disorders",
        ["dizziness", "light-headed", "dizzy on standing"],
    ),
    "Fatigue": (
        0.06,
        "General disorders and administration site conditions",
        ["fatigue", "tired", "low energy"],
    ),
    "Headache": (0.07, "Nervous system disorders", ["headache", "HA", "head pain"]),
    "Nausea": (0.05, "Gastrointestinal disorders", ["nausea", "queasy", "felt sick"]),
    "Palpitations": (
        0.04,
        "Cardiac disorders",
        ["palpitations", "heart racing", "fluttering in chest"],
    ),
}
QT_VERBATIMS = [
    "QTc prolonged on ECG",
    "prolonged QT interval",
    "ECG QTcF > 500 ms",
    "QT prolongation",
]
TDP_VERBATIMS = ["torsade de pointes", "polymorphic VT (torsades) on telemetry"]


def generate(scenario, seed, out):
    cfg = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    trial = TrialWriter(STUDY, rng)
    dosed = trial.enrol(
        ARMS, N_PER_ARM, P_FEMALE, AGE, AGE_BOUNDS, equal_weights=cfg["equal_weights"]
    )
    ref_cl = CL_TYP * (WEIGHT["M"][0] / 70) ** 0.75
    ref_v = V_TYP * (WEIGHT["M"][0] / 70)
    cmax_ref = one_compartment(200.0, ref_cl, ref_v, KA, F_ORAL)[0]
    slope = TYPICAL_MALE_TOP_DOSE_DQTC / cmax_ref  # ms per ng/mL
    for p in dosed:
        female = p.sex == "F"
        if p.dose:
            cl = CL_TYP * (p.weight / 70) ** 0.75 * math.exp(rng.normal(0, OMEGA_CL))
            v = V_TYP * (p.weight / 70) * math.exp(rng.normal(0, OMEGA_V))
            trial.add_pk(p, *one_compartment(p.dose, cl, v, KA, F_ORAL))
        offset = cfg["female_offset_ms"] if female else 0.0
        base_mean = BASELINE_QTCF["M"] + offset
        baseline = rng.normal(base_mean, BASELINE_SD)
        p_slope = slope * (cfg["female_slope_ratio"] if female else 1.0)
        # Individual drug response, scaled by exposure so placebo has none.
        response = rng.normal(0, RESPONSE_SD_AT_REF) * (p.cmax / cmax_ref)
        trial.eg.append(ecg_row(p, baseline, "Y", -1))
        values = []
        for day in ECG_DAYS:
            if day > p.nights:
                break
            conc = p.cmax * rng.uniform(0.85, 1.10)
            value = (
                baseline
                + p_slope * conc
                + response * conc / max(p.cmax, 1e-9)
                + rng.normal(0, ECG_NOISE_SD)
            )
            values.append((value, day))
            trial.eg.append(ecg_row(p, value, "", day))
        if values:
            peak, peak_day = max(values)
            change = max(v - baseline for v, _ in values)
            if peak > 500 or change > 60:
                trial.add_ae(
                    p,
                    "Electrocardiogram QT prolonged",
                    "Investigations",
                    QT_VERBATIMS,
                    day=peak_day,
                    related=bool(p.dose),
                    action="DRUG WITHDRAWN" if peak > 500 else "DOSE NOT CHANGED",
                )
            odds_ratio = cfg["female_tdp_or"] if female else 1.0
            p_tdp = expit(
                logit(TDP_BASE_AT_450)
                + TDP_LOG_OR_PER_10MS * (peak - 450) / 10
                + math.log(odds_ratio)
            )
            if p.dose and rng.random() < p_tdp:
                trial.add_ae(
                    p,
                    "Torsade de pointes",
                    "Cardiac disorders",
                    TDP_VERBATIMS,
                    day=peak_day,
                    serious=True,
                    related=bool(p.dose),
                    severity="SEVERE",
                    action="DRUG WITHDRAWN",
                )
                trial.notes.append(
                    {
                        "USUBJID": p.sid,
                        "TEXT": (
                            f"SAE narrative: participant {p.sid} "
                            f"({'female' if female else 'male'}, "
                            "blinded treatment) had polymorphic ventricular tachycardia "
                            "on telemetry "
                            f"on study day {peak_day}; terminated spontaneously. Study drug "
                            "permanently discontinued. Outcome: recovered."
                        ),
                    }
                )
        for term, (rate, soc, verbatims) in BACKGROUND.items():
            if rng.random() < rate:
                trial.add_ae(p, term, soc, verbatims, day=int(rng.integers(1, p.nights + 4)))
    trial.add_realism(
        dosed,
        [
            ("Headache", BACKGROUND["Headache"][1], BACKGROUND["Headache"][2]),
            ("Fatigue", BACKGROUND["Fatigue"][1], BACKGROUND["Fatigue"][2]),
        ],
        ("Nausea", BACKGROUND["Nausea"][1], "nausea"),
    )
    trial.add_notes(
        dosed,
        [
            "No palpitations or syncope reported at the Day 7 visit.",
            "Possible light-headedness after the first dose; participant unsure.",
            "History of palpitations before enrolment, unchanged on study.",
            "Felt a bit off on Day 3, resolved without action.",
            "Participant denies fainting or chest pain.",
            "Day 7 ECG reviewed by cardiologist; QTcF increase considered related to study drug.",
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
        },
        "qtc_model": {
            "baseline_qtcf_ms": BASELINE_QTCF,
            "baseline_sd": BASELINE_SD,
            "ecg_noise_sd": ECG_NOISE_SD,
            "slope_ms_per_ng_ml": slope,
            "typical_male_top_dose_dqtc_ms": TYPICAL_MALE_TOP_DOSE_DQTC,
            "response_sd_at_reference_ms": RESPONSE_SD_AT_REF,
            "ecg_days": ECG_DAYS,
        },
        "tdp_model": {"p_at_450_ms": TDP_BASE_AT_450, "log_or_per_10_ms": TDP_LOG_OR_PER_10MS},
        "true_effects": true_effects(scenario),
        "class_reference": CLASS_REFERENCE,
    }
    (out / "truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    return len(trial.dm), len(dosed), len(trial.ae)


def ecg_row(p, value, baseline_flag, day):
    when = p.start + timedelta(days=day - 1) if day > 0 else p.start - timedelta(days=1)
    return {
        "STUDYID": STUDY,
        "USUBJID": p.sid,
        "EGTESTCD": "QTCF",
        "EGTEST": "QTcF Interval",
        "EGSTRESN": f"{value:.0f}",
        "EGSTRESU": "msec",
        "EGBLFL": baseline_flag,
        "VISIT": "BASELINE" if day < 0 else f"DAY {day}",
        "EGDTC": when.isoformat(),
    }


def true_effects(scenario):
    cfg = SCENARIOS[scenario]
    ratio = 1.0 if cfg["equal_weights"] else round(WEIGHT_EXPOSURE_RATIO, 3)
    return {
        "female_to_male_AUC_ratio_typical": ratio,
        "exposure_difference": "body weight only" if ratio > 1 else "none",
        "baseline_qtcf_female_minus_male_ms": cfg["female_offset_ms"],
        "concentration_qtc_slope_female_to_male": cfg["female_slope_ratio"],
        "torsade_female_odds_ratio_at_equal_qtc": cfg["female_tdp_or"],
        "expected_conclusion": {
            "baseline_vulnerability": "Women cross QTc outlier categories more often mainly "
            "because of longer baseline QTc (and are more TdP-prone at equal QTc); the "
            "drug's effect per unit concentration does not differ by sex. Monitoring, not "
            "dose, is the Phase II question.",
            "slope_difference": "Women have longer baseline QTc AND a steeper "
            "concentration-QTc slope; both baseline and drug response contribute.",
            "null": "No sex difference in exposure, baseline QTc, slope or TdP risk.",
        }[scenario],
        "background_terms": "Dizziness, fatigue, headache, nausea, palpitations: no drug or "
        "sex effect (illustrative rates)",
        "note": "Torsade de pointes is rare; a trial of this size usually has 0-2 cases, too "
        "few for a sex comparison.",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="baseline_vulnerability")
    ap.add_argument("--seed", type=int, default=722)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    args = ap.parse_args()
    total, dosed, records = generate(args.scenario, args.seed, args.out)
    print(
        f"{STUDY} [{args.scenario}, seed {args.seed}]: {total} DM rows, {dosed} dosed, "
        f"{records} AE records -> {args.out}"
    )


if __name__ == "__main__":
    main()
