"""Cross-record provenance checks; these reject missing IDs, not scientific falsehoods.

A source ID resolving successfully does not prove its claim is accurate. Agents
must also inspect retrieved content and retain excerpts/locations and limitations.
"""

from app.contracts import InvestigationReport, PlannerInput, RunResult, ScreeningOutput


def _ids(records: list, attribute: str) -> set[str]:
    values = [getattr(record, attribute) for record in records]
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate {attribute}")
    return set(values)


def _require(values: list[str], known: set[str], label: str) -> None:
    missing = set(values) - known
    if missing:
        raise ValueError(f"Unknown {label}: {sorted(missing)}")


def validate_screening(screening: ScreeningOutput) -> None:
    """Check local IDs, provenance links and propagation of synthetic labels."""
    bundle = screening.trial_bundle
    sources = _ids(bundle.sources, "source_id")
    source_records = {source.source_id: source for source in bundle.sources}
    analyses = _ids(screening.analyses, "analysis_id")
    _ids(screening.findings, "finding_id")
    _ids(screening.symptom_mappings, "mapping_id")
    rows = [*bundle.demographic_rows, *bundle.adverse_event_rows, *bundle.pk_rows]
    _ids(rows, "row_id")
    _ids(bundle.narrative_entries, "entry_id")

    def check_locator(locator) -> None:
        _require([locator.source_id], sources, "source ID")

    for row in rows:
        check_locator(row.source_locator)
        if source_records[row.source_locator.source_id].is_synthetic and not row.is_synthetic:
            raise ValueError("Synthetic source rows must remain labelled")
    for narrative in bundle.narrative_entries:
        check_locator(narrative.locator)
    for mapping in screening.symptom_mappings:
        check_locator(mapping.source_locator)
    for analysis in screening.analyses:
        for locator in analysis.source_locators:
            check_locator(locator)
        if any(source_records[x.source_id].is_synthetic for x in analysis.source_locators):
            if not analysis.is_synthetic:
                raise ValueError("Analyses of synthetic sources must remain labelled")
    synthetic_analyses = {x.analysis_id for x in screening.analyses if x.is_synthetic}
    for finding in screening.findings:
        _require(finding.analysis_ids, analyses, "analysis ID")
        _require(finding.source_ids, sources, "source ID")
        if set(finding.analysis_ids) & synthetic_analyses or any(
            source_records[x].is_synthetic for x in finding.source_ids
        ):
            if not finding.is_synthetic:
                raise ValueError("Synthetic findings must remain labelled")
    if any(x.is_synthetic for x in [*bundle.sources, *rows, *screening.analyses]):
        if not bundle.is_synthetic:
            raise ValueError("Bundle containing synthetic data must remain labelled")


def validate_planner_input(planner: PlannerInput) -> None:
    """Validate references across all three agents before the future planner runs."""
    screening = planner.screening
    validate_screening(screening)
    trial_id = screening.trial_bundle.trial_id
    if planner.investigation.trial_id != trial_id:
        raise ValueError("Investigation trial does not match screening")
    findings = {x.finding_id for x in screening.findings}
    analyses = {x.analysis_id for x in screening.analyses}
    source_records = {x.source_id: x for x in screening.trial_bundle.sources}
    _ids(planner.evidence_reports, "request_id")
    evidence_items = [item for report in planner.evidence_reports for item in report.evidence_items]
    evidence = _ids(evidence_items, "evidence_id")
    for report in planner.evidence_reports:
        _ids(report.sources, "source_id")
        for source in report.sources:
            existing = source_records.get(source.source_id)
            if existing is not None and existing != source:
                raise ValueError("Conflicting records for a source ID")
            source_records[source.source_id] = source
    sources = set(source_records)
    for report in planner.evidence_reports:
        for search in report.searches:
            _require(search.result_source_ids, sources, "search source ID")
        for item in report.evidence_items:
            _require([item.source_id, item.source_locator.source_id], sources, "evidence source ID")
            if item.source_id != item.source_locator.source_id:
                raise ValueError("Evidence source and locator disagree")
            _require(item.finding_ids, findings, "evidence finding ID")
        for request in report.suggested_analysis_requests:
            _require(request.related_finding_ids, findings, "requested finding ID")
    investigation = planner.investigation
    _require(investigation.completed_analysis_ids, analyses, "analysis ID")
    _require(investigation.evidence_ids, evidence, "evidence ID")
    _ids(investigation.hypotheses, "hypothesis_id")
    _ids(investigation.assessed_findings, "finding_id")
    for assessment in investigation.assessed_findings:
        _require([assessment.finding_id], findings, "assessed finding ID")
        _require(assessment.analysis_ids, analyses, "assessment analysis ID")
        _require(assessment.evidence_ids, evidence, "assessment evidence ID")
    for hypothesis in investigation.hypotheses:
        _require(hypothesis.finding_ids, findings, "hypothesis finding ID")
        _require(hypothesis.supporting_evidence_ids, evidence, "hypothesis evidence ID")
        _require(hypothesis.contradicting_evidence_ids, evidence, "hypothesis evidence ID")


def validate_run(result: RunResult) -> None:
    """Validate partial outputs too; do not require an implemented fourth agent."""
    if result.status == "completed" and (result.screening is None or result.investigation is None):
        raise ValueError("Completed runs require screening and investigation")
    _ids(result.events, "event_id")
    for event in result.events:
        if event.run_id != result.run_id:
            raise ValueError("Event belongs to another run")
    if result.screening is not None:
        validate_screening(result.screening)
    if result.screening is None and (result.investigation or result.evidence_reports):
        raise ValueError("Investigation and evidence require screening")
    if result.screening is not None:
        investigation = result.investigation or InvestigationReport(
            trial_id=result.screening.trial_bundle.trial_id, status="unavailable"
        )
        planner = PlannerInput(
            screening=result.screening,
            investigation=investigation,
            evidence_reports=result.evidence_reports,
        )
        validate_planner_input(planner)
    if result.planner_input is not None:
        validate_planner_input(result.planner_input)
        if (
            result.planner_input.screening != result.screening
            or result.planner_input.investigation != result.investigation
            or result.planner_input.evidence_reports != result.evidence_reports
        ):
            raise ValueError("PlannerInput must match current run outputs")
