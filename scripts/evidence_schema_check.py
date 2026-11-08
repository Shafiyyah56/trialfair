"""One-call schema-only diagnostic using synthetic input; no literature requests."""

import asyncio
import json
import re
from urllib.parse import quote

from app.agents.evidence import EvidenceSynthesis, synthesis_schema
from app.model_client import ModelMessage, generate_with_budget


def redact_provider_message(message: str, api_key: str) -> str:
    """Only for schema-only synthetic requests; never dump SDK exception details."""
    text = str(message)
    if api_key:
        for secret in {api_key, quote(api_key, safe="")}:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"https?://[^\s\"'<>]+", "[URL REDACTED]", text)
    text = re.sub(r"(?i)(bearer\s+|api[_-]?key\s*[:=]\s*)[^\s,;\"']+", r"\1[REDACTED]", text)
    text = re.sub(r"AIza[\w-]{20,}", "[REDACTED]", text)
    return text[:1500]


async def check_schema(context) -> bool:
    """Print whether Gemini accepts the exact evidence schema, without running research."""
    print(
        "Testing evidence response schema: one Gemini call, no literature searches...", flush=True
    )
    schema = synthesis_schema()
    try:
        async with asyncio.timeout(25):
            reply = await generate_with_budget(
                context,
                [
                    ModelMessage(
                        role="user",
                        content="This is a synthetic schema transport check, not research. "
                        "Return empty evidence, questions, suggestions and limitations. "
                        "Set status to partial.",
                    )
                ],
                tools=[],
                output_schema=schema,
            )
        EvidenceSynthesis.model_validate(reply.structured_output)
        print(
            json.dumps(
                {
                    "mode": "live-schema-check",
                    "accepted": True,
                    "model_id": context.model.model_id,
                    "schema_bytes": len(json.dumps(schema)),
                    "model_turns": context.budget.used.get("model_turn", 0),
                },
                indent=2,
            )
        )
        return True
    except Exception as exc:
        # The prompt contains no source/narrative data. Only a separately redacted
        # provider message is exposed, never exc.details, headers or request objects.
        secret = context.settings.gemini_api_key
        key = secret.get_secret_value() if secret else ""
        message = redact_provider_message(getattr(exc, "message", ""), key)
        print(
            json.dumps(
                {
                    "mode": "live-schema-check",
                    "accepted": False,
                    "error_type": type(exc).__name__,
                    "http_code": getattr(exc, "code", None),
                    "provider_message": message or "No provider validation message available.",
                },
                indent=2,
            )
        )
        return False
