# SYN-401-102: synthetic Phase Ib/IIa trial dataset (data card)

**SYNTHETIC DATA.** SYN-401 is a fictional sedative-hypnotic. No real participant, trial or
result is represented, and no real patient data was used. Never present results from this
dataset as real-world drug safety or as TrialFair's real-world performance.

Generator version 2.0.0. Default files in `data/`: scenario `exposure_mediated`, seed 401.

## Purpose

This dataset tests whether TrialFair finds sex-specific safety signals and evidence gaps
that a reviewer could miss in an early-phase trial. Its truth is known because it comes
from a stated generating mechanism, so results can be evaluated against a baseline.

SYN-401 is **deliberately not modelled on any single real drug.** Its parameters come
from the published range across six approved hypnotics. Evidence for any one real drug
is therefore related-drug context, not a direct match.

## Simulated trial

Randomised, double-blind, placebo-controlled, parallel-group, 14-night dose-ranging study
in adults (18–64) with insomnia.

- Arms: placebo, SYN-401 5 mg and SYN-401 10 mg, with 40 randomised per arm.
- About 12–18 screen failures. About 1.5% are randomised but never dosed.
- Randomisation is not stratified by sex. The probability of a female participant is
  0.30, between the published Phase I (22%) and Phase II (48%) shares.

## Files (SDTM-style CSV)

| File | Content |
|---|---|
| `data/dm.csv` | One row per participant: SEX, AGE, WEIGHTKG, planned/actual arm, first/last dose dates |
| `data/ae.csv` | One row per AE record: verbatim AETERM, coded AEDECOD, AEBODSYS, AESEV, AESER, AEREL, onset/end dates |
| `data/pp.csv` | Night-1 PK per dosed participant: CMAX, AUCIFO, TMAX, LAMZHL |
| `data/narratives.csv` | SAE narratives and investigator comments (negation, uncertainty, history) |
| `data/truth.json` | Scenario, seed, every generating parameter, the six-drug class reference, and the conclusions a correct analysis should reach |
| `generate.py` | Regenerates any scenario and seed |
| `evaluate.py`, `evaluation.json` | Known-truth evaluation (below) |

AEDECOD values are plain-language terms resembling preferred terms. **No MedDRA codes are
included or generated.**

## Use in TrialFair

```sh
uv run python -m app.agents.interpreter --participant-dir fixtures/synthetic/syn401/data --synthetic
uv run python fixtures/synthetic/syn401/generate.py --scenario null --seed 7 --out /tmp/syn401_null
```

The CLI loader picks up `pp.csv` and `narratives.csv` automatically. The dashboard
now supports **Synthetic CSV upload** for these files with the matching SYN-401
curated class-context profile. See docs/SYNTHETIC_UPLOAD.md for the web flow.

## Class calibration (six approved hypnotics)

