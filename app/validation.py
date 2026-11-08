"""Cross-record provenance checks; these reject missing IDs, not scientific falsehoods.

A source ID resolving successfully does not prove its claim is accurate. Agents
must also inspect retrieved content and retain excerpts/locations and limitations.
"""

from app.contracts import (
    InvestigationReport,
    PlannerInput,
    PlannerReport,
    RunResult,
    ScreeningOutput,
)


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
    if result.planner_report is not None:
        if result.planner_input is None:
            raise ValueError("Planner report requires its validated input snapshot")
        validate_planner_report(result.planner_report, result.planner_input)
        if result.status == "completed" and result.planner_report.status != "completed":
            raise ValueError("Incomplete planning prevents completed run status")


def planner_input_limitations(planner: PlannerInput) -> list[str]:
    """Explicit incompleteness cannot be overridden by model completion status."""
    limits = list(planner.screening.trial_bundle.limitations)
    if planner.investigation.status != "completed":
        limits.append("Upstream investigation is incomplete.")
    assessed = {x.finding_id for x in planner.investigation.assessed_findings}
    if any(x.finding_id not in assessed for x in planner.screening.findings):
        limits.append("Some screened findings have not been assessed.")
    if any(x.needs_review for x in planner.screening.symptom_mappings):
        limits.append("Symptom interpretation requires human review.")
    if any(x.status != "completed" for x in planner.evidence_reports):
        limits.append("Some upstream evidence research is incomplete.")
    if not any(r.evidence_items for r in planner.evidence_reports):
        limits.append(
            "No accepted external evidence items are available; no literature "
            "conclusion is established."
        )
    if any(a.status != "completed" for a in planner.screening.analyses):
        limits.append("Some upstream analyses are unavailable or invalid.")
    limits.extend(planner.investigation.limitations)
    limits.extend(lim for r in planner.evidence_reports for lim in r.limitations)
    return list(dict.fromkeys(limits))


