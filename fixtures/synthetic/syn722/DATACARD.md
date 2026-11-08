# SYN-722-201: synthetic QT-prolonging drug trial (data card)

**SYNTHETIC DATA.** SYN-722 is a fictional class III-type antiarrhythmic. No real participant,
trial or result is represented, and no real patient data was used. Never present results as
real-world drug safety or as TrialFair's real-world performance.

Generator version 1.0.0. Default files in `data/`: scenario `baseline_vulnerability`, seed 722.

## Purpose and hidden truth

This dataset shows a sex difference that is **not** caused by exposure or by a stronger drug
effect. It contrasts with SYN-401 (exposure-driven) and SYN-318 (no real difference).

Default truth:

- **Exposure** differs by sex only through body weight (~1.14× female AUC). There is no
  residual sex effect on clearance.
- **The drug's QTcF effect per unit concentration is the same in women and men.**
- **Women start with a ~8 ms longer baseline QTcF.** Torsade de pointes is calibrated to the
  published rates: on the top dose, about 1.9% of men vs 4.1% of women.
- Women therefore cross ICH E14 outlier categories (QTcF > 500 ms, increase > 60 ms) more
  often because of **baseline vulnerability**. The Phase II question is monitoring, not dose.

| Scenario | Truth |
|---|---|
| `baseline_vulnerability` (default) | Female baseline +8 ms; same slope; female TdP OR 1.6 at equal QTc |
| `slope_difference` | As default, plus a female concentration-QTc slope 1.3× steeper |
| `null` | No sex difference in exposure, baseline, slope or TdP risk |

## Simulated trial

Phase Ib/IIa, randomised, double-blind, placebo-controlled, 14 days, in adults (40–79) with
paroxysmal atrial fibrillation.

- Arms: placebo, SYN-722 100 mg and 200 mg; 40 randomised per arm.
- Probability of a female participant: 0.35 (illustrative).
- Screen failures and rare undosed participants are included.

Files are `dm.csv`, `ae.csv` (including AEACN), `pp.csv`, `eg.csv`, `narratives.csv` and
`truth.json`. `eg.csv` holds QTcF at baseline (EGBLFL=Y) and on days 1, 7 and 14.

## Calibration sources (multiple drugs; evidence is mixed)

| Source | Finding used | Year |
|---|---|---|
| Lehmann MH et al., *Circulation* (sotalol, 22 trials, 3,135 adults) | TdP 4.1% women vs 1.9% men; ~3× adjusted odds | 1996 |
| Makkar RR et al., *JAMA* | 70% of 332 published cardiovascular-drug TdP cases were women (case reports, reporting bias) | 1993 |
| Rodriguez I et al., *JAMA* (ibutilide) | Larger QTc increase in women (59–63 vs 46 ms), not exposure-adjusted | 2001 |
| Gowda RM et al. (ibutilide, pooled) | TdP 5.6% women vs 3.0% men | 2004 |
| Vicente J et al., *J Electrocardiol* 48:1081 (dofetilide, quinidine, ranolazine) | **No** sex difference in exposure-adjusted QTc prolongation | 2015 |
| Duke dofetilide initiation cohort | Women dose-reduced or stopped more (55% vs 32%) | 2010s |
| PMC3888125 and initiation cohort | QTc +19 ± 30 ms after initial sotalol/dofetilide dose | 2014 |
| PMC7313317 (379 patients) | Mean maximal QTc 471 ms during standard-dose initiation | 2020 |
| Rautaharju PM et al. 1992; PMC6932456 | Women have longer baseline QTc (~8–10 ms in one study) | 1992 / 2019 |
| ICH E14 | QTcF > 450/480/500 ms and increase > 30/60 ms categories | 2005 |

**How the model uses these:**

| Parameter | Value | Basis |
|---|---|---|
| Male baseline QTcF | 448 ms (SD 18, illustrative) | Expected maximum on the top dose ≈ 471 ms |
| Typical top-dose ΔQTcF | +20 ms | Initiation cohort mean +19 ms |
| Response variation | Individual SD 25 ms, scaled by exposure | Total spread ≈ ±30 ms |
| TdP probability | Logistic in maximum QTcF; drug-induced only | Calibrated numerically to 1.9% / 4.1% |
| TdP female OR at equal QTc | 1.6 | The explicit baseline offset explains the rest of Lehmann's crude excess |
| PK scale, half-life (~7 h), background AE rates | — | Illustrative |

## Known-truth evaluation (300 trials per scenario, no LLM)

`fixtures/synthetic/evaluate_participant_sets.py syn722` runs TrialFair's loader,
Female-vs-Male AE comparison, `summarise_pk_by_sex` and `summarise_qtc_by_sex` on each trial.
Each value is the share of trials where the 95% interval excludes the null.

| Measure | baseline_vulnerability | slope_difference | null |
|---|---|---|---|
| "QT prolonged" AE, women vs men, 200 mg | 0.12 | 0.28 | 0.05 |
| Torsade de pointes, women vs men, 200 mg | 0.09 | 0.10 | 0.005 |
| Concentration-QTc slope difference | 0.18 | 0.25 | **0.18 (false alarms)** |
| Mean max ΔQTcF difference, 200 mg | 0.05 | 0.18 | 0.07 |
| PK AUC ratio (mean ≈ 1.14 by weight), CI excludes 1 | 0.17–0.20 | 0.16–0.17 | 0.04 |
| Trials with ≥1 non-QT AE comparison flagged | 0.15 | 0.15 | 0.24 |

### Reading and known tool gaps

1. **The concentration-QTc slope test is miscalibrated.** Response variability grows with
   concentration, so ordinary least-squares CIs are too narrow: 18% false alarms under the
   null. Checked independently: heteroscedasticity-robust (HC3) CIs give 5.7%. This is a
   pending fix in `app/services/statistics.py`.
2. **Baseline QTc differences are not tested.** The tool analyses change from baseline,
   which removes the baseline offset by design ("female offset" ≈ 0). A pre-dose
   Female-vs-Male baseline comparison is a pending addition.
3. TdP and outlier categories are sparse, so detection is low at this trial size. That is
   realistic. The data supports "monitor women closely in Phase II", not a definitive
   conclusion.
4. These rates describe this synthetic design and TrialFair's deterministic statistics only.

Licence: generated with seeded NumPy PCG64; identical scenario and seed give identical
files; no third-party data. Proposed licence: CC BY 4.0, pending team confirmation.
