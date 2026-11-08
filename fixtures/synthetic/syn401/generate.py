"""SYN-401-102: mechanistic SYNTHETIC Phase Ib/IIa trial for TrialFair (not committed).

SYNTHETIC DATA. SYN-401 is a fictional sedative-hypnotic. No real participant, trial or
result is represented. It is deliberately NOT modelled on any single drug: parameters
are calibrated to the published range across six approved hypnotics (CLASS_REFERENCE),
so evidence found for any one real drug is related-drug context, never a direct match.

Generating model (per participant i):
  sex_i       ~ Bernoulli(p_female)                       (randomisation not sex-stratified)
  weight_i    ~ Normal(sex-specific mean, SD), truncated  (HSE 2019 means)
  CL_i        = CL_typ * (weight_i/70)^0.75 * theta_sex^[female] * exp(eta_CL)
  V_i         = V_typ  * (weight_i/70)       * exp(eta_V)
  AUC_i, Cmax_i from a one-compartment oral model, night-1 dose (PP domain)
  E_i         = AUC_i / AUC_ref  (typical 85.4 kg man at 10 mg; 0 on placebo)
  P(AE_k)     = logistic(logit(p0_k) + beta_k * s_sex * E_i)
theta_sex is set from the scenario's target female:male exposure ratio. beta_k is
solved so the expected 10 mg rate in the reference population equals the class-median
label rate. Headache has a sex difference in every arm (baseline epidemiology, not a
drug effect). Other events have no drug or sex effect.

Usage:
  python generate.py                        # default scenario, seed 401
  python generate.py --scenario null --seed 7 --out runs/null_7
  python generate.py --female-exposure-ratio 1.17 --seed 3 --out runs/custom
Writes dm.csv, ae.csv, pp.csv, narratives.csv, truth.json into --out.
"""

import argparse
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from scipy.optimize import brentq

GENERATOR_VERSION = "2.0.0"
STUDY = "SYN-401-102"
ARMS = [("PBO", "Placebo", 0.0), ("SYN5", "SYN-401 5 mg", 5.0), ("SYN10", "SYN-401 10 mg", 10.0)]
N_PER_ARM = 40
P_FEMALE = 0.30  # between published Phase I (22%) and Phase II (48%) shares: Labots 2018

# --- Class reference: what the published labels/literature report for approved hypnotics.
# Rates are % at the highest labelled adult dose vs placebo; None = not reported in the
# reviewed source. female_exposure is the reported female:male AUC ratio, or a verbal
# label conclusion where no ratio is published.
CLASS_REFERENCE = {
    "zolpidem": {
        "female_exposure": 1.45,
        "female_exposure_note": "AUC 40-50% higher in women",
        "somnolence": (15, 2),
        "dizziness": (12, 5),
        "headache": (19, 16),
        "half_life_h": 2.5,
        "sources": [
            "Greenblatt 2014 J Clin Pharmacol 54:282",
            "FDA DSC Jan/May 2013",
            "Ambien CR US PI (12.5 mg adult table)",
            "Ambien US PI 12.3",
        ],
    },
    "suvorexant": {
        "female_exposure": 1.17,
        "female_exposure_note": "AUC +17%, Cmax +9% in women",
        "somnolence": (7, 3),
        "dizziness": None,
        "headache": None,
        "half_life_h": 12,
        "sources": ["Suvorexant AU product information (TGA)", "Belsomra US PI"],
    },
    "lemborexant": {
        "female_exposure": 1.0,
        "female_exposure_note": "no clinically significant sex difference (label)",
        "somnolence": (10, 1),
        "dizziness": None,
        "headache": None,
        "half_life_h": 18,
        "sources": ["Dayvigo US PI 12.3 and highlights (10 mg)"],
    },
    "daridorexant": {
        "female_exposure": 1.0,
        "female_exposure_note": "no clinically significant sex effect (label)",
        "somnolence": (5, 4),
        "dizziness": (3, 2),
        "headache": (7, 5),
        "half_life_h": 8,
        "sources": ["Quviviq US PI", "FDA Drug Trials Snapshot: Quviviq"],
    },
    "eszopiclone": {
        "female_exposure": 1.0,
        "female_exposure_note": "PK similar in men and women (label)",
        "somnolence": (8, 3),
        "dizziness": (7, 4),
        "headache": None,
        "half_life_h": 6,
        "sources": [
            "Lunesta US PI (3 mg, 6-week adult table; somnolence row "
            "differs between label versions)"
        ],
    },
    "zaleplon": {
        "female_exposure": 1.0,
        "female_exposure_note": "no significant PK difference by sex (label)",
        "somnolence": None,
        "dizziness": None,
        "headache": None,
        "half_life_h": 1,
        "sources": ["Sonata US PI"],
    },
}


