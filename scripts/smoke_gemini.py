"""Opt-in live SDK check. Requires --live and local credentials; never prints the key.

Run: uv run --locked python -m scripts.smoke_gemini --live
This makes up to three model requests: a plain reply, tool selection and a final
structured response. The only tool is a local constant echo, with no clinical data.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from importlib.metadata import version

from app.config import Settings
from app.model_client import GeminiModelClient, ModelMessage, ToolDefinition


async def smoke():
    settings = Settings()
    settings.require_live_credentials()
    client = GeminiModelClient(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_id=settings.gemini_model,
    )
    result = {
        "date": datetime.now(UTC).isoformat(),
        "model_id": settings.gemini_model,
        "sdk_version": version("google-genai"),
        "api": "models.generate_content",
        "plain_response": False,
        "function_calling": False,
        "structured_output": False,
    }
    try:
        plain = await client.generate(
            [ModelMessage(role="user", content="Reply with OK.")], tools=[], timeout_seconds=20
        )
        if not plain.text:
            raise ValueError("No plain response")
        result["plain_response"] = True
        messages = [
            ModelMessage(
                role="user",
                content="Call trialfair_ping with token CHECK exactly once. "
                "Do not answer in text yet.",
            )
        ]
        first = await client.generate(
            messages,
            tools=[
                ToolDefinition(
                    name="trialfair_ping",
                    description="Echo a check token to verify tool round trip.",
                    input_schema={
                        "type": "object",
                        "properties": {"token": {"type": "string"}},
                        "required": ["token"],
                    },
                )
            ],
            timeout_seconds=20,
        )
        if len(first.tool_calls) != 1:
            raise ValueError("Expected exactly one ping call")
        call = first.tool_calls[0]
        if call.name != "trialfair_ping" or call.arguments != {"token": "CHECK"}:
            raise ValueError("Invalid ping call")
        result["function_calling"] = True
        messages.extend(
            [
                ModelMessage(role="assistant", content=first.model_dump(mode="json")),
                ModelMessage(
                    role="tool",
                    content={
                        "call_id": call.call_id,
                        "name": call.name,
                        "result": {"token": "CHECK"},
                    },
                ),
                ModelMessage(role="user", content="Return ok=true if the ping returned CHECK."),
            ]
        )
        final = await client.generate(
            messages,
            tools=[],
            output_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
            timeout_seconds=20,
        )
        if final.structured_output != {"ok": True}:
            raise ValueError("Structured round trip failed")
        result["structured_output"] = True
        print(json.dumps(result, indent=2))
    finally:
        await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow paid model requests")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to explicitly enable network/model calls")
    try:
        asyncio.run(smoke())
    except Exception as exc:
        # Provider exception text may contain request URLs: output only its class.
        raise SystemExit(
            f"Live check failed ({type(exc).__name__}); no credentials logged."
        ) from None
