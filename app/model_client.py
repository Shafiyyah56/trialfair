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
    ) -> ModelResponse: ...