def _class_median(key, index):
    values = [v[key][index] for v in CLASS_REFERENCE.values() if v.get(key)]
    return float(np.median(values)) / 100.0


# --- Pharmacokinetics (fictional; absolute scale illustrative) --------------------------
WEIGHT = {"F": (72.1, 14.0), "M": (85.4, 15.0)}  # mean from HSE 2019; SD illustrative
WEIGHT_BOUNDS = (45.0, 150.0)
WEIGHT_EXPOSURE_RATIO = (WEIGHT["M"][0] / WEIGHT["F"][0]) ** 0.75  # ~1.135 from weight alone
CL_TYP = 6.0  # L/h at 70 kg, male
V_TYP = 60.0  # L at 70 kg -> typical half-life ~7 h (class median of 1-18 h)
KA = 2.0  # 1/h
F_ORAL = 0.70
OMEGA_CL, OMEGA_V = 0.35, 0.20  # between-subject SD on log scale (illustrative)
SIGMA_PROP = 0.08  # residual noise on derived PK parameters

SCENARIOS = {
    # Default: typical female:male exposure 1.30, inside the class range (1.0-1.45) and
    # not equal to any single drug. Weight explains ~1.135; the rest is a residual sex effect.
    "exposure_mediated": {
        "female_exposure_ratio": 1.30,
        "female_pd_sensitivity": 1.0,
        "equal_weights": False,
        "headache_sex_effect": True,
    },
    # Upper end of the class (zolpidem-like magnitude).
    "high_exposure": {
        "female_exposure_ratio": 1.45,
        "female_pd_sensitivity": 1.0,
        "equal_weights": False,
        "headache_sex_effect": True,
    },
    # Exposure difference explained entirely by body weight (most class labels: no
    # clinically significant sex effect once size is considered).
    "weight_only": {
        "female_exposure_ratio": WEIGHT_EXPOSURE_RATIO,
        "female_pd_sensitivity": 1.0,
        "equal_weights": False,
        "headache_sex_effect": True,
    },
    # As default, plus women 1.5x more sensitive at equal exposure (Greenblatt 2014 proposed
    # greater intrinsic sensitivity as part of the zolpidem sex effect).
    "intrinsic_sensitivity": {
        "female_exposure_ratio": 1.30,
        "female_pd_sensitivity": 1.5,
        "equal_weights": False,
        "headache_sex_effect": True,
    },
    # No sex difference anywhere: for false-positive evaluation.
    "null": {
        "female_exposure_ratio": 1.0,
        "female_pd_sensitivity": 1.0,
        "equal_weights": True,
        "headache_sex_effect": False,
    },
}

# --- Adverse events -----------------------------------------------------------------------
AE_MODEL = {
    "Somnolence": {
        "p0": _class_median("somnolence", 1),
        "target_top_dose": _class_median("somnolence", 0),
        "exposure": True,
    },
    "Dizziness": {
        "p0": _class_median("dizziness", 1),
        "target_top_dose": _class_median("dizziness", 0),
        "exposure": True,
    },
    # Rare complex sleep behaviour (FDA 2019 boxed warning across the Z-drugs).
    "Somnambulism": {"p0": 0.001, "target_top_dose": 0.010, "exposure": True, "serious_prob": 0.5},
    # Headache: class placebo rates 5-16% (median ~10%); female:male ~1.45 in every arm
    # (population ratios 1.16-3); small drug effect equal in both sexes (+2-3 points).
    "Headache": {"p0_by_sex": {"M": 0.09, "F": 0.13}, "drug_logit_shift": 0.25},
    "Nausea": {"p0": 0.05},
    "Fatigue": {"p0": 0.05},
    "Upper respiratory tract infection": {"p0": 0.04},
    "Back pain": {"p0": 0.03},
    "Diarrhoea": {"p0": 0.03},
}

