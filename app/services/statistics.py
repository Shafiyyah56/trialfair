"""Allowlisted deterministic exploratory analyses over validated server datasets."""

import math
import statistics as pystats
import warnings
from typing import Literal
from uuid import uuid4

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from scipy import stats
from scipy.stats import fisher_exact
from statsmodels.stats.proportion import confint_proportions_2indep

from app.context import ToolContext
from app.contracts import (
    AnalysisRequest,
    AnalysisResult,
    ScreeningOutput,
    SourceLocator,
    TrialBundle,
)
from app.services.participant_data import EXPOSURE_PARAMETERS, participant_table_for
from app.validation import validate_screening

# ICH E14 categorical QTc analysis categories (absolute values and change from baseline).
QTC_ABSOLUTE_CATEGORIES_MS = (450, 480, 500)
QTC_CHANGE_CATEGORIES_MS = (30, 60)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row_ids: list[str] = Field(default_factory=list)


class ExposureSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    term: str = Field(min_length=1, max_length=200)
    exposure_parameter: Literal[EXPOSURE_PARAMETERS] | None = None


class NoParameters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


PARAMETER_MODELS = {
    "summarise_representation": Selection,
    "audit_subgroup_availability": Selection,
    "compare_adverse_event_rates": Selection,
    "summarise_pk_by_sex": Selection,
    "exposure_response": ExposureSelection,
    "summarise_qtc_by_sex": NoParameters,
}


def _female_male(sex: str) -> bool | None:
    folded = (sex or "").casefold()
    return True if folded == "female" else False if folded == "male" else None


def _log_ratio_ci(female: list[float], male: list[float]) -> dict:
    """Female/male geometric mean ratio with a Welch 95% CI on the log scale."""
    f, m = np.log(female), np.log(male)
    test = stats.ttest_ind(f, m, equal_var=False)
    ci = test.confidence_interval(0.95)
    return {
        "geometric_mean_ratio": float(math.exp(f.mean() - m.mean())),
        "ratio_ci95": [float(math.exp(ci.low)), float(math.exp(ci.high))],
        "welch_p_value": float(test.pvalue),
        "n_female": len(female),
        "n_male": len(male),
    }


def summarise_representation(bundle: TrialBundle, rows):
    return {
        "rows": [
            {
                "row_id": r.row_id,
                "category": r.category,
                "reported_label": r.reported_label,
                "group_id": r.group_id,
                "analysis_population": r.analysis_population,
                "count": r.count,
                "denominator": r.denominator,
                "proportion": r.count / r.denominator
                if r.count is not None and r.denominator
                else None,
            }
            for r in rows
        ]
    }, [
        "Groups and categories are not pooled; total groups may overlap treatment groups.",
        "No universal enrolment target is assumed; missing denominators remain missing.",
    ]


def _ae_availability(bundle):
    rows = bundle.adverse_event_rows
    labelled = [r for r in rows if r.reported_sex_category]
    categories = {r.reported_sex_category.casefold() for r in labelled}
    reasons = []
    compatible_pairs = []
    # Validate pairs using exactly the statistical tool's preconditions, not row counts.
    female = [r for r in labelled if r.reported_sex_category.casefold() == "female"]
    male = [r for r in labelled if r.reported_sex_category.casefold() == "male"]
    for a in female:
        for b in male:
            try:
                _validate_ae_pair([a, b])
                compatible_pairs.append([a.row_id, b.row_id])
            except ValueError as exc:
                reasons.append(str(exc))
    covered = {key for pair in compatible_pairs for key in pair}
    if compatible_pairs:
        # Additional reported categories are descriptive only; they never block or join
        # the Female/Male comparison, but every Female/Male row must have a valid pair.
        state = "available" if all(r.row_id in covered for r in [*female, *male]) else "incomplete"
        if state == "incomplete":
            reasons.append("Some reported category rows lack a compatible comparison")
        if len(female) + len(male) < len(labelled):
            reasons.append("Additional reported sex categories are retained descriptively")
    elif not labelled:
        declared = bundle.availability.sex_stratified_ae
        state = declared if declared in {"not_assessed", "not_applicable"} else "missing"
        reasons.append(
            "No explicit sex-category participant comparison extracted; "
            "this does not establish that the source lacks subgroup data"
        )
    elif not {"female", "male"} <= categories:
        state = "incomplete"
        reasons.append(
            "A single or unsupported set of reported categories cannot form a comparison"
        )
    else:
        state = "incompatible"
    return {
        "status": state,
        "compatible_row_pairs": compatible_pairs,
        "reasons": list(dict.fromkeys(reasons)),
    }


