"""SDK-shape tests: use real SDK types with an injected fake transport, never a key."""

import asyncio
from types import SimpleNamespace

from google.genai import types

from app.model_client import GeminiModelClient, ModelMessage, ToolDefinition, _provider_schema


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        return next(self.responses)


def response(parts):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts),
            )
        ]
    )


def test_tool_continuation_preserves_opaque_signatures():
    models = FakeModels(
        [
            response(
                [
                    types.Part(text="private reasoning", thought=True),
                    types.Part(
                        function_call=types.FunctionCall(name="inspect", args={"id": "a"}),
                        thought_signature=b"opaque-signature",
                    ),
                ]
            ),
            response([types.Part(text='{"ok":true}')]),
        ]
    )
    client = GeminiModelClient(
        api_key="test-only-placeholder",
        model_id="test-model",
        sdk_client=SimpleNamespace(aio=SimpleNamespace(models=models)),
    )

    async def scenario():
        messages = [
            ModelMessage(role="system", content="System rule"),
            ModelMessage(role="user", content="Inspect a"),
        ]
        first = await client.generate(
            messages,
            tools=[
                ToolDefinition(
                    name="inspect",
                    description="Inspect an ID",
                    input_schema={"type": "object"},
                )
            ],
            timeout_seconds=1,
        )
        assert first.text is None
        assert first.tool_calls[0].arguments == {"id": "a"}
        messages.append(ModelMessage(role="assistant", content=first.model_dump(mode="json")))
        messages.append(
            ModelMessage(
                role="tool",
                content={
                    "call_id": first.tool_calls[0].call_id,
                    "name": "inspect",
                    "result": {"id": "a"},
                },
            )
        )
        last = await client.generate(
            messages,
            tools=[],
            output_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
            },
            timeout_seconds=1,
        )
        assert last.structured_output == {"ok": True}

    asyncio.run(scenario())
    request = models.requests[1]
    assert request["model"] == "test-model"
    assert request["contents"][1].parts[1].thought_signature == b"opaque-signature"
    assert request["contents"][2].parts[0].function_response.name == "inspect"
    assert request["config"].automatic_function_calling.disable is True
    assert request["config"].http_options.retry_options.attempts == 1
    assert request["config"].http_options.timeout == 1000


def test_recursive_json_schema_is_not_forwarded():
    value = {
        "$defs": {"JsonValue": {"anyOf": []}},
        "properties": {
            "parameters": {"type": "object", "additionalProperties": {"$ref": "#/$defs/JsonValue"}},
        },
    }
    converted = _provider_schema(value)
    assert converted["properties"]["parameters"]["additionalProperties"] == {}
    assert "JsonValue" not in converted["$defs"]
    assert "JsonValue" in value["$defs"]  # Original schema unchanged.