# Investigator verbatim wording (AETERM). Coded term (AEDECOD) is separate, as in SDTM.
VERBATIMS = {
    "Somnolence": [
        "drowsiness",
        "daytime sleepiness",
        "drowsy next morning",
        "excessive sleepiness AM",
        "somnolence",
        "sleepy until midday",
        "groggy on waking",
    ],
    "Dizziness": [
        "dizziness",
        "dizzy spells",
        "light-headedness",
        "felt dizzy on standing",
        "giddiness",
        "dizzy",
    ],
    "Somnambulism": [
        "sleepwalking",
        "sleep walking episode, no recall",
        "found in kitchen at night, no memory of event",
    ],
    "Headache": [
        "headache",
        "HA",
        "frontal headache",
        "tension headache",
        "head pain",
        "headache on waking",
    ],
    "Nausea": ["nausea", "nauseous", "queasy", "felt sick", "nausea after breakfast"],
    "Fatigue": ["fatigue", "tiredness", "tired", "lethargy", "low energy"],
    "Upper respiratory tract infection": [
        "common cold",
        "URTI",
        "cold symptoms",
        "sore throat and runny nose",
    ],
    "Back pain": ["back pain", "lower back ache", "LBP"],
    "Diarrhoea": ["diarrhoea", "loose stools", "diarrhea"],
}
SOC = {
    "Somnolence": "Nervous system disorders",
    "Dizziness": "Nervous system disorders",
    "Headache": "Nervous system disorders",
    "Somnambulism": "Psychiatric disorders",
    "Nausea": "Gastrointestinal disorders",
    "Diarrhoea": "Gastrointestinal disorders",
    "Fatigue": "General disorders and administration site conditions",
    "Upper respiratory tract infection": "Infections and infestations",
    "Back pain": "Musculoskeletal and connective tissue disorders",
}

OTHER_SOURCES = {
    "phase_female_shares": (
        "Labots G et al. Br J Clin Pharmacol 2018;84(4):700-707. doi:10.1111/bcp.13497"
    ),
    "body_weight_means": (
        "Health Survey for England 2019 (NHS Digital): mean 85.4 kg men, 72.1 kg women"
    ),
    "headache_sex_ratio": (
        "Schwartz BS et al. JAMA 1998;279(5):381-3 (episodic TTH prevalence ratio 1.16); "
        "reviews report 1.16-3"
    ),
    "complex_sleep_behaviour": "FDA Drug Safety Communication, 30 Apr 2019 (boxed warning)",
    "pk_predicts_adr_direction": (
        "Zucker I, Prendergast BJ. Biol Sex Differ 2020;11:32. doi:10.1186/s13293-020-00308-5"
    ),
    "half_lives": "MSD Manual hypnotics table; product labels (lemborexant effective t1/2 17-19 h)",
}


def logit(p):
    return math.log(p / (1 - p))


def expit(x):
    return 1 / (1 + math.exp(-x))


def one_compartment(dose_mg, cl, v):
    """Cmax (ng/mL), Tmax (h), AUCinf (h*ng/mL), half-life (h) for a single oral dose."""
    k = cl / v
    tmax = math.log(KA / k) / (KA - k)
    amount = F_ORAL * dose_mg * 1000.0  # ug -> ng/mL when divided by V in L
    cmax = amount * KA / (v * (KA - k)) * (math.exp(-k * tmax) - math.exp(-KA * tmax))
    auc = amount / cl
    return cmax, tmax, auc, math.log(2) / k


def theta_for(cfg):
    """Female clearance multiplier after weight scaling, from the target exposure ratio."""
    weight_ratio = 1.0 if cfg["equal_weights"] else WEIGHT_EXPOSURE_RATIO
    return weight_ratio / cfg["female_exposure_ratio"]


AUC_REF = F_ORAL * 10.0 * 1000.0 / (CL_TYP * (WEIGHT["M"][0] / 70) ** 0.75)


def _reference_exposures(n=20000, seed=20261108):
    """Exposures at 10 mg in the default scenario's reference population (fixed seed)."""
    rng = np.random.default_rng(seed)
    theta = theta_for(SCENARIOS["exposure_mediated"])
    female = rng.random(n) < P_FEMALE
    mean = np.where(female, WEIGHT["F"][0], WEIGHT["M"][0])
    sd = np.where(female, WEIGHT["F"][1], WEIGHT["M"][1])
    weight = np.clip(rng.normal(mean, sd), *WEIGHT_BOUNDS)
    cl = CL_TYP * (weight / 70) ** 0.75 * np.where(female, theta, 1.0)
    cl *= np.exp(rng.normal(0, OMEGA_CL, n))
    return F_ORAL * 10.0 * 1000.0 / cl / AUC_REF


