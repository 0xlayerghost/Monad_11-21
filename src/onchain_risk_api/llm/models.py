from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from onchain_risk_api.domain.models import ApiError, ApiModel
from onchain_risk_api.tools.models import ToolCallResult, ToolDefinition


class FunctionCall(BaseModel):
    model_config = ConfigDict(strict=True)

    call_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    arguments: str = Field(max_length=16384)


class TokenUsage(BaseModel):
    model_config = ConfigDict(strict=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


@dataclass(frozen=True)
class ModelTurn:
    output: list[dict[str, Any]]
    calls: list[FunctionCall]
    text: str
    usage: TokenUsage


class ModelProvider(Protocol):
    async def complete(
        self, *, instructions: str, inputs: list[dict[str, Any]],
        tools: list[ToolDefinition], max_output_tokens: int,
    ) -> ModelTurn: ...


class ModelProviderError(Exception):
    def __init__(
        self, code: str, message: str, *, details: dict[str, int | str] | None = None,
    ) -> None:
        super().__init__(message)
        self.error = ApiError(code=code, message=message, details=details)


class TraceEvent(ApiModel):
    step: int
    kind: Literal["model", "tool"]
    call_id: str | None = None
    tool_name: str | None = None
    result: ToolCallResult | None = None


class AgentResult(ApiModel):
    status: Literal["completed", "stopped", "error"] = "stopped"
    stop_reason: str = "MODEL_CALL_LIMIT"
    answer: str | None = None
    answer_is_model_generated: Literal[True] = True
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    trace: list[TraceEvent] = Field(default_factory=list)
    error: ApiError | None = None


class InvestigationRequest(ApiModel):
    prompt: str = Field(min_length=1, max_length=8000)
