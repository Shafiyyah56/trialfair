"""Opt-in trial-to-report check. Requires --live; can incur Gemini charges."""

import argparse
import asyncio
import json
from uuid import uuid4

from app.contracts import TrialInput
from app.orchestrator import run_trial
from app.runtime import build_context


async def smoke(nct_id):
    trial_input = TrialInput(nct_id=nct_id, mode="live")
    context = build_context(str(uuid4()), "live")
    context.emit = lambda event: print(
        f"{event.agent}/{event.event_type}: {event.summary}", flush=True
    )
    try:
        result = await run_trial(trial_input, context)
        output = context.settings.data_dir / "pipeline-smoke.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(result.model_dump_json(indent=2))
        evidence_items = [item for r in result.evidence_reports for item in r.evidence_items]
        print(
            json.dumps(
                {
                    "mode": "live",
                    "model_id": result.model_id,
                    "trial_id": nct_id,
                    "status": result.status,
                    "duration_seconds": round(result.duration_ms / 1000, 2),
                    "screening_available": result.screening is not None,
                    "investigation_available": result.investigation is not None,
                    "evidence_reports": len(result.evidence_reports),
                    "evidence_items": len(evidence_items),
                    "cited_sources": len({item.source_id for item in evidence_items}),
                    "budget_used": context.budget.used,
                    "errors": result.errors,
                    "report_path": str(output),
                },
                indent=2,
            ),
            flush=True,
        )
        return bool(result.screening and result.investigation and evidence_items)
    finally:
        await context.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow source and paid model calls")
    parser.add_argument("--nct-id", required=True, help="Completed trial with posted results")
    args = parser.parse_args()
    if not args.live:
        parser.error("Explicit --live is required; no network requests were made.")
    if not asyncio.run(smoke(args.nct_id)):
        print("The full path returned no cited evidence; review pipeline-smoke.json.", flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