Rates are % at the highest labelled adult dose vs placebo. "—" means not taken from that
source. The years show when each source was published (or the label's era).

| Drug | Female vs male exposure | Somnolence | Dizziness | Headache | t½ (h) | Source (year) |
|---|---|---|---|---|---|---|
| zolpidem | AUC +40–50% | 15 vs 2 | 12 vs 5 | 19 vs 16 | 2.5 | Greenblatt, J Clin Pharmacol (2014); FDA DSC (2013); Ambien CR / Ambien US PI |
| suvorexant | AUC +17%, Cmax +9% | 7 vs 3 | — | — | 12 | Suvorexant AU PI (TGA, 2015); Belsomra US PI |
| lemborexant | no clinically significant difference | 10 vs 1 | — | — | 17–19 (effective) | Dayvigo US PI (approved 2019) |
| daridorexant | no clinically significant effect | 5 vs 4 (somnolence or fatigue) | 3 vs 2 | 7 vs 5 | 8 | Quviviq US PI; FDA Drug Trials Snapshot (2022) |
| eszopiclone | similar in men and women | 8 vs 3* | 7 vs 4 | — | 6 | Lunesta US PI (3 mg) |
| zaleplon | no significant difference | — | — | — | 1 | Sonata US PI |

\*Label versions disagree on the eszopiclone somnolence row. Several AE figures came from
third-party copies of labels; verify on DailyMed before quoting.

**Values used for SYN-401:**

| Parameter | Value | Basis |
|---|---|---|
| Somnolence | 3% placebo, 8% at 10 mg | Class medians |
| Dizziness | 4% placebo, 7% at 10 mg | Class medians |
| Typical half-life | ~7 h | Class median |
| Female:male exposure (default) | 1.30 | Inside the class range (1.0–1.45); matches no single drug |

The class evidence on sex is mixed: 2 of 6 drugs report higher female exposure.

## Generating mechanism

The female excess in side effects is never written in. It **emerges** from exposure.

1. **Body weight** is drawn from sex-specific Normal distributions: means 72.1 kg (women)
   and 85.4 kg (men), from HSE 2019. The SDs of 14 and 15 kg are illustrative.
2. **Clearance** = CL_typ × (weight/70)^0.75 × θ_sex (women only) × exp(η), with
   η ~ N(0, 0.35²). Weight alone gives about 1.135× female exposure. θ_sex is set so the
   typical female:male exposure equals the scenario target.
3. **Exposure** (AUC, Cmax) comes from a one-compartment oral model. The absolute
   concentration scale is illustrative for a fictional drug.
4. **AE probability** = logistic(logit(placebo rate) + β × relative exposure).
   - β is solved so the expected 10 mg rate in the reference population equals the
     class-median label rate.
   - **Somnolence and dizziness** are exposure-driven.
   - **Somnambulism** (complex sleep behaviour; FDA 2019 boxed warning for the Z-drugs)
     is rare, exposure-related and sometimes serious.
   - **Headache** is higher in women in **every arm, including placebo** (F:M ≈ 1.45),
     plus a small drug effect equal in both sexes. This is a deliberate trap: a real sex
     difference that is **not drug-related**.
   - **Nausea, fatigue, URTI, back pain and diarrhoea** have no drug or sex effect.
5. **Realistic data issues:**
   - pre-treatment screening events
   - month-only onset dates
   - repeat episodes, so occurrences exceed participants
   - screen failures and undosed participants
   - messy verbatim wording
   - narratives with negation and uncertainty

| Scenario | Truth |
|---|---|
| `exposure_mediated` (default) | Typical female exposure 1.30×, from body weight plus a residual sex effect |
| `high_exposure` | 1.45× (top of the class range) |
| `weight_only` | ~1.135×, fully explained by body weight |
| `intrinsic_sensitivity` | 1.30× plus women 1.5× more sensitive at equal exposure |
| `null` | No sex difference anywhere, including equal body weights and headache |

`--female-exposure-ratio X` sets any custom ratio. A new seed gives a fresh, unseen trial,
and `truth.json` states what should be found.

## Evaluation against a baseline

The evaluation ran 500 simulated trials per scenario with no LLM. `evaluate.py` runs
**TrialFair's own participant loader and Female-vs-Male comparison** on every trial.
Each value is the share of trials where the 95% CI excludes the null.

| Comparison (10 mg arm unless stated) | exposure_mediated | high_exposure | intrinsic_sensitivity | weight_only | null |
|---|---|---|---|---|---|
| Somnolence | 0.04 | 0.06 | 0.14 | 0.03 | 0.02 |
| Dizziness | 0.04 | 0.04 | 0.09 | 0.03 | 0.01 |
| Headache, placebo arm (true where effect present) | 0.05 | 0.05 | 0.05 | 0.05 | 0.02 |
| True-null terms (max over arms) | ≤0.026 | ≤0.022 | ≤0.018 | ≤0.020 | ≤0.016 |
| Trials with ≥1 false-positive AE comparison | 0.19 | 0.18 | 0.17 | 0.18 | 0.26 |
| PK female/male AUC ratio, median (5 mg / 10 mg) | 1.30 / 1.29 | 1.45 / 1.44 | 1.30 / 1.29 | 1.14 / 1.12 | 1.00 / 0.99 |
| PK: CI excludes 1 (5 mg / 10 mg) | 0.45 / 0.42 | 0.71 / 0.71 | 0.45 / 0.42 | 0.15 / 0.15 | 0.05 / 0.05 |

PK here uses a Welch test on log AUC within each arm, the same method as TrialFair's
`summarise_pk_by_sex`.

**Registry-style baseline** (arm totals only, as posted on ClinicalTrials.gov): no
Female-vs-Male comparison can be formed, so detection is 0 in every scenario.

### Reading

- With about 12 women per arm and class-typical effect sizes, **a trial this size almost
  never gives a conclusive AE sex difference**, even when one is real. That is the
  realistic early-phase problem TrialFair is meant to expose.
- **Participant-level PK is the more sensitive early signal.** At the top of the class
  range it is detected in about 70% of trials.
- **Per-comparison false positives are low (≤3%).** But with about 30 comparisons, 17–26%
  of trials show at least one spurious AE difference, so multiplicity must be disclosed.
- These rates describe this synthetic design and TrialFair's deterministic statistics only.
  They are not real-world performance and do not evaluate the LLM agents.

## Known limitations and pending work

- The new `exposure_response` tool has not yet been evaluated against the scenario truths.
- There is no automatic calibration check of generated vs target values.
- The demo seed was not pre-registered.
- Not yet simulated: discontinuations due to AEs, missing PK samples, and unknown-sex
  participants.
- Several AE rates come from third-party label copies; verify against DailyMed.

## Other sources

- Labots G et al. *Br J Clin Pharmacol* 2018;84(4):700–707. doi:10.1111/bcp.13497. Women
  are 22% of Phase I and 48% of Phase II participants.
- NHS Digital, Health Survey for England 2019: mean weight 85.4 kg (men) and 72.1 kg
  (women).
- Schwartz BS et al. *JAMA* 1998;279(5):381–3: headache female:male prevalence ratio
  1.16; other studies report 1.2–3.
- US FDA Drug Safety Communication, 30 April 2019: complex sleep behaviours boxed warning.
- Zucker I, Prendergast BJ. *Biol Sex Differ* 2020;11:32. Female-biased PK predicted
  female-biased ADRs.
- MSD Manual hypnotics table and product labels, for half-lives.

Values marked illustrative (absolute PK scale, SDs, between-subject variability,
absorption and age distribution) are modelling assumptions, not sourced facts.

## Licence and provenance

Generated with NumPy's seeded PCG64 generator; identical scenario and seed give identical
files. The dataset contains no third-party data. Cited sources informed parameter values
only. Proposed licence: CC BY 4.0, pending team confirmation.