def audit_subgroup_availability(bundle: TrialBundle, rows):
    ae = [
        r
        for r in bundle.adverse_event_rows
        if r.reported_sex_category
        and r.participants_affected is not None
        and r.participants_at_risk
    ]
    pk = [r for r in bundle.pk_rows if r.reported_sex_category]
    ae_state = _ae_availability(bundle)
    table = participant_table_for(bundle)
    pk_sexes = {
        _female_male(table.participants[sid]["sex"])
        for values in (table.exposures.values() if table else [])
        for sid in values
    }
    if {True, False} <= pk_sexes:
        pk_state = {
            "status": "available",
            "reasons": [
                "Participant-level PK from one visit permits within-arm Female/Male "
                "comparison of the same parameter, dose and sampling."
            ],
        }
    elif pk:
        pk_state = {
            "status": "reported_only",
            "reasons": [
                "Sex-category PK summaries are reported; population and sampling-window "
                "comparability cannot be established from PKRow v1.0 alone"
            ],
        }
    else:
        declared = bundle.availability.sex_stratified_pk
        pk_state = {
            "status": declared if declared in {"not_assessed", "not_applicable"} else "missing",
            "reasons": [
                "No explicit sex-category PK summaries extracted; source review may be needed"
            ],
        }
    missing = []
    if ae_state["status"] not in {"available", "not_applicable"}:
        missing.append("compatible sex-stratified AE participant counts")
    if pk_state["status"] not in {"available", "not_applicable"}:
        missing.append("verified compatible sex-stratified PK summaries")
    return {
        "reported_availability": bundle.availability.model_dump(mode="json"),
        "comparison_availability": {"adverse_events": ae_state, "pk": pk_state},
        "ae_rows_with_explicit_sex_and_participant_counts": len(ae),
        "pk_rows_with_explicit_sex": len(pk),
        "ae_comparison_requires_compatibility_review": ae_state["status"] != "available",
        "missing_fields": missing,
    }, [
        "Availability describes extracted inputs, not absence from original sources or analyses.",
        "Baseline sex counts cannot supply adverse-event denominators.",
    ]


def _validate_ae_pair(rows):
    if len(rows) != 2:
        raise ValueError("Select exactly two disjoint sex-category rows")
    a, b = rows
    required = ("intervention", "analysis_population", "reporting_window")
    for name in (*required, "source_term", "event_seriousness", "group_id"):
        if not getattr(a, name) or getattr(a, name) != getattr(b, name):
            raise ValueError(f"Missing or incompatible {name}; same validated arm/group required")
    if a.event_seriousness == "unspecified":
        raise ValueError("Missing event seriousness")
    if not a.reported_sex_category or not b.reported_sex_category:
        raise ValueError("Missing explicit reported sex categories")
    if a.reported_sex_category.casefold() == b.reported_sex_category.casefold():
        raise ValueError("Sex categories must be distinct and disjoint")
    if {a.reported_sex_category.casefold(), b.reported_sex_category.casefold()} != {
        "female",
        "male",
    }:
        raise ValueError(
            "Disjoint category comparison requires explicit Female and Male labels; "
            "other reported categories remain available descriptively"
        )
    for r in rows:
        if r.participants_affected is None or not r.participants_at_risk:
            raise ValueError(
                "Requires participants_affected and positive participants_at_risk; "
                "event occurrences are not participant counts"
            )
    return a, b