def validate_planner_report(report: PlannerReport, planner: PlannerInput) -> None:
    """Check reference edges and honesty, not semantic support or clinical validity.

    run_planner additionally restricts generated text to application-authored actions.
    Call this after schema validation and before publishing independent reports.
    """
    validate_planner_input(planner)
    bundle = planner.screening.trial_bundle
    if report.trial_id != bundle.trial_id:
        raise ValueError("Planner trial does not match input")
    evidence = {x.evidence_id: x for r in planner.evidence_reports for x in r.evidence_items}
    sources = {x.source_id: x for x in bundle.sources}
    sources.update({x.source_id: x for r in planner.evidence_reports for x in r.sources})
    synthetic = bundle.is_synthetic or any(x.is_synthetic for x in sources.values())
    if report.is_synthetic != synthetic:
        raise ValueError("Planner synthetic label must match inputs")
    required_limits = planner_input_limitations(planner)
    if not set(required_limits) <= set(report.input_limitations):
        raise ValueError("Planner must preserve input limitations")
    if report.status == "completed" and required_limits:
        raise ValueError("Incomplete or limited upstream inputs prevent completed planning")
    if report.status == "unavailable" and report.recommendations:
        raise ValueError("Unavailable planning cannot contain selected recommendations")
    _ids(report.recommendations, "recommendation_id")
    findings = {x.finding_id: x for x in planner.screening.findings}
    hypotheses = {x.hypothesis_id: x for x in planner.investigation.hypotheses}
    analyses = {x.analysis_id: x for x in planner.screening.analyses}
    for rec in report.recommendations:
        _require(rec.finding_ids, set(findings), "planner finding ID")
        _require(rec.analysis_ids, set(analyses), "planner analysis ID")
        _require(rec.evidence_ids, set(evidence), "planner evidence ID")
        _require(rec.source_ids, set(sources), "planner source ID")
        _require(rec.hypothesis_ids, set(hypotheses), "planner hypothesis ID")
        related = set(rec.finding_ids)
        linked_analyses = {aid for fid in related for aid in findings[fid].analysis_ids}
        linked_analyses.update(
            aid
            for a in planner.investigation.assessed_findings
            if a.finding_id in related
            for aid in a.analysis_ids
        )
        if not set(rec.analysis_ids) <= linked_analyses:
            raise ValueError("Planner analysis is unrelated to its findings")
        linked_sources = {sid for fid in related for sid in findings[fid].source_ids}
        linked_sources.update(
            loc.source_id for aid in rec.analysis_ids for loc in analyses[aid].source_locators
        )
        scoped_evidence = set()
        for hid in rec.hypothesis_ids:
            hypothesis = hypotheses[hid]
            if not related.intersection(hypothesis.finding_ids):
                raise ValueError("Planner hypothesis is unrelated to its findings")
            for eid in hypothesis.supporting_evidence_ids + hypothesis.contradicting_evidence_ids:
                if not set(hypothesis.finding_ids).intersection(evidence[eid].finding_ids):
                    raise ValueError("Hypothesis evidence is unrelated to its findings")
                scoped_evidence.add(eid)
        for eid in rec.evidence_ids:
            if not related.intersection(evidence[eid].finding_ids) and eid not in scoped_evidence:
                raise ValueError("Planner evidence is unrelated to its findings")
            linked_sources.add(evidence[eid].source_id)
        if not set(rec.source_ids) <= linked_sources:
            raise ValueError("Planner source lacks a finding, analysis or accepted evidence link")
        required_sources = {evidence[eid].source_id for eid in rec.evidence_ids}
        if not required_sources <= set(rec.source_ids):
            raise ValueError("Planner must retain cited evidence sources")
        contradictions = {
            eid
            for eid, e in evidence.items()
            if e.relation == "contradicts" and related.intersection(e.finding_ids)
        }
        if not contradictions <= set(rec.evidence_ids):
            raise ValueError("Planner must retain relevant contradictory evidence")
        relevant_hypotheses = {
            hid
            for hid, hypothesis in hypotheses.items()
            if related.intersection(hypothesis.finding_ids)
        }
        if not relevant_hypotheses <= set(rec.hypothesis_ids):
            raise ValueError("Planner must retain relevant hypotheses")
        for hid in rec.hypothesis_ids:
            hypothesis = hypotheses[hid]
            if not set(
                hypothesis.supporting_evidence_ids + hypothesis.contradicting_evidence_ids
            ) <= set(rec.evidence_ids):
                raise ValueError("Planner must retain hypothesis evidence")
        if rec.evidence_basis == "hypothesis" and not rec.hypothesis_ids:
            raise ValueError("Hypothesis basis requires a linked hypothesis")
        if rec.evidence_basis == "evidence_gap" and not any(
            findings[f].finding_type == "evidence_gap" for f in related
        ):
            raise ValueError("Evidence-gap basis requires a gap finding")

    # Planning completion requires an explicit disposition, not a claim that all
    # scientific questions are resolved. Partial legacy snapshots may omit these.
    _ids(report.finding_dispositions, "finding_id")
    disposed = {d.finding_id for d in report.finding_dispositions}
    _require(list(disposed), set(findings), "disposition finding ID")
    if report.status == "completed" and not set(findings) <= disposed:
        raise ValueError(
            "Completed planning must address every finding with an explicit disposition"
        )
    recommendations = {r.recommendation_id: r for r in report.recommendations}
    for disposition in report.finding_dispositions:
        fid = disposition.finding_id
        _require(
            disposition.recommendation_ids, set(recommendations), "disposition recommendation ID"
        )
        _require(disposition.analysis_ids, set(analyses), "disposition analysis ID")
        _require(disposition.evidence_ids, set(evidence), "disposition evidence ID")
        allowed_analyses = set(findings[fid].analysis_ids)
        allowed_analyses.update(
            aid
            for a in planner.investigation.assessed_findings
            if a.finding_id == fid
            for aid in a.analysis_ids
        )
        if not set(disposition.analysis_ids) <= allowed_analyses:
            raise ValueError("Disposition analysis is unrelated to its finding")
        if any(fid not in evidence[eid].finding_ids for eid in disposition.evidence_ids):
            raise ValueError("Disposition evidence is unrelated to its finding")
        if any(
            fid not in recommendations[rid].finding_ids for rid in disposition.recommendation_ids
        ):
            raise ValueError("Disposition recommendation is unrelated to its finding")
        if disposition.status == "requires_further_investigation":
            if not disposition.recommendation_ids:
                raise ValueError(
                    "Further investigation disposition requires a valid follow-up action"
                )
        elif disposition.recommendation_ids:
            raise ValueError("Follow-up actions require a further-investigation disposition")
        if disposition.status == "resolved":
            if not disposition.analysis_ids and not disposition.evidence_ids:
                raise ValueError(
                    "Resolved planning disposition requires source-linked review support"
                )
            if any(analyses[aid].status != "completed" for aid in disposition.analysis_ids):
                raise ValueError("Resolved disposition cannot rely on unavailable analysis")
        for rec in report.recommendations:
            if (
                fid in rec.finding_ids
                and rec.recommendation_id not in disposition.recommendation_ids
            ):
                raise ValueError("Disposition must retain its selected follow-up actions")
