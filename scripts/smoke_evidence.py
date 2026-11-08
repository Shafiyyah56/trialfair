"""Opt-in real Europe PMC / Agent 3 smoke check with progress and labelled output.

Run from repo root: .venv/bin/python -m scripts.smoke_evidence --live
Use --sources-only to check the public source API without any Gemini calls.
No patient data or keys are printed. The research question is not clinical advice.
"""

import argparse
import asyncio
import json
from time import monotonic
from uuid import uuid4

from app.agents.evidence import run_evidence
from app.config import Settings
from app.context import RunBudget
from app.contracts import EvidenceRequest
from app.runtime import build_context
from app.services.europe_pmc import EuropePMCClient


async def smoke(args):
    settings = Settings()
    if args.sources_only:
        print("Checking Europe PMC (no Gemini calls)...", flush=True)
        budget = RunBudget.from_settings(settings)
        client = EuropePMCClient(budget)
        records = await client.search_publications(args.query, page_size=2)
        print(
            json.dumps(
                {
                    "mode": "live-source-check",
                    "count": len(records),
                    "sources": [
                        {
                            "title": x.source.title,
                            "url": str(x.source.url),
                            "access_level": x.source.access_level,
                            "licence_status": x.source.licence_status,
                        }
                        for x in records
                    ],
                    "external_requests": budget.used.get("external_request", 0),
                },
                indent=2,
            )
        )
        return bool(records)
    context = build_context(str(uuid4()), "live")
    if args.schema_only:
        from scripts.evidence_schema_check import check_schema

        try:
            return await check_schema(context)
        finally:
            await context.aclose()
    context.emit = lambda event: print(f"{event.event_type}: {event.summary}", flush=True)
    request = EvidenceRequest(
        request_id=str(uuid4()),
        trial_id="standalone-literature-check",
        finding_ids=["standalone-question"],
        question=args.question,
        drug_names=args.drug or ["zolpidem"],
        symptom_terms=args.symptom or ["next-day impairment"],
        hypotheses_to_challenge=[
            "A reported sex difference applies uniformly across formulations."
        ],
    )
    started = monotonic()
    print("Starting live Agent 3 research using the configured model...", flush=True)
    try:
        report = await run_evidence(request, context)
        output = settings.data_dir / "evidence-smoke.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2))
        print(
            json.dumps(
                {
                    "mode": "live",
                    "model_id": context.model.model_id,
                    "status": report.status,
                    "searches": len(report.searches),
                    "sources": len(report.sources),
                    "evidence_items": len(report.evidence_items),
                    "cited_sources": len({item.source_id for item in report.evidence_items}),
                    "duration_seconds": round(monotonic() - started, 2),
                    "budget_used": context.budget.used,
                    "report_path": str(output),
                    "limitations": report.limitations,
                },
                indent=2,
            )
        )
        return bool(report.evidence_items)
    finally:
        await context.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow actual network/model requests")
    parser.add_argument("--drug", action="append", help="Drug term; repeat for more than one")
    parser.add_argument("--symptom", action="append", help="Symptom term; repeat as needed")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--sources-only", action="store_true", help="Do not call Gemini")
    checks.add_argument(
        "--schema-only", action="store_true", help="One model call, no literature searches"
    )
    parser.add_argument(
        "--query", default="zolpidem AND (sex OR women OR female) AND (exposure OR impairment)"
    )
    parser.add_argument(
        "--question",
        default="What human evidence reports sex differences in zolpidem exposure "
        "or next-day impairment, "
        "and are there contradictory findings or formulation limitations?",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to explicitly enable external requests")
    try:
        success = asyncio.run(smoke(args))
    except Exception as exc:
        raise SystemExit(
            f"Evidence check failed ({type(exc).__name__}); no credentials logged."
        ) from None
    if not success:
        if args.schema_only:
            raise SystemExit("Schema check failed; review the redacted validation message above.")
        raise SystemExit("No source-grounded evidence returned; review the recorded limitations.")