def _calibrate_betas():
    exposures = _reference_exposures()
    betas = {}
    for term, m in AE_MODEL.items():
        if m.get("exposure"):
            a = logit(m["p0"])
            betas[term] = brentq(
                lambda b, a=a, t=m["target_top_dose"]: (
                    float(np.mean(1 / (1 + np.exp(-(a + b * exposures))))) - t
                ),
                0.0,
                20.0,
            )
    return betas


def generate(scenario, seed, out):
    cfg = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)
    theta = theta_for(cfg)
    betas = _calibrate_betas()

    first_screen = date(2025, 2, 3)
    dm, ae, pp, notes = [], [], [], []
    subjects = []
    n = 0
    # Screen failures: consented, never randomised or dosed.
    for _ in range(int(rng.integers(12, 19))):
        n += 1
        sex = "F" if rng.random() < P_FEMALE else "M"
        dm.append(
            {
                "STUDYID": STUDY,
                "USUBJID": f"{STUDY}-{n:04d}",
                "SEX": sex,
                "AGE": int(rng.integers(18, 65)),
                "WEIGHTKG": "",
                "ARMCD": "SCRNFAIL",
                "ARM": "Screen Failure",
                "ACTARMCD": "",
                "ACTARM": "",
                "RFXSTDTC": "",
                "RFXENDTC": "",
            }
        )
    for armcd, arm, dose in ARMS:
        for _ in range(N_PER_ARM):
            n += 1
            sid = f"{STUDY}-{n:04d}"
            sex = "F" if rng.random() < P_FEMALE else "M"
            mean, sd = WEIGHT["M" if cfg["equal_weights"] else sex]
            weight = float(np.clip(rng.normal(mean, sd), *WEIGHT_BOUNDS))
            age = int(np.clip(round(rng.normal(45, 12)), 18, 64))
            start = first_screen + timedelta(days=int(rng.integers(14, 100)))
            dosed = rng.random() > 0.015  # rare: randomised but never dosed
            nights = 14 if rng.random() > 0.06 else int(rng.integers(3, 14))
            dm.append(
                {
                    "STUDYID": STUDY,
                    "USUBJID": sid,
                    "SEX": sex,
                    "AGE": age,
                    "WEIGHTKG": f"{weight:.1f}",
                    "ARMCD": armcd,
                    "ARM": arm,
                    "ACTARMCD": armcd if dosed else "NOTTRT",
                    "ACTARM": arm if dosed else "Not Treated",
                    "RFXSTDTC": start.isoformat() if dosed else "",
                    "RFXENDTC": (start + timedelta(days=nights - 1)).isoformat() if dosed else "",
                }
            )
            if not dosed:
                continue
            female = sex == "F"
            cl = CL_TYP * (weight / 70) ** 0.75 * (theta if female else 1.0)
            cl *= math.exp(rng.normal(0, OMEGA_CL))
            v = V_TYP * (weight / 70) * math.exp(rng.normal(0, OMEGA_V))
            exposure = 0.0
            if dose:
                cmax, tmax, auc, thalf = one_compartment(dose, cl, v)
                noise = lambda: math.exp(rng.normal(0, SIGMA_PROP))  # noqa: E731
                cmax, auc = cmax * noise(), auc * noise()
                exposure = auc / AUC_REF
                for code, label, value, unit in (
                    ("CMAX", "Max Conc", cmax, "ng/mL"),
                    ("AUCIFO", "AUC Infinity Obs", auc, "h*ng/mL"),
                    ("TMAX", "Time of CMAX", tmax * noise(), "h"),
                    ("LAMZHL", "Half-Life Lambda z", thalf * noise(), "h"),
                ):
                    pp.append(
                        {
                            "STUDYID": STUDY,
                            "USUBJID": sid,
                            "PPTESTCD": code,
                            "PPTEST": label,
                            "PPSTRESN": f"{value:.3g}",
                            "PPSTRESU": unit,
                            "PPSPEC": "PLASMA",
                            "VISIT": "NIGHT 1",
                            "PPDTC": start.isoformat(),
                        }
                    )
            subjects.append(
                {
                    "sid": sid,
                    "sex": sex,
                    "armcd": armcd,
                    "start": start,
                    "nights": nights,
                    "exposure": exposure,
                    "dose": dose,
                }
            )

    for s in subjects:
        female = s["sex"] == "F"
        for term, m in AE_MODEL.items():
            if "p0_by_sex" in m:
                p0 = m["p0_by_sex"]["F" if female and cfg["headache_sex_effect"] else "M"]
                p = expit(logit(p0) + (m["drug_logit_shift"] if s["dose"] else 0.0))
            elif m.get("exposure"):
                beta = betas[term]
                if female:
                    beta *= cfg["female_pd_sensitivity"]
                p = expit(logit(m["p0"]) + beta * s["exposure"])
            else:
                p = m["p0"]
            if rng.random() >= p:
                continue
            episodes = 1 + (int(rng.poisson(0.8)) if term in {"Somnolence", "Headache"} else 0)
            early = m.get("exposure", False)
            for e in range(episodes):
                day = (
                    int(rng.integers(1, 4))
                    if early and e == 0
                    else int(rng.integers(1, s["nights"] + 4))
                )
                onset = s["start"] + timedelta(days=day - 1)
                if early:
                    sev = (
                        "SEVERE"
                        if s["exposure"] > 1.6 and rng.random() < 0.3
                        else ("MODERATE" if rng.random() < 0.35 + 0.15 * s["exposure"] else "MILD")
                    )
                    rel = rng.choice(["RELATED", "POSSIBLY RELATED"], p=[0.6, 0.4])
                else:
                    sev = rng.choice(["MILD", "MODERATE"], p=[0.75, 0.25])
                    rel = rng.choice(
                        ["NOT RELATED", "UNLIKELY RELATED", "POSSIBLY RELATED"], p=[0.6, 0.25, 0.15]
                    )
                serious = "Y" if rng.random() < m.get("serious_prob", 0.0) else "N"
                ae.append(
                    {
                        "STUDYID": STUDY,
                        "USUBJID": s["sid"],
                        "AETERM": str(rng.choice(VERBATIMS[term])),
                        "AEDECOD": term,
                        "AEBODSYS": SOC[term],
                        "AESEV": sev,
                        "AESER": serious,
                        "AEREL": rel,
                        "AESTDTC": onset.isoformat(),
                        "AEENDTC": (onset + timedelta(days=int(rng.integers(0, 4)))).isoformat(),
                    }
                )
                if serious == "Y":
                    notes.append(
                        {
                            "USUBJID": s["sid"],
                            "TEXT": (
                                f"SAE narrative: participant {s['sid']} "
                                f"({'female' if female else 'male'},"
                                f" blinded treatment) experienced {term.lower()} on study day {day}"
                                " with no recollection of the event. Assessed as an"
                                " important medical"
                                " event; study drug interrupted. Outcome: recovered."
                            ),
                        }
                    )

    # Pre-treatment events reported during screening (pre-existing; must be excluded).
    for s in rng.choice(subjects, size=8, replace=False):
        term = str(rng.choice(["Headache", "Upper respiratory tract infection", "Back pain"]))
        onset = s["start"] - timedelta(days=int(rng.integers(3, 12)))
        ae.append(
            {
                "STUDYID": STUDY,
                "USUBJID": s["sid"],
                "AETERM": str(rng.choice(VERBATIMS[term])),
                "AEDECOD": term,
                "AEBODSYS": SOC[term],
                "AESEV": "MILD",
                "AESER": "N",
                "AEREL": "NOT RELATED",
                "AESTDTC": onset.isoformat(),
                "AEENDTC": "",
            }
        )
    # Partial onset dates (month only): undeterminable, must be excluded and disclosed.
    for s in rng.choice(subjects, size=2, replace=False):
        ae.append(
            {
                "STUDYID": STUDY,
                "USUBJID": s["sid"],
                "AETERM": "back pain",
                "AEDECOD": "Back pain",
                "AEBODSYS": SOC["Back pain"],
                "AESEV": "MILD",
                "AESER": "N",
                "AEREL": "NOT RELATED",
                "AESTDTC": s["start"].isoformat()[:7],
                "AEENDTC": "",
            }
        )
    # Investigator visit comments: negation, uncertainty, pre-existing, attribution.
    for s, text in zip(
        rng.choice(subjects, size=6, replace=False),
        [
            "No dizziness reported at the Day 7 visit.",
            "Possible drowsiness the morning after first dose; participant unsure.",
            "History of tension headaches before enrolment, unchanged on study.",
            "Felt a bit off on Day 2, resolved without action.",
            "Participant denies sleepwalking or night-time activity.",
            "Moderate next-morning drowsiness, considered related to study drug "
            "by the investigator.",
        ],
        strict=True,
    ):
        notes.append({"USUBJID": s["sid"], "TEXT": text})

    order = np.argsort([r["USUBJID"] + r["AESTDTC"] for r in ae], kind="stable")
    ae = [ae[i] for i in order]
    seq = {}
    for r in ae:
        seq[r["USUBJID"]] = seq.get(r["USUBJID"], 0) + 1
        r["AESEQ"] = seq[r["USUBJID"]]

    write_csv(out / "dm.csv", dm)
    write_csv(out / "ae.csv", ae, first=["STUDYID", "USUBJID", "AESEQ"])
    write_csv(out / "pp.csv", pp)
    write_csv(out / "narratives.csv", notes)
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
            "CL_typ_L_per_h_70kg_male": CL_TYP,
            "V_typ_L_70kg": V_TYP,
            "ka": KA,
            "F": F_ORAL,
            "omega_CL": OMEGA_CL,
            "omega_V": OMEGA_V,
            "sigma_prop": SIGMA_PROP,
            "auc_ref": AUC_REF,
            "theta_sex_after_weight": theta,
        },
        "ae_model": AE_MODEL,
        "calibrated_exposure_slopes": betas,
        "true_effects": true_effects(scenario),
        "class_reference": CLASS_REFERENCE,
        "other_sources": OTHER_SOURCES,
    }
    (out / "truth.json").write_text(json.dumps(truth, indent=2) + "\n")
    return len(dm), len(subjects), len(ae)


