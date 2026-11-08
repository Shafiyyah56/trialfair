"""Shared helpers for TrialFair's mechanistic SYNTHETIC trial generators (SYN-722, SYN-318).

Writes SDTM-style CSVs (DM, AE, PP, EG, narratives) from a seeded NumPy generator. Nothing
here represents a real participant, trial or result. Each dataset's generate.py owns its
calibration and states its sources; this module holds only mechanics.
"""

import csv
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

# Health Survey for England 2019 measured means (kg); SDs are illustrative.
WEIGHT = {"F": (72.1, 14.0), "M": (85.4, 15.0)}
WEIGHT_BOUNDS = (45.0, 150.0)
WEIGHT_EXPOSURE_RATIO = (WEIGHT["M"][0] / WEIGHT["F"][0]) ** 0.75  # ~1.135 by allometry


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def expit(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def one_compartment(dose_mg, cl, v, ka, f_oral):
    """Cmax (ng/mL), Tmax (h), AUCinf (h*ng/mL), half-life (h) for one oral dose."""
    k = cl / v
    tmax = math.log(ka / k) / (ka - k)
    amount = f_oral * dose_mg * 1000.0
    cmax = amount * ka / (v * (ka - k)) * (math.exp(-k * tmax) - math.exp(-ka * tmax))
    return cmax, tmax, amount / cl, math.log(2) / k


@dataclass
class Participant:
    sid: str
    sex: str
    armcd: str
    arm: str
    dose: float
    weight: float
    age: int
    start: date
    nights: int
    cmax: float = 0.0
    auc: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class TrialWriter:
    """Accumulates SDTM-style rows for one synthetic trial."""

    study: str
    rng: np.random.Generator
    dm: list = field(default_factory=list)
    ae: list = field(default_factory=list)
    pp: list = field(default_factory=list)
    eg: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def enrol(
        self,
        arms,
        n_per_arm,
        p_female,
        age_mean_sd,
        age_bounds,
        equal_weights=False,
        first_screen=date(2025, 2, 3),
    ):
        """Screen failures, randomised participants and rare randomised-not-dosed cases."""
        rng, n, dosed = self.rng, 0, []
        lo, hi = age_bounds
        for _ in range(int(rng.integers(12, 19))):
            n += 1
            self.dm.append(
                self._dm_row(
                    f"{self.study}-{n:04d}",
                    "F" if rng.random() < p_female else "M",
                    int(rng.integers(lo, hi + 1)),
                    "",
                    "SCRNFAIL",
                    "Screen Failure",
                    "",
                    "",
                    None,
                    0,
                )
            )
        for armcd, arm, dose in arms:
            for _ in range(n_per_arm):
                n += 1
                sid = f"{self.study}-{n:04d}"
                sex = "F" if rng.random() < p_female else "M"
                mean, sd = WEIGHT["M" if equal_weights else sex]
                weight = float(np.clip(rng.normal(mean, sd), *WEIGHT_BOUNDS))
                age = int(np.clip(round(rng.normal(*age_mean_sd)), lo, hi))
                start = first_screen + timedelta(days=int(rng.integers(14, 100)))
                is_dosed = rng.random() > 0.015
                nights = 14 if rng.random() > 0.06 else int(rng.integers(3, 14))
                self.dm.append(
                    self._dm_row(
                        sid,
                        sex,
                        age,
                        f"{weight:.1f}",
                        armcd,
                        arm,
                        armcd if is_dosed else "NOTTRT",
                        arm if is_dosed else "Not Treated",
                        start if is_dosed else None,
                        nights,
                    )
                )
                if is_dosed:
                    dosed.append(
                        Participant(sid, sex, armcd, arm, dose, weight, age, start, nights)
                    )
        return dosed

    def _dm_row(self, sid, sex, age, weight, armcd, arm, actarmcd, actarm, start, nights):
        return {
            "STUDYID": self.study,
            "USUBJID": sid,
            "SEX": sex,
            "AGE": age,
            "WEIGHTKG": weight,
            "ARMCD": armcd,
            "ARM": arm,
            "ACTARMCD": actarmcd,
            "ACTARM": actarm,
            "RFXSTDTC": start.isoformat() if start else "",
            "RFXENDTC": (start + timedelta(days=nights - 1)).isoformat() if start else "",
        }

    def add_pk(self, p: Participant, cmax, tmax, auc, thalf, sigma=0.08):
        noise = lambda: math.exp(self.rng.normal(0, sigma))  # noqa: E731
        p.cmax, p.auc = cmax * noise(), auc * noise()
        for code, label, value, unit in (
            ("CMAX", "Max Conc", p.cmax, "ng/mL"),
            ("AUCIFO", "AUC Infinity Obs", p.auc, "h*ng/mL"),
            ("TMAX", "Time of CMAX", tmax * noise(), "h"),
            ("LAMZHL", "Half-Life Lambda z", thalf * noise(), "h"),
        ):
            self.pp.append(
                {
                    "STUDYID": self.study,
                    "USUBJID": p.sid,
                    "PPTESTCD": code,
                    "PPTEST": label,
                    "PPSTRESN": f"{value:.3g}",
                    "PPSTRESU": unit,
                    "PPSPEC": "PLASMA",
                    "VISIT": "DAY 1",
                    "PPDTC": p.start.isoformat(),
                }
            )

    def add_ae(
        self,
        p: Participant,
        term,
        soc,
        verbatims,
        *,
        day,
        serious=False,
        related=False,
        severity=None,
        action="DOSE NOT CHANGED",
    ):
        rng = self.rng
        onset = p.start + timedelta(days=day - 1)
        rel = (
            rng.choice(["RELATED", "POSSIBLY RELATED"], p=[0.6, 0.4])
            if related
            else rng.choice(
                ["NOT RELATED", "UNLIKELY RELATED", "POSSIBLY RELATED"], p=[0.6, 0.25, 0.15]
            )
        )
        self.ae.append(
            {
                "STUDYID": self.study,
                "USUBJID": p.sid,
                "AETERM": str(rng.choice(verbatims)),
                "AEDECOD": term,
                "AEBODSYS": soc,
                "AESEV": severity or str(rng.choice(["MILD", "MODERATE"], p=[0.75, 0.25])),
                "AESER": "Y" if serious else "N",
                "AEREL": str(rel),
                "AEACN": action,
                "AESTDTC": onset.isoformat(),
                "AEENDTC": (onset + timedelta(days=int(rng.integers(0, 4)))).isoformat(),
            }
        )

    def add_realism(self, dosed, pre_terms, partial_term):
        """Pre-treatment screening events and month-only onset dates (both excluded)."""
        rng = self.rng
        for p in rng.choice(dosed, size=min(8, len(dosed)), replace=False):
            term, soc, verbatims = pre_terms[int(rng.integers(len(pre_terms)))]
            onset = p.start - timedelta(days=int(rng.integers(3, 12)))
            self.ae.append(
                {
                    "STUDYID": self.study,
                    "USUBJID": p.sid,
                    "AETERM": str(rng.choice(verbatims)),
                    "AEDECOD": term,
                    "AEBODSYS": soc,
                    "AESEV": "MILD",
                    "AESER": "N",
                    "AEREL": "NOT RELATED",
                    "AEACN": "NOT APPLICABLE",
                    "AESTDTC": onset.isoformat(),
                    "AEENDTC": "",
                }
            )
        term, soc, verbatim = partial_term
        for p in rng.choice(dosed, size=min(2, len(dosed)), replace=False):
            self.ae.append(
                {
                    "STUDYID": self.study,
                    "USUBJID": p.sid,
                    "AETERM": verbatim,
                    "AEDECOD": term,
                    "AEBODSYS": soc,
                    "AESEV": "MILD",
                    "AESER": "N",
                    "AEREL": "NOT RELATED",
                    "AEACN": "DOSE NOT CHANGED",
                    "AESTDTC": p.start.isoformat()[:7],
                    "AEENDTC": "",
                }
            )

    def add_notes(self, dosed, texts):
        for p, text in zip(
            self.rng.choice(dosed, size=len(texts), replace=False), texts, strict=True
        ):
            self.notes.append({"USUBJID": p.sid, "TEXT": text})

    def write(self, out: Path):
        out.mkdir(parents=True, exist_ok=True)
        order = np.argsort([r["USUBJID"] + r["AESTDTC"] for r in self.ae], kind="stable")
        ae = [self.ae[i] for i in order]
        seq = {}
        for r in ae:
            seq[r["USUBJID"]] = seq.get(r["USUBJID"], 0) + 1
            r["AESEQ"] = seq[r["USUBJID"]]
        write_csv(out / "dm.csv", self.dm)
        write_csv(out / "ae.csv", ae, first=["STUDYID", "USUBJID", "AESEQ"])
        write_csv(out / "pp.csv", self.pp)
        if self.eg:
            write_csv(out / "eg.csv", self.eg)
        write_csv(out / "narratives.csv", self.notes, fields=["USUBJID", "TEXT"])


def write_csv(path, rows, first=(), fields=None):
    if fields is None:
        if not rows:
            path.write_text("")
            return
        fields = list(first) + [k for k in rows[0] if k not in first]
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
