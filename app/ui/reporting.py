"""Read-only presentation/export of a validated run; no new scientific conclusions."""

from collections import Counter
from html import escape

from app.validation import validate_run


def unique(values):
    return list(dict.fromkeys(value for value in values if value))


def source_records(result):
    records = (
        {s.source_id: s for s in result.screening.trial_bundle.sources} if result.screening else {}
    )
    for report in result.evidence_reports:
        records.update({s.source_id: s for s in report.sources})
    return records


def report_flags(result):
    limitations = list(result.screening.trial_bundle.limitations) if result.screening else []
    limitations += [line for report in result.evidence_reports for line in report.limitations]
    limitations += result.investigation.limitations if result.investigation else []
    limitations += result.planner_report.limitations if result.planner_report else []
    return {
        "synthetic": bool(result.screening and result.screening.trial_bundle.is_synthetic),
        "curated": any("Curated demonstration:" in line for line in limitations),
        "fallback": any("rules-based" in line.lower() for line in limitations),
    }


def report_summary(result):
    findings = result.screening.findings if result.screening else []
    counts = Counter(f.finding_type for f in findings)
    evidence = sum(len(report.evidence_items) for report in result.evidence_reports)
    actions = len(result.planner_report.recommendations) if result.planner_report else 0
    return (
        f"The review identified {counts['potential_signal']} potential safety signals, "
        f"{counts['evidence_gap']} evidence gaps and "
        f"{counts['data_quality']} data-quality findings. "
        f"It includes {evidence} cited evidence items and {actions} proposed follow-up actions. "
        "These are research findings and proposals for human review; they do not establish "
        "causality, clinical safety or approval to progress a trial."
    )


def shared_action_limits(plan):
    counts = Counter(line for rec in plan.recommendations for line in rec.limitations)
    return [line for line, count in counts.items() if count > 1]


def _outline(result):
    validate_run(result)
    bundle = result.screening.trial_bundle if result.screening else None
    plan = result.planner_report
    flags = report_flags(result)
    finding_labels = (
        {f.finding_id: f"F{i}" for i, f in enumerate(result.screening.findings, 1)}
        if bundle
        else {}
    )
    items = [item for report in result.evidence_reports for item in report.evidence_items]
    evidence_labels = {item.evidence_id: f"E{i}" for i, item in enumerate(items, 1)}
    blocks = [
        ("h1", "Trial improvement report"),
        ("p", f"TrialFair | {bundle.trial_id if bundle else result.run_id}"),
        ("p", bundle.title if bundle else "Investigation without validated screening"),
        (
            "p",
            f"Run status: {result.status}. Plan status: "
            f"{plan.status if plan else 'unavailable'}. Human review required.",
        ),
        (
            "p",
            f"Recorded model: {result.model_id or 'not recorded'}. Execution: {result.mode}. "
            f"Duration: {result.duration_ms / 1000:.1f} seconds.",
        ),
    ]
    if flags["synthetic"]:
        blocks.append(
            (
                "notice",
                "SIMULATED DATA — findings describe a fictional trial, "
                "not observed patient outcomes.",
            )
        )
    if flags["curated"]:
        blocks.append(
            (
                "notice",
                "CURATED EVIDENCE — sources and excerpt annotations were preselected; "
                "this is not an autonomous literature search.",
            )
        )
    if flags["fallback"]:
        blocks.append(
            (
                "notice",
                "RULES-BASED FALLBACK — a model stage did not complete valid output. "
                "Review the recorded limitations before using its assessment or draft.",
            )
        )
    blocks += [
        ("h2", "Review summary"),
        ("p", report_summary(result)),
        ("h2", "Prioritised action plan"),
    ]
    if plan:
        for number, rec in enumerate(plan.recommendations, 1):
            blocks += [
                ("h3", f"{number:02d} {rec.action}"),
                (
                    "p",
                    f"Priority: {rec.priority.title()} | "
                    f"{rec.category.replace('_', ' ').title()} | "
                    f"Data: {rec.availability.replace('_', ' ')}",
                ),
                ("p", rec.rationale),
                ("p", f"Priority rationale: {rec.priority_rationale}"),
                ("p", f"Question to resolve: {rec.resolves_question}"),
                ("p", f"Feasibility: {rec.feasibility}"),
                ("list", [f"Required data: {v}" for v in rec.required_data]),
                ("list", [f"Prerequisite: {v}" for v in rec.prerequisites]),
                (
                    "p",
                    "Linked findings: "
                    + ", ".join(finding_labels.get(fid, fid) for fid in rec.finding_ids),
                ),
                (
                    "p",
                    "Evidence: "
                    + (
                        ", ".join(evidence_labels.get(eid, eid) for eid in rec.evidence_ids)
                        or "No accepted external evidence linked"
                    ),
                ),
                ("list", rec.limitations),
            ]
    if not plan or not plan.recommendations:
        blocks.append(
            (
                "p",
                "No selected follow-up actions are available. Complete the outstanding "
                "investigation before relying on a plan.",
            )
        )
    blocks.append(("h2", "Screened findings"))
    for finding in result.screening.findings if bundle else []:
        blocks += [
            ("h3", f"{finding_labels[finding.finding_id]} {finding.title}"),
            ("p", finding.description),
            ("list", finding.limitations),
        ]
    blocks.append(("h2", "Evidence reviewed"))
    for item in items:
        source = source_records(result)[item.source_id]
        blocks += [
            ("h3", f"{evidence_labels[item.evidence_id]} {item.relation.title()} evidence"),
            ("p", item.claim),
            ("p", item.relevance),
            ("quote", item.source_locator.excerpt or "No excerpt recorded"),
            ("link", (source.title, str(source.url))) if source.url else ("p", source.title),
            (
                "p",
                f"Access: {source.access_level}. Licence: "
                f"{source.licence_name or source.licence_status}. "
                f"Retrieved: {source.retrieved_at.isoformat()}.",
            ),
            ("list", item.limitations),
        ]
    limitations = unique(
        [
            *(bundle.limitations if bundle else []),
            *(result.investigation.limitations if result.investigation else []),
            *(line for report in result.evidence_reports for line in report.limitations),
            *(plan.input_limitations if plan else []),
            *(plan.limitations if plan else []),
            *result.errors,
        ]
    )
    blocks += [
        ("h2", "Uncertainty and limitations"),
        ("list", limitations),
        ("h2", "Questions for researcher review"),
        (
            "list",
            unique(
                [
                    *(plan.unresolved_questions if plan else []),
                    *(result.investigation.unresolved_questions if result.investigation else []),
                ]
            ),
        ),
        (
            "p",
            "No analysis, experiment, dose change or trial-progression decision "
            "is authorised by this report.",
        ),
        (
            "p",
            f"Traceability: run {result.run_id}. Full IDs, numerical results and "
            "assumptions are in the accompanying validated JSON.",
        ),
    ]
    return blocks