def true_effects(scenario):
    """What a correct analysis should conclude, independent of sampling noise."""
    cfg = SCENARIOS[scenario]
    ratio = round(cfg["female_exposure_ratio"], 3)
    exposure_driven = ratio > 1.001 or cfg["female_pd_sensitivity"] > 1
    return {
        "expected_female_to_male_AUC_ratio_typical": ratio,
        "Somnolence": "female > male in active arms only"
        if exposure_driven
        else "no sex difference",
        "Dizziness": "female > male in active arms only (weaker effect)"
        if exposure_driven
        else "no sex difference",
        "Somnambulism": "rare and exposure-related; too sparse for a sex comparison",
        "Headache": "female > male in ALL arms including placebo (baseline epidemiology, "
        "not drug-related)"
        if cfg["headache_sex_effect"]
        else "no sex difference",
        "Nausea, Fatigue, URTI, Back pain, Diarrhoea": "no drug or sex effect",
        "class_evidence_note": "Published hypnotic evidence is mixed (2 of 6 class drugs "
        "report higher female exposure). It is related-drug context for SYN-401, not "
        "direct evidence; this trial's own PK is the drug-specific evidence.",
        "mechanism": {
            "exposure_mediated": "lower female clearance: body weight plus a residual sex effect",
            "high_exposure": "as default, at the upper end of the class range",
            "weight_only": "female exposure difference fully explained by body weight",
            "intrinsic_sensitivity": "lower female clearance plus greater female sensitivity",
            "null": "none",
        }.get(scenario, "custom female exposure ratio"),
    }


def write_csv(path, rows, first=()):
    if not rows:
        path.write_text("")
        return
    fields = list(first) + [k for k in rows[0] if k not in first]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="exposure_mediated")
    ap.add_argument("--seed", type=int, default=401)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "data")
    ap.add_argument(
        "--female-exposure-ratio",
        type=float,
        default=None,
        help="Override the scenario's typical female:male AUC ratio",
    )
    args = ap.parse_args()
    if args.female_exposure_ratio is not None:
        if not 0.5 <= args.female_exposure_ratio <= 3.0:
            ap.error("--female-exposure-ratio must be between 0.5 and 3.0")
        SCENARIOS["custom"] = dict(
            SCENARIOS[args.scenario], female_exposure_ratio=args.female_exposure_ratio
        )
        args.scenario = "custom"
    total, dosed, records = generate(args.scenario, args.seed, args.out)
    print(
        f"{STUDY} [{args.scenario}, seed {args.seed}]: {total} DM rows, {dosed} dosed, "
        f"{records} AE records -> {args.out}"
    )


if __name__ == "__main__":
    main()