def compare_adverse_event_rates(bundle: TrialBundle, rows):
    a, b = _validate_ae_pair(rows)
    x, n, y, m = (
        a.participants_affected,
        a.participants_at_risk,
        b.participants_affected,
        b.participants_at_risk,
    )
    p, q = x / n, y / m
    low, high = confint_proportions_2indep(x, n, y, m, method="newcomb", compare="diff")
    test = fisher_exact([[x, n - x], [y, m - y]], alternative="two-sided")
    return {
        "categories": [a.reported_sex_category, b.reported_sex_category],
        "proportions": [p, q],
        "risk_difference": p - q,
        "risk_difference_ci95": [float(low), float(high)],
        "risk_ratio": p / q if q else None,
        "fisher_p_value": float(test.pvalue),
    }, [
        "Exploratory unadjusted comparison; multiplicity is not controlled.",
        "Newcombe difference interval combines Wilson score intervals at 95% confidence.",
        "No continuity correction; risk ratio unavailable when reference risk is zero.",
        "Sparse counts can yield low precision; non-significance does not establish safety.",
        "This within-arm comparison is not a sex-by-treatment interaction or causal effect.",
    ]


def summarise_pk_by_sex(bundle: TrialBundle, rows):
    if not rows:
        raise ValueError("Missing reported sex-stratified PK summaries")
    result = {"rows": [r.model_dump(mode="json") for r in rows], "descriptive_ratio": None}
    table = participant_table_for(bundle)
    if table is None or not table.exposures:
        return result, [
            "Reported aggregate summaries only; no patient-level inference.",
            "Population and sampling-window fields are absent from contract v1.0; "
            "a cross-category ratio cannot be verified and is withheld.",
        ]
    ratios = []
    for code, values in sorted(table.exposures.items()):
        by_arm: dict[str, dict[bool, list[float]]] = {}
        for sid, value in values.items():
            p = table.participants[sid]
            sex = _female_male(p["sex"])
            if sex is not None:
                by_arm.setdefault(p["armcd"], {True: [], False: []})[sex].append(value)
        for armcd, groups in sorted(by_arm.items()):
            if len(groups[True]) < 2 or len(groups[False]) < 2:
                ratios.append(
                    {
                        "parameter": code,
                        "group_id": armcd,
                        "status": "unavailable",
                        "reason": "Fewer than two Female or Male values in this arm",
                    }
                )
                continue
            ratios.append(
                {
                    "parameter": code,
                    "group_id": armcd,
                    "status": "completed",
                    "unit": table.exposure_units[code],
                    **_log_ratio_ci(groups[True], groups[False]),
                }
            )
    result["participant_level_ratios"] = ratios
    return result, [
        "Ratios use participant-level values for the same parameter, arm/dose and visit; "
        "log-normal exposure assumed (Welch 95% CI on log values).",
        "Exploratory and unadjusted for body size; several parameters and arms are "
        "compared without multiplicity adjustment.",
        "A higher exposure ratio is not by itself evidence of harm or of a dose change need.",
    ]


