import json
from copy import deepcopy
from typing import Any

import httpx
from pydantic import ValidationError

from onchain_risk_api.llm.config import LlmSettings
from onchain_risk_api.llm.models import (
    FunctionCall,
    ModelProviderError,
    ModelTurn,
    TokenUsage,
)
from onchain_risk_api.tools.models import ToolDefinition

MAX_RESPONSE_BYTES = 1_000_000


def _http_error(status: int) -> ModelProviderError:
    if status in {400, 422}:
        code = "LLM_REQUEST_REJECTED"
        message = "Check the configured model and Responses API request compatibility."
    elif status in {401, 403}:
        code = "LLM_AUTH_ERROR"
        message = "Check model credentials and access."
    elif status == 402:
        code = "LLM_BILLING_ERROR"
        message = "Check the model account balance and billing access."
    elif status in {404, 405}:
        code = "LLM_ENDPOINT_ERROR"
        message = "Check the base URL, Responses API endpoint and model availability."
    elif status == 429:
        code = "LLM_RATE_LIMITED"
        message = "Check the model account rate limits and quota before trying again."
    else:
        code = "LLM_UNAVAILABLE"
        message = "The model service returned an unexpected HTTP status."
    return ModelProviderError(code, message, details={"httpStatus": status})


def responses_tools(definitions: list[ToolDefinition]) -> list[dict[str, Any]]:
    tools = []
    for definition in definitions:
        schema = deepcopy(definition.input_schema)
        schema["required"] = list(schema["properties"])
        for parameter in schema["properties"].values():
            parameter.pop("default", None)
        tools.append({
            "type": "function", "name": definition.name,
            "description": definition.description, "parameters": schema, "strict": True,
        })
    return tools


def parse_response(payload: object) -> ModelTurn:
    try:
        if not isinstance(payload, dict):
            raise ValueError
        if payload.get("status") != "completed":
            raise ModelProviderError("LLM_INCOMPLETE", "The model did not complete its response.")
        output = payload["output"]
        if not isinstance(output, list) or not output or len(output) > 32:
            raise ValueError
        calls = []
        texts = []
        for item in output:
            if not isinstance(item, dict):
                raise ValueError
            if item.get("type") == "function_call":
                calls.append(FunctionCall.model_validate(item))
            elif item.get("type") == "message":
                if item.get("role") != "assistant" or not isinstance(item.get("content"), list):
                    raise ValueError
                for content in item["content"]:
                    if content.get("type") == "output_text":
                        text = content["text"]
                    elif content.get("type") == "refusal":
                        text = content["refusal"]
                    else:
                        raise ValueError
                    if not isinstance(text, str):
                        raise ValueError
                    texts.append(text)
            elif item.get("type") != "reasoning":
                raise ValueError
        if not calls and not "".join(texts).strip():
            raise ValueError
        usage = TokenUsage.model_validate(payload["usage"])
        return ModelTurn(output=output, calls=calls, text="\n".join(texts), usage=usage)
    except (KeyError, TypeError, AttributeError, ValueError, ValidationError):
        raise ModelProviderError(
            "LLM_INVALID_RESPONSE", "The model returned invalid data."
        ) from None


class OpenAIResponsesProvider:
    def __init__(self, *, settings: LlmSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def complete(
        self, *, instructions: str, inputs: list[dict[str, Any]],
        tools: list[ToolDefinition], max_output_tokens: int,
    ) -> ModelTurn:
        payload = {
            "model": self._settings.model, "instructions": instructions, "input": inputs,
            "tools": responses_tools(tools), "parallel_tool_calls": False,
            "max_output_tokens": max_output_tokens, "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        try:
            async with self._client.stream(
                "POST", str(self._settings.base_url).rstrip("/") + "/responses",
                headers={"Authorization": "Bearer " + self._settings.api_key.get_secret_value()},
                json=payload, timeout=self._settings.timeout_seconds, follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise _http_error(response.status_code)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise ModelProviderError(
                            "LLM_RESPONSE_LIMIT", "Model response is too large."
                        )
            return parse_response(json.loads(body))
        except httpx.TimeoutException:
            raise ModelProviderError("LLM_TIMEOUT", "The model request timed out.") from None
        except httpx.ConnectError:
            raise ModelProviderError(
                "LLM_CONNECTION_ERROR", "Check network connectivity, DNS, TLS and proxy settings."
            ) from None
        except httpx.HTTPError:
            raise ModelProviderError(
                "LLM_TRANSPORT_ERROR", "The model connection failed during HTTP transport."
            ) from None
        except (ValueError, UnicodeError):
            raise ModelProviderError(
                "LLM_INVALID_RESPONSE", "The model returned invalid data."
            ) from None
