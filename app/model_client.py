"""Provider-neutral interface; the safety branch owns the single live Gemini adapter.

Tool arguments are untrusted until validated by the selected tool's Pydantic
schema. Tools must be allowlisted and consume the shared ToolContext budget.
"""

from typing import Protocol

from pydantic import Field, JsonValue

from app.contracts import Contract, Identifier


class ToolDefinition(Contract):
    name: Identifier
    description: str
    input_schema: dict[str, JsonValue]


class ModelMessage(Contract):
    role: str
    content: JsonValue


class ToolCall(Contract):
    call_id: Identifier
    name: Identifier
    arguments: dict[str, JsonValue]


class ModelResponse(Contract):
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    structured_output: dict[str, JsonValue] | None = None
    continuation: str | None = None


class ModelClient(Protocol):
    """Implement with google-genai; never silently change the configured model."""

    @property
    def model_id(self) -> str: ...

    async def generate(
        self,
        messages: list[ModelMessage],
        *,
        tools: list[ToolDefinition],
        output_schema: dict[str, JsonValue] | None = None,
        timeout_seconds: float,
        thinking_level: str | None = None,
    ) -> ModelResponse: ...


class GeminiModelClient:
    """One run-scoped Google SDK adapter with manual tools and no hidden retries.

    The caller consumes one model_turn before generate. This adapter does exactly
    one SDK request, preserves the provider's complete model content in memory
    (including opaque thought signatures) and never logs private reasoning.
    Instantiate only at an explicit live execution boundary, not at import time.
    """

    def __init__(self, *, api_key: str, model_id: str, sdk_client=None):
        if not api_key.strip() or not model_id.strip():
            raise ValueError("Gemini requires a configured key and model ID")
        from google import genai
        from google.genai import types

        self._model_id = model_id
        self._client = sdk_client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
        self._continuations = {}
        self._provider_ids = set()

    @property
    def model_id(self) -> str:
        return self._model_id

    def _contents(self, messages):
        """Resolve opaque in-memory continuation tokens without revealing thought text."""
        import json

        from google.genai import types

        system = []
        contents = []
        for message in messages:
            if message.role == "system":
                system.append(str(message.content))
                continue
            if message.role == "assistant":
                token = (
                    message.content.get("continuation")
                    if isinstance(message.content, dict)
                    else None
                )
                if token:
                    if token not in self._continuations:
                        raise ValueError("Unknown provider continuation")
                    contents.append(self._continuations[token])
                else:
                    raise ValueError("Gemini assistant turns require the original provider content")
                continue
            if message.role == "tool":
                value = message.content
                part = types.Part(
                    function_response=types.FunctionResponse(
                        id=value["call_id"] if value["call_id"] in self._provider_ids else None,
                        name=value["name"],
                        response={"result": value["result"]},
                    )
                )
                if contents and contents[-1].role == "user":
                    contents[-1].parts.append(part)
                else:
                    contents.append(types.Content(role="user", parts=[part]))
                continue
            if message.role != "user":
                raise ValueError("Unsupported model message role")
            text = (
                message.content if isinstance(message.content, str) else json.dumps(message.content)
            )
            contents.append(types.Content(role="user", parts=[types.Part(text=text)]))
        return "\n\n".join(system), contents

    async def generate(
        self,
        messages: list[ModelMessage],
        *,
        tools: list[ToolDefinition],
        output_schema: dict[str, JsonValue] | None = None,
        timeout_seconds: float,
        thinking_level: str | None = None,
    ) -> ModelResponse:
        import asyncio
        import json
        from uuid import uuid4

        from google.genai import types

        if tools and output_schema:
            raise ValueError("Use a separate structured-output turn after the tool loop")
        system, contents = self._contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            http_options=types.HttpOptions(
                timeout=max(1, int(timeout_seconds * 1000)),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        if tools:
            config.tools = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool.name,
                            description=tool.description,
                            parameters_json_schema=_provider_schema(tool.input_schema),
                        )
                        for tool in tools
                    ]
                )
            ]
        if thinking_level is not None:
            # Only sent when explicitly configured; models without thinking levels
            # would otherwise reject the request.
            config.thinking_config = types.ThinkingConfig(thinking_level=thinking_level.upper())
        if output_schema is not None:
            config.response_mime_type = "application/json"
            config.response_json_schema = _provider_schema(output_schema)
        async with asyncio.timeout(timeout_seconds):
            response = await self._client.aio.models.generate_content(
                model=self.model_id,
                contents=contents,
                config=config,
            )
        candidates = response.candidates or []
        if not candidates or not candidates[0].content:
            raise ValueError("Gemini returned no usable content")
        content = candidates[0].content
        token = str(uuid4())
        self._continuations[token] = content
        calls = []
        text_parts = []
        for part in content.parts or []:
            if part.thought:
                continue
            if part.function_call is not None:
                call = part.function_call
                if call.id:
                    self._provider_ids.add(call.id)
                calls.append(
                    ToolCall(
                        call_id=call.id or str(uuid4()),
                        name=call.name,
                        arguments=call.args or {},
                    )
                )
            elif part.text:
                text_parts.append(part.text)
        text = "".join(text_parts)
        structured = json.loads(text) if output_schema is not None else None
        return ModelResponse(
            text=text or None,
            tool_calls=calls,
            structured_output=structured,
            continuation=token,
        )

    async def aclose(self) -> None:
        """Release run-scoped SDK connections and opaque provider history."""
        await self._client.aio.aclose()
        self._continuations.clear()


def _provider_schema(schema: dict) -> dict:
    """Avoid recursive JsonValue schemas; validate all actual values with Pydantic."""
    import copy

    result = copy.deepcopy(schema)
    result.get("$defs", {}).pop("JsonValue", None)

    def walk(value):
        if isinstance(value, dict):
            if value.get("$ref") == "#/$defs/JsonValue":
                return {}
            return {key: walk(item) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(result)


async def generate_with_budget(
    context, messages, *, tools, output_schema=None, thinking_level=None
) -> ModelResponse:
    """Shared entry point for agent calls: count once and bound actual execution.

    All three agents should use this helper. ModelClient.generate itself does not
    consume the budget; SDK automatic calls/retries are disabled by the adapter.
    """
    import asyncio

    context.budget.consume("model_turn")
    async with asyncio.timeout(context.budget.remaining_seconds()):
        extra = {"thinking_level": thinking_level} if thinking_level else {}
        return await context.model.generate(
            messages,
            tools=tools,
            output_schema=output_schema,
            timeout_seconds=context.budget.remaining_seconds(),
            **extra,
        )
