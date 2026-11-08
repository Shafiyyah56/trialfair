"""Independent synthetic scientific examples; no observed clinical data."""

import asyncio

import pytest
from scipy.stats import fisher_exact
from statsmodels.stats.proportion import proportion_confint

from app.contracts import AdverseEventRow, AnalysisRequest, DemographicRow, PKRow
from app.services.statistics import execute_analysis


def counts(bundle, x=20, y=10, n=100, m=100):
    bundle = bundle.model_copy(deep=True)
    sid = bundle.sources[0].source_id
    bundle.adverse_event_rows = [
        AdverseEventRow(
            row_id=f"ae-{i}",
            source_term="Dizziness",
            group_id="arm-A",
            intervention="Synthetic X 1 mg",
            reported_sex_category=sex,
            analysis_population="Safety population",
            participants_affected=a,
            participants_at_risk=b,
            event_seriousness="non_serious",
            reporting_window="Day 1-7",
            source_locator={"source_id": sid, "location": f"synthetic.ae[{i}]"},
            is_synthetic=True,
        )
        for i, (sex, a, b) in enumerate((("Female", x, n), ("Male", y, m)))
    ]
    return bundle


def run_tool(context, bundle, tool="compare_adverse_event_rates", parameters=None):
    context.datasets["validated"] = bundle
    return asyncio.run(
        execute_analysis(
            AnalysisRequest(
                request_id="request",
                requested_by="safety",
                tool_name=tool,
                dataset_ref="validated",
                rationale="Synthetic test",
                parameters=parameters or {},
            ),
            context,
        )
    )


def test_independent_risk_difference(context_factory, screening):
    ctx, _ = context_factory()
    result = run_tool(ctx, counts(screening.trial_bundle))
    assert result.status == "completed"
    assert result.results["proportions"] == [0.2, 0.1]
    assert result.results["risk_difference"] == pytest.approx(0.1)
    assert result.results["risk_ratio"] == 2
    # Newcombe formula checked independently from Wilson single-proportion intervals.
    l1, u1 = proportion_confint(20, 100, method="wilson")
    l2, u2 = proportion_confint(10, 100, method="wilson")
    expected = [
        0.1 - ((0.2 - l1) ** 2 + (u2 - 0.1) ** 2) ** 0.5,
        0.1 + ((u1 - 0.2) ** 2 + (0.1 - l2) ** 2) ** 0.5,
    ]
    assert result.results["risk_difference_ci95"] == pytest.approx(expected)
    assert result.results["fisher_p_value"] == pytest.approx(
        fisher_exact([[20, 80], [10, 90]]).pvalue
    )
    assert result.request_id == "request" and result.is_synthetic
    assert ctx.additional_analyses == []


@pytest.mark.parametrize(("x", "y", "ratio"), [(0, 0, None), (1, 0, None), (0, 1, 0)])
def test_sparse_zero_events(context_factory, screening, x, y, ratio):
    ctx, _ = context_factory()
    result = run_tool(ctx, counts(screening.trial_bundle, x, y, 5, 5))
    assert result.status == "completed"
    assert result.results["risk_ratio"] == ratio
    assert 0 <= result.results["fisher_p_value"] <= 1
    assert any("Sparse" in x for x in result.limitations)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("participants_affected", None),
        ("participants_at_risk", None),
        ("reporting_window", "Day 2"),
        ("intervention", "Other dose"),
        ("analysis_population", "Other population"),
        ("group_id", "other-arm"),
        ("reported_sex_category", None),
        ("source_term", "Other endpoint"),
    ],
)
def test_invalid_comparison_preconditions(context_factory, screening, field, value):
    ctx, _ = context_factory()
    bundle = counts(screening.trial_bundle)
    setattr(bundle.adverse_event_rows[1], field, value)
    bundle.adverse_event_rows[1].event_occurrences = 15
    result = run_tool(ctx, bundle)
    assert result.status == "unavailable"
    assert "risk_difference" not in result.results


def test_missing_data_and_no_paths(context_factory, screening):
    ctx, _ = context_factory()
    result = asyncio.run(
        execute_analysis(
            AnalysisRequest(
                request_id="bad",
                requested_by="safety",
                tool_name="summarise_representation",
                dataset_ref="/etc/passwd",
                rationale="Test",
            ),
            ctx,
        )
    )
    assert result.status == "invalid"
    result = run_tool(ctx, screening.trial_bundle, parameters={"code": "print(1)"})
    assert result.status == "invalid"
    result = run_tool(ctx, counts(screening.trial_bundle), parameters={"row_ids": ["ae-0", "ae-0"]})
    assert result.status == "invalid"


def test_representation_preserves_categories(context_factory, screening):
    ctx, _ = context_factory()
    bundle = screening.trial_bundle.model_copy(deep=True)
    bundle.demographic_rows = [
        DemographicRow(
            row_id="unknown",
            category="Sex as reported",
            reported_label="Not reported",
            group_id="A",
            count=None,
            denominator=100,
            source_locator={"source_id": bundle.sources[0].source_id, "location": "synthetic.sex"},
            is_synthetic=True,
        )
    ]
    result = run_tool(ctx, bundle, "summarise_representation")
    assert result.results["rows"][0]["reported_label"] == "Not reported"
    assert result.results["rows"][0]["proportion"] is None


def test_pk_insufficient_context_withholds_ratio(context_factory, screening):
    ctx, _ = context_factory()
    bundle = screening.trial_bundle.model_copy(deep=True)
    bundle.pk_rows = [
        PKRow(
            row_id=f"pk-{i}",
            parameter="Cmax",
            value=value,
            unit="ng/mL",
            summary_statistic="MEAN",
            group_id="A",
            reported_sex_category=sex,
            dose="1 mg",
            formulation="tablet",
            sample_size=10,
            source_locator={
                "source_id": bundle.sources[0].source_id,
                "location": f"synthetic.pk[{i}]",
            },
            is_synthetic=True,
        )
        for i, (value, sex) in enumerate(((10, "Female"), (5, "Male")))
    ]
    result = run_tool(ctx, bundle, "summarise_pk_by_sex")
    assert result.results["descriptive_ratio"] is None
    assert len(result.results["rows"]) == 2
