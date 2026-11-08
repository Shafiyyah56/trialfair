"""Allowlisted deterministic exploratory analyses over validated server datasets."""

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from scipy.stats import fisher_exact
from statsmodels.stats.proportion import confint_proportions_2indep

from app.context import ToolContext
from app.contracts import AnalysisRequest, AnalysisResult, ScreeningOutput, TrialBundle
from app.validation import validate_screening


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row_ids: list[str] = Field(default_factory=list)


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
        state = "available" if all(r.row_id in covered for r in labelled) else "incomplete"
        if state == "incomplete":
            reasons.append("Some reported category rows lack a compatible comparison")
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
    if pk:
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
    result = {"rows": [r.model_dump(mode="json") for r in rows], "descriptive_ratio": None}
    limitations = [
        "Reported aggregate summaries only; no patient-level inference.",
        "Population and sampling-window fields are absent from contract v1.0; "
        "a cross-category ratio cannot be verified and is withheld.",
    ]
    if not rows:
        raise ValueError("Missing reported sex-stratified PK summaries")
    return result, limitations


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
        selection = Selection.model_validate(request.parameters)
    except (ValidationError, ValueError) as exc:
        result.limitations = [f"Invalid dataset or parameters: {type(exc).__name__}"]
        return result
    result.is_synthetic = bundle.is_synthetic
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
        from app.contracts import SourceLocator

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
