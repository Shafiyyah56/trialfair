# SYN-318-201: synthetic antiepileptic trial with no real sex difference (data card)

**SYNTHETIC DATA.** SYN-318 is a fictional adjunctive antiseizure medicine. No real
participant, trial or result is represented, and no real patient data was used. Never present
results as real-world drug safety or as TrialFair's real-world performance.

Generator version 1.0.0. Default files in `data/`: scenario `weight_only`, seed 318.

## Purpose and hidden truth

This is the **negative control.** Women have slightly higher drug exposure (~1.14×) **only
because they weigh less**: clearance scales with body weight and there is no residual sex
effect. Drug sensitivity is identical by sex.

A correct analysis should conclude that there is **no sex difference beyond body size**, and
it should not raise sex-specific AE signals beyond chance. This tests that TrialFair does
not "cry wolf".

| Scenario | Truth |
|---|---|
| `weight_only` (default) | Female exposure ~1.135× from body weight alone |
| `hidden_sex_effect` | Female exposure 1.30×, only partly explained by weight |
| `null` | No exposure or AE difference (equal body weights) |

## Simulated trial

Phase Ib/IIa, randomised, double-blind, placebo-controlled, 14 days, adjunctive treatment in
adults (18–65) with focal epilepsy.

- Arms: placebo, SYN-318 100 mg and 200 mg; 40 randomised per arm.
- Probability of a female participant: 0.45 (illustrative).
- Files: `dm.csv`, `ae.csv` (including AEACN), `pp.csv`, `narratives.csv`, `truth.json`.

## Calibration sources (four antiseizure medicines)

| Drug | Sex and PK (label) | Somnolence | Dizziness | Fatigue | Era |
|---|---|---|---|---|---|
| levetiracetam | Cmax/AUC ~20% higher in women; **weight-adjusted clearance comparable** | 15 vs 8 | 9 vs 4 | 15 vs 9 (asthenia) | approved 1999 |
| brivaracetam | No differences between male and female subjects | 16 vs 8 | 12 vs 7 | 9 vs 4 | approved 2016 |
| lacosamide | No clinically relevant influence of gender; higher female levels from smaller V/F | 8 vs 5 (400 mg) | 30 vs 8 | — | approved 2008 |
| topiramate | Clearance not affected by gender (older label versions) | — | — | — | approved 1996 |

Rates are % drug vs placebo from pooled adjunctive label tables. Several came from
third-party copies of labels; verify on DailyMed. The topiramate statement is from archived
labels.

**Values used** (class medians): somnolence 8% → 15%, dizziness 7% → 12%, fatigue 6.5% → 12%
at 200 mg. The exposure slope is solved so the reference population's 200 mg rate equals
these medians. Body weight follows HSE 2019 means. The PK scale, half-life (~9 h) and
background AE rates are illustrative.

## Known-truth evaluation (300 trials per scenario, no LLM)

| Measure | weight_only | hidden_sex_effect | null |
|---|---|---|---|
| PK AUC ratio, mean | 1.135 | 1.30 | 1.00 |
| PK AUC ratio CI excludes 1 (per arm) | 0.23–0.25 | 0.73 | 0.05 |
| Somnolence 200 mg, women vs men CI excludes 0 | 0.04 | 0.03 | 0.07 |
| Highest per-comparison AE flag rate (any term or arm) | ≤0.04 | ≤0.03 | ≤0.07 |
| Trials with ≥1 AE comparison flagged | 0.26 | 0.25 | 0.29 |

### Reading and known tool gaps

1. **AE comparisons behave like a negative control should:** each one is flagged at about
   the chance rate. But with about 27 comparisons, roughly a quarter of trials show one
   spurious difference. TrialFair's multiplicity statement is essential here.
2. **The weight-only exposure difference is real, and TrialFair detects it in about a quarter
   of trials.** It cannot yet say the difference is explained by body weight, because
   TrialFair's PK ratio is not weight-adjusted. A weight-normalised comparison is a pending
   addition. Without it, the correct "no sex difference beyond body size" conclusion relies
   on the agents and literature (the class labels say exactly this).
3. These rates describe this synthetic design and TrialFair's deterministic statistics only.

Licence: generated with seeded NumPy PCG64; identical scenario and seed give identical
files; no third-party data. Proposed licence: CC BY 4.0, pending team confirmation.