def report_markdown(result):
    lines = []
    for kind, content in _outline(result):
        if kind in {"h1", "h2", "h3"}:
            lines.append("#" * int(kind[1]) + " " + content)
        elif kind == "list":
            lines.extend("- " + line for line in unique(content))
        elif kind in {"notice", "quote"}:
            lines.append("> " + content)
        elif kind == "link":
            lines.append(f"[{content[0]}](<{content[1]}>)")
        else:
            lines.append(content)
        lines.append("")
    return "\n".join(lines)


def report_html(result):
    body = []
    for kind, content in _outline(result):
        if kind == "list":
            if content:
                body.append(
                    "<ul>" + "".join(f"<li>{escape(v)}</li>" for v in unique(content)) + "</ul>"
                )
        elif kind == "link":
            body.append(
                f'<p><a href="{escape(content[1], quote=True)}">{escape(content[0])}</a></p>'
            )
        else:
            tag = kind if kind in {"h1", "h2", "h3"} else "blockquote" if kind == "quote" else "p"
            css = ' class="notice"' if kind == "notice" else ""
            body.append(f"<{tag}{css}>{escape(content)}</{tag}>")
    return (
        """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TrialFair trial improvement report</title><style>
body{font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#192d41;
max-width:880px;margin:48px auto;padding:0 32px;background:white}
h1{font-size:32px;line-height:1.2;color:#14283d}h2{margin-top:36px;padding-top:14px;
border-top:1px solid #e4eaf1;font-size:21px}h3{font-size:17px;margin-top:25px}
a{color:#276d76}blockquote{border-left:3px solid #65a7a5;padding:10px 18px;margin:16px 0;
background:#f3f8f8}.notice{background:#fff6e6;padding:12px 16px;border-radius:8px}
li{margin:5px 0}@media print{body{margin:0;max-width:none;font-size:10pt}
h2,h3{break-after:avoid}a{color:#192d41}@page{size:A4;margin:18mm}}
</style><main>"""
        + "\n".join(body)
        + "</main></html>"
    )