def _fit_logit(y, columns, names):
    """Logistic regression with Wald 95% CIs; separation or non-convergence -> None."""
    import statsmodels.api as sm
    from statsmodels.tools.sm_exceptions import ConvergenceWarning, PerfectSeparationWarning

    x = sm.add_constant(np.column_stack(columns).astype(float), has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("error", PerfectSeparationWarning)
        warnings.simplefilter("error", ConvergenceWarning)
        warnings.simplefilter("ignore", RuntimeWarning)
        try:
            fit = sm.Logit(np.asarray(y, dtype=float), x).fit(disp=0, maxiter=200)
        except (
            PerfectSeparationWarning,
            ConvergenceWarning,
            np.linalg.LinAlgError,
            ValueError,
        ) as exc:
            return {
                "status": "unavailable",
                "reason": f"Model not estimable ({type(exc).__name__})",
            }
    ci = fit.conf_int(0.05)
    terms = {}
    for i, name in enumerate(names, start=1):
        if not np.isfinite(ci[i]).all() or abs(fit.params[i]) > 20:
            return {"status": "unavailable", "reason": "Unstable estimate (likely separation)"}
        terms[name] = {
            "odds_ratio": float(math.exp(fit.params[i])),
            "or_ci95": [float(math.exp(ci[i][0])), float(math.exp(ci[i][1]))],
            "wald_p_value": float(fit.pvalues[i]),
        }
    return {"status": "completed", "n": int(len(y)), "events": int(sum(y)), "terms": terms}


def exposure_response(bundle: TrialBundle, params: ExposureSelection):
    table = participant_table_for(bundle)
    if table is None:
        raise ValueError(
            "Exposure-response requires participant-level data loaded in this server "
            "session; it is never estimated from aggregate summaries"
        )
    known_terms = {r.source_term for r in bundle.adverse_event_rows}
    if params.term not in known_terms:
        raise ValueError("Unknown AE term; use a reported term from this dataset")
    available = [code for code in EXPOSURE_PARAMETERS if table.exposures.get(code)]
    code = params.exposure_parameter or (available[0] if available else None)
    if code is None or code not in table.exposures:
        raise ValueError("Missing participant-level exposure parameter")
    values = table.exposures[code]
    affected = table.teae.get(params.term, set())
    x, y, female = [], [], []
    missing_exposure = other_sex = 0
    for sid, p in table.participants.items():
        if p["placebo"]:
            exposure = 0.0
        elif sid in values:
            exposure = values[sid]
        else:
            missing_exposure += 1
            continue
        x.append(exposure)
        y.append(int(sid in affected))
        female.append(_female_male(p["sex"]))
    events = sum(y)
    if events == 0 or events == len(y):
        raise ValueError("Exposure-response needs both affected and unaffected participants")
    dosed = [v for v in x if v > 0]
    if not dosed:
        raise ValueError("No dosed participants with exposure values")
    scale = pystats.median(dosed)
    scaled = [v / scale for v in x]
    keep = [i for i, f in enumerate(female) if f is not None]
    other_sex = len(female) - len(keep)
    exposure_model = _fit_logit(y, [scaled], ["exposure"])
    y_s = [y[i] for i in keep]
    sex_col = [int(female[i]) for i in keep]
    unadjusted = _fit_logit(y_s, [sex_col], ["female"])
    adjusted = _fit_logit(y_s, [[scaled[i] for i in keep], sex_col], ["exposure", "female"])
    exposure_by_sex = {}
    if keep:
        dosed_f = [x[i] for i in keep if female[i] and x[i] > 0]
        dosed_m = [x[i] for i in keep if not female[i] and x[i] > 0]
        exposure_by_sex = {
            "female_median": pystats.median(dosed_f) if dosed_f else None,
            "male_median": pystats.median(dosed_m) if dosed_m else None,
            "note": "Pooled across active doses; see summarise_pk_by_sex for within-arm ratios.",
        }
    limitations = [
        "Exploratory participant-level logistic regression (Wald 95% CIs); not a causal "
        "estimate and not adjusted for body size or other covariates.",
        f"Exposure scaled per median dosed {code} ({scale:.4g} {table.exposure_units[code]}); "
        "placebo participants enter with zero exposure.",
        "Outcome: participant with at least one treatment-emergent event of this term.",
        "Several terms may be analysed; no multiplicity adjustment.",
    ]
    if min(events, len(y) - events) < 10 * 2:
        limitations.append(
            "Few events for the number of model terms (fewer than about 10 per term, a "
            "common rule of thumb): estimates are imprecise and may be unstable."
        )
    if missing_exposure:
        limitations.append(f"{missing_exposure} dosed participants without {code} excluded.")
    if other_sex:
        limitations.append(
            f"{other_sex} participants with other reported sex categories are excluded from "
            "sex terms only."
        )
    return {
        "term": params.term,
        "exposure_parameter": code,
        "exposure_unit": table.exposure_units[code],
        "exposure_scale": scale,
        "n": len(y),
        "events": events,
        "exposure_model": exposure_model,
        "sex_unadjusted_model": unadjusted,
        "sex_exposure_adjusted_model": adjusted,
        "exposure_by_sex": exposure_by_sex,
    }, limitations


def summarise_qtc_by_sex(bundle: TrialBundle, params: NoParameters):
    table = participant_table_for(bundle)
    if table is None or not table.ecg:
        raise ValueError("Requires participant-level QTcF ECG data with a baseline value")
    groups: dict[tuple[str, bool], list[dict]] = {}
    for sid, ecg in table.ecg.items():
        p = table.participants[sid]
        sex = _female_male(p["sex"])
        if sex is not None:
            groups.setdefault((p["armcd"], sex), []).append({"sid": sid, **ecg})

    def describe(members):
        changes = [m["max_change"] for m in members]
        n = len(changes)
        mean = sum(changes) / n
        ci = None
        if n >= 2:
            half = stats.t.ppf(0.975, n - 1) * pystats.stdev(changes) / math.sqrt(n)
            ci = [mean - half, mean + half]
        return {
            "n": n,
            "mean_baseline_ms": sum(m["baseline"] for m in members) / n,
            "mean_max_change_ms": mean,
            "mean_max_change_ci95": ci,
            "max_value_over_ms": {
                str(c): sum(m["max_post"] > c for m in members) for c in QTC_ABSOLUTE_CATEGORIES_MS
            },
            "max_change_over_ms": {
                str(c): sum(m["max_change"] > c for m in members) for c in QTC_CHANGE_CATEGORIES_MS
            },
        }

    arms = sorted({armcd for armcd, _ in groups})
    summaries, comparisons = [], []
    for armcd in arms:
        f, m = groups.get((armcd, True), []), groups.get((armcd, False), [])
        for sex, members in (("Female", f), ("Male", m)):
            if members:
                summaries.append({"group_id": armcd, "sex": sex, **describe(members)})
        if len(f) >= 2 and len(m) >= 2:
            test = stats.ttest_ind(
                [x["max_change"] for x in f], [x["max_change"] for x in m], equal_var=False
            )
            ci = test.confidence_interval(0.95)
            outliers = {}
            for label, flag in (
                ("max_value_over_500", lambda x: x["max_post"] > 500),
                ("max_change_over_60", lambda x: x["max_change"] > 60),
            ):
                a, b = sum(map(flag, f)), sum(map(flag, m))
                low, high = confint_proportions_2indep(
                    a, len(f), b, len(m), method="newcomb", compare="diff"
                )
                outliers[label] = {
                    "female": [a, len(f)],
                    "male": [b, len(m)],
                    "risk_difference_ci95": [float(low), float(high)],
                    "fisher_p_value": float(
                        fisher_exact([[a, len(f) - a], [b, len(m) - b]]).pvalue
                    ),
                }
            comparisons.append(
                {
                    "group_id": armcd,
                    "mean_max_change_difference_ms": float(
                        np.mean([x["max_change"] for x in f])
                        - np.mean([x["max_change"] for x in m])
                    ),
                    "difference_ci95": [float(ci.low), float(ci.high)],
                    "welch_p_value": float(test.pvalue),
                    "outliers": outliers,
                }
            )
    concentration_qtc = None
    cmax = table.exposures.get("CMAX")
    if cmax:
        import statsmodels.api as sm

        rows = []
        for sid, ecg in table.ecg.items():
            p = table.participants[sid]
            sex = _female_male(p["sex"])
            conc = 0.0 if p["placebo"] else cmax.get(sid)
            if sex is not None and conc is not None:
                rows.append((ecg["max_change"], conc, int(sex)))
        if len(rows) >= 8:
            yv = np.array([r[0] for r in rows])
            c = np.array([r[1] for r in rows])
            fem = np.array([r[2] for r in rows])
            fit = sm.OLS(yv, sm.add_constant(np.column_stack([c, fem, c * fem]))).fit()
            ci = fit.conf_int(0.05)
            concentration_qtc = {
                "n": len(rows),
                "slope_ms_per_unit_male": float(fit.params[1]),
                "slope_ci95_male": [float(ci[1][0]), float(ci[1][1])],
                "female_minus_male_slope": float(fit.params[3]),
                "slope_difference_ci95": [float(ci[3][0]), float(ci[3][1])],
                "female_offset_ms_at_zero_concentration": float(fit.params[2]),
                "offset_ci95": [float(ci[2][0]), float(ci[2][1])],
                "unit": f"ms per {table.exposure_units['CMAX']}",
            }
    return {
        "summaries": summaries,
        "female_male_comparisons": comparisons,
        "concentration_qtc": concentration_qtc,
    }, [
        "QTcF change uses each participant's maximum post-baseline value; not "
        "placebo-corrected or time-matched.",
        "Categories follow the ICH E14 categorical analysis (QTcF > 450/480/500 ms; "
        "increase > 30/60 ms); they are outlier flags, not clinical decisions.",
        "Concentration-QTc uses Cmax and maximum change (exploratory linear model with a "
        "sex interaction); not a validated exposure-response analysis.",
        "Sparse outlier counts give imprecise comparisons; no multiplicity adjustment.",
    ]


async def execute_analysis(request: AnalysisRequest, context: ToolContext) -> AnalysisResult:
    """Do not append to additional_analyses: the safety dispatcher owns that list."""
    context.budget.remaining_seconds()
    result = AnalysisResult(
        analysis_id=f"analysis-{uuid4().hex}",
        request_id=request.request_id,
        status="invalid",
        method=request.tool_name,
        parameters=request.parameters,
        source_locators=[],
        is_synthetic=False,
    )
    bundle = context.datasets.get(request.dataset_ref)
    if bundle is None:
        result.limitations = ["Unknown server-side dataset_ref; paths are never resolved"]
        return result
    try:
        bundle = TrialBundle.model_validate(bundle.model_dump())
        validate_screening(ScreeningOutput(trial_bundle=bundle))
        selection = PARAMETER_MODELS.get(request.tool_name, Selection).model_validate(
            request.parameters
        )
    except (ValidationError, ValueError) as exc:
        result.limitations = [f"Invalid dataset or parameters: {type(exc).__name__}"]
        return result
    result.is_synthetic = bundle.is_synthetic
    if request.tool_name in {"exposure_response", "summarise_qtc_by_sex"}:
        function = (
            exposure_response
            if request.tool_name == "exposure_response"
            else (summarise_qtc_by_sex)
        )
        table = participant_table_for(bundle)
        domains = (
            ("dm", "ae", "pp") if request.tool_name == "exposure_response" else ("dm", "pp", "eg")
        )
        result.source_locators = [
            SourceLocator(source_id=table.source_ids[d], location="participant-level values")
            for d in domains
            if table is not None and d in table.source_ids
        ] or [SourceLocator(source_id=s.source_id, location="$") for s in bundle.sources]
        result.method = {
            "exposure_response": "Participant-level logistic regression of AE on exposure "
            "and sex (Wald 95% CI)",
            "summarise_qtc_by_sex": "QTcF change by sex: Welch t, Newcombe/Fisher for ICH E14 "
            "categories, linear concentration-QTc with sex interaction",
        }[request.tool_name]
        try:
            result.results, result.limitations = function(bundle, selection)
            result.status = "completed"
            if table is not None:
                result.sample_sizes = {"participants": len(table.participants)}
        except ValueError as exc:
            result.status = "unavailable"
            result.limitations = [str(exc)]
            result.results = {"missing_requirements": [str(exc)]}
        return AnalysisResult.model_validate(result.model_dump())
    collections = {
        "summarise_representation": bundle.demographic_rows,
        "audit_subgroup_availability": [],
        "compare_adverse_event_rates": bundle.adverse_event_rows,
        "summarise_pk_by_sex": bundle.pk_rows,
    }
    if request.tool_name not in collections:
        result.limitations = ["Unsupported analytical tool"]
        return result
    candidates = collections[request.tool_name]
    ids = selection.row_ids
    if len(ids) != len(set(ids)) or set(ids) - {r.row_id for r in candidates}:
        result.limitations = ["Duplicate or unknown row IDs"]
        return result
    rows = [next(r for r in candidates if r.row_id == key) for key in ids] if ids else candidates
    if request.tool_name == "summarise_pk_by_sex":
        rows = [r for r in rows if r.reported_sex_category]
    result.source_locators = [r.source_locator for r in rows]
    if not result.source_locators:
        result.source_locators = [
            SourceLocator(source_id=s.source_id, location="$") for s in bundle.sources
        ]
    tools = {
        "summarise_representation": summarise_representation,
        "audit_subgroup_availability": audit_subgroup_availability,
        "compare_adverse_event_rates": compare_adverse_event_rates,
        "summarise_pk_by_sex": summarise_pk_by_sex,
    }
    try:
        result.results, result.limitations = tools[request.tool_name](bundle, rows)
        result.status = "completed"
        if request.tool_name == "compare_adverse_event_rates":
            result.sample_sizes = {r.row_id: r.participants_at_risk for r in rows}
            result.method = "Newcombe/Wilson 95% risk-difference interval; two-sided Fisher exact"
    except ValueError as exc:
        result.status = "unavailable"
        result.limitations = [str(exc)]
        result.results = {"missing_requirements": [str(exc)]}
    return AnalysisResult.model_validate(result.model_dump())
