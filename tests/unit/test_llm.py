import asyncio
import copy
import io
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from onchain_risk_api.app import create_app
from onchain_risk_api.llm import __main__ as cli
from onchain_risk_api.llm.config import LlmSettings
from onchain_risk_api.llm.models import AgentResult, ModelProviderError, ModelTurn
from onchain_risk_api.llm.provider import OpenAIResponsesProvider, parse_response, responses_tools
from onchain_risk_api.llm.runner import InvestigationRunner
from onchain_risk_api.tools.registry import get_tool_definitions
from tests.helpers import TRANSACTION_HASH, FakeChainProvider, make_test_settings


def make_llm_settings(**overrides) -> LlmSettings:
    return LlmSettings(
        _env_file=None, api_key="test-key-not-real", model="test-model", **overrides
    )


def call_item(
    name="get_native_balance", arguments=None, call_id="call_balance",
) -> dict:
    if arguments is None:
        arguments = {"network_name": "base-sepolia", "address": "0x" + "11" * 20}
    return {
        "type": "function_call", "id": "fc_" + call_id, "call_id": call_id,
        "name": name, "arguments": json.dumps(arguments), "status": "completed",
    }


def response_payload(output=None) -> dict:
    return {
        "status": "completed",
        "output": output if output is not None else [{
            "type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "查询完成，请核对工具证据。"},
            ],
        }],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


class FakeModel:
    def __init__(self, *outputs) -> None:
        self.outputs = list(outputs)
        self.requests = []

    async def complete(self, **kwargs) -> ModelTurn:
        self.requests.append(copy.deepcopy(kwargs))
        return parse_response(response_payload(self.outputs.pop(0)))


def make_runner(model, *, chain=None, **limits):
    chain = chain or FakeChainProvider()
    app = create_app(settings=make_test_settings(), provider=chain)
    return InvestigationRunner(
        settings=make_llm_settings(**limits), provider=model, tools=app.state.tool_registry,
        network_name="base-sepolia", chain_id=84532,
    ), chain


def test_llm_config_loads_separately_and_redacts_secrets(monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sensitive-test-value")
    monkeypatch.setenv("LLM_MODEL", "configured-model")
    settings = LlmSettings(_env_file=None)
    assert settings.model == "configured-model"
    assert "sensitive-test-value" not in repr(settings)
    assert "sensitive-test-value" not in settings.model_dump_json()
    assert make_test_settings().network_name == "base-sepolia"


@pytest.mark.parametrize("endpoint", [
    "http://remote.example/v1", "https://user:password@example.com/v1",
    "https://example.com/v1?key=secret", "https://example.com/v1#fragment",
])
def test_llm_config_rejects_unsafe_endpoints(endpoint) -> None:
    with pytest.raises(ValidationError):
        make_llm_settings(base_url=endpoint)


@pytest.mark.parametrize("overrides", [
    {"max_tool_calls": 0}, {"max_model_calls": 11}, {"output_token_budget": 10},
    {"timeout_seconds": 0},
])
def test_llm_config_rejects_invalid_limits(overrides) -> None:
    with pytest.raises(ValidationError):
        make_llm_settings(**overrides)


def test_responses_schemas_are_strict_without_mutating_generic_tools() -> None:
    definitions = get_tool_definitions()
    original = copy.deepcopy(definitions)
    tools = responses_tools(definitions)
    assert definitions == original
    for tool in tools:
        assert tool["strict"] is True
        assert tool["parameters"]["additionalProperties"] is False
        assert set(tool["parameters"]["required"]) == set(tool["parameters"]["properties"])
        assert all("default" not in value for value in tool["parameters"]["properties"].values())
    assert {"type": "null"} in tools[0]["parameters"]["properties"]["block_number"]["anyOf"]


@pytest.mark.asyncio
async def test_loop_executes_real_registry_and_returns_evidence_to_model() -> None:
    reasoning = {"type": "reasoning", "id": "rs_test", "encrypted_content": "opaque"}
    model = FakeModel([reasoning, call_item()], None)
    runner, chain = make_runner(model)
    result = await runner.run("查询这个地址的余额")
    assert result.status == "completed"
    assert result.model_calls == 2
    assert result.tool_calls == 1
    assert (result.input_tokens, result.output_tokens) == (200, 40)
    assert len(chain.balance_requests) == 1
    assert [event.kind for event in result.trace] == ["model", "tool", "model"]
    assert model.requests[1]["inputs"][1] == reasoning
    returned = model.requests[1]["inputs"][-1]
    assert returned["call_id"] == "call_balance"
    assert returned["type"] == "function_call_output"
    assert json.loads(returned["output"])["callId"] == result.trace[1].call_id
    assert json.loads(returned["output"])["data"]["balanceSmallestUnit"] == str(10**18 + 1)
    for request in model.requests:
        assert "Cite that exact callId" in request["instructions"]
        assert (
            "Do not add address labels, contract identities or risk assessments absent "
            "from tool data." in request["instructions"]
        )
        assert "If tools omit finality, say it was not checked." in request["instructions"]
        assert (
            "Never infer finality or confirmation status from a block number or hash."
            in request["instructions"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", [
    "Query USDC token balance for 0x" + "11" * 20,
    "Check token allowances for 0x" + "11" * 20,
])
async def test_model_requests_explicitly_state_token_tool_limitations(prompt: str) -> None:
    model = FakeModel(None)
    runner, _ = make_runner(model)

    await runner.run(prompt)

    instructions = model.requests[0]["instructions"]
    assert "explicit ERC-20 balances and allowances are available" in instructions
    assert (
        "Approval discovery and enumeration of all token holdings are unsupported" in instructions
    )
    assert "never ask for spender for a balance query" in instructions
    assert "ask for missing addresses, never guess" in instructions
    assert "do not query native balances as a substitute." in instructions


@pytest.mark.asyncio
@pytest.mark.parametrize("transaction_hash", ["0x" + "0" * 64, "0x" + "f" * 64, TRANSACTION_HASH])
async def test_not_found_preserves_error_and_limits_hash_pattern_inferences(
    transaction_hash: str,
) -> None:
    chain = FakeChainProvider()
    chain.receipt = None
    chain.transaction = None
    model = FakeModel([call_item(
        "get_transaction_receipt",
        {"network_name": "base-sepolia", "transaction_hash": transaction_hash},
        call_id="call_receipt_missing",
    )], None)
    runner, chain = make_runner(model, chain=chain)

    result = await runner.run("Check this transaction on Base Sepolia")

    assert result.status == "completed"
    assert result.model_calls == 2
    assert result.tool_calls == 1
    assert chain.receipt_requests == [transaction_hash]
    assert chain.transaction_requests == [transaction_hash]
    assert chain.block_requests == []
    returned = model.requests[1]["inputs"][-1]
    payload = json.loads(returned["output"])
    assert returned["call_id"] == payload["callId"] == result.trace[1].call_id
    assert payload["status"] == "error"
    assert payload["data"] is None
    assert payload["error"]["code"] == "TRANSACTION_NOT_FOUND"
    for request in model.requests:
        assert "For TRANSACTION_NOT_FOUND" in request["instructions"]
        assert "do not claim global absence" in request["instructions"]
        assert (
            "Never infer a hash is fake, a placeholder, invalid or risky from its pattern."
            in request["instructions"]
        )


@pytest.mark.asyncio
async def test_missing_address_returns_clarification_without_chain_reads() -> None:
    model = FakeModel([{
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "请提供地址后我再查询。"}],
    }])
    runner, chain = make_runner(model)

    result = await runner.run("Please check the balance")

    assert result.status == "completed"
    assert result.answer == "请提供地址后我再查询。"
    assert result.model_calls == 1
    assert result.tool_calls == 0
    assert [event.kind for event in result.trace] == ["model"]
    assert chain.chain_calls == 0
    assert chain.balance_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "arguments", "error_code"), [
    ("send_transaction", {}, "UNKNOWN_TOOL"),
    ("get_native_balance", {"network_name": "base-sepolia"}, "INVALID_TOOL_ARGUMENTS"),
    ("get_native_balance", {
        "network_name": "bsc", "address": "0x" + "11" * 20,
    }, "NETWORK_NOT_CONFIGURED"),
])
async def test_rejected_calls_return_errors_without_chain_reads(
    name, arguments, error_code,
) -> None:
    model = FakeModel([call_item(name, arguments)], None)
    runner, chain = make_runner(model)
    result = await runner.run("查询")
    assert result.status == "completed"
    assert result.trace[1].result.error.code == error_code
    returned = model.requests[1]["inputs"][-1]
    assert json.loads(returned["output"])["callId"] == returned["call_id"]
    assert chain.balance_requests == []
    assert chain.chain_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_state", ["pending", "reverted"])
async def test_pending_and_revert_are_successful_tool_reads(receipt_state) -> None:
    chain = FakeChainProvider()
    if receipt_state == "pending":
        chain.receipt = None
        chain.transaction = chain.transaction.model_copy(update={
            "block_number": None, "block_hash": None,
        })
    else:
        chain.receipt = chain.receipt.model_copy(update={"status": 0})
    model = FakeModel([call_item("get_transaction_receipt", {
        "network_name": "base-sepolia", "transaction_hash": TRANSACTION_HASH,
    })], None)
    runner, _ = make_runner(model, chain=chain)
    result = await runner.run("检查交易")
    tool_result = result.trace[1].result
    assert result.status == "completed"
    assert tool_result.status == "ok"
    if receipt_state == "pending":
        assert tool_result.data.status == "pending"
    else:
        assert tool_result.data.execution_status == "reverted"


@pytest.mark.asyncio
@pytest.mark.parametrize(("limits", "expected"), [
    ({"max_model_calls": 1}, "MODEL_CALL_LIMIT"),
    ({"max_output_tokens": 800, "output_token_budget": 800}, "OUTPUT_BUDGET_LIMIT"),
])
async def test_no_tool_executes_without_a_followup_model_budget(limits, expected) -> None:
    runner, chain = make_runner(FakeModel([call_item()]), **limits)
    result = await runner.run("查询")
    assert result.status == "stopped"
    assert result.stop_reason == expected
    assert result.tool_calls == 0
    assert chain.balance_requests == []


@pytest.mark.asyncio
async def test_batch_exceeding_tool_budget_is_rejected_before_execution() -> None:
    model = FakeModel([call_item(), call_item(call_id="second")])
    runner, chain = make_runner(model, max_tool_calls=1)
    result = await runner.run("查询")
    assert result.stop_reason == "TOOL_CALL_LIMIT"
    assert chain.balance_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("same_turn", [True, False])
async def test_duplicate_call_ids_are_rejected(same_turn) -> None:
    outputs = [[call_item(), call_item()]] if same_turn else [[call_item()], [call_item()]]
    runner, chain = make_runner(FakeModel(*outputs))
    result = await runner.run("查询")
    assert result.status == "error"
    assert result.error.code == "LLM_INVALID_RESPONSE"
    assert len(chain.balance_requests) == (0 if same_turn else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["", "  ", "x" * 8001])
async def test_invalid_prompt_does_not_call_model(prompt) -> None:
    model = FakeModel()
    runner, _ = make_runner(model)
    result = await runner.run(prompt)
    assert result.stop_reason == "INVALID_PROMPT"
    assert model.requests == []


@pytest.mark.asyncio
async def test_context_budget_stops_before_second_model_call() -> None:
    model = FakeModel([
        {"type": "reasoning", "encrypted_content": "x" * 65000}, call_item(),
    ])
    runner, _ = make_runner(model)
    result = await runner.run("查询")
    assert result.stop_reason == "CONTEXT_LIMIT"
    assert result.model_calls == 1


@pytest.mark.asyncio
async def test_total_timeout_cancels_model_and_preserves_attempt_trace() -> None:
    async def slow(**kwargs):
        await asyncio.sleep(1)
    runner, _ = make_runner(type("SlowModel", (), {"complete": staticmethod(slow)})(),
                            run_timeout_seconds=0.01)
    result = await runner.run("查询")
    assert result.status == "stopped"
    assert result.stop_reason == "RUN_TIMEOUT"
    assert result.model_calls == 1
    assert len(result.trace) == 1


@pytest.mark.asyncio
async def test_unexpected_error_is_sanitized_and_cancellation_propagates() -> None:
    model = FakeModel()
    model.complete = AsyncMock(side_effect=RuntimeError("secret endpoint and key"))
    runner, _ = make_runner(model)
    result = await runner.run("查询")
    assert result.error.code == "AGENT_EXECUTION_FAILED"
    assert "secret" not in result.model_dump_json()
    model.complete = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await runner.run("查询")


@pytest.mark.asyncio
async def test_http_adapter_posts_responses_wire_format_without_persisted_state() -> None:
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response_payload([call_item()]))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIResponsesProvider(settings=make_llm_settings(), client=client)
        turn = await provider.complete(
            instructions="policy", inputs=[{"role": "user", "content": "query"}],
            tools=get_tool_definitions(), max_output_tokens=800,
        )
    assert turn.calls[0].call_id == "call_balance"
    assert str(requests[0].url) == "https://api.openai.com/v1/responses"
    assert requests[0].headers["Authorization"] == "Bearer test-key-not-real"
    body = json.loads(requests[0].content)
    assert body["store"] is False
    assert body["parallel_tool_calls"] is False
    assert body["include"] == ["reasoning.encrypted_content"]
    assert body["max_output_tokens"] == 800
    assert body["tools"][0]["strict"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "expected"), [
    (400, "LLM_REQUEST_REJECTED"), (422, "LLM_REQUEST_REJECTED"),
    (402, "LLM_BILLING_ERROR"),
    (404, "LLM_ENDPOINT_ERROR"), (405, "LLM_ENDPOINT_ERROR"),
    (401, "LLM_AUTH_ERROR"), (403, "LLM_AUTH_ERROR"), (429, "LLM_RATE_LIMITED"),
    (500, "LLM_UNAVAILABLE"), (503, "LLM_UNAVAILABLE"), (302, "LLM_UNAVAILABLE"),
    (418, "LLM_UNAVAILABLE"),
])
async def test_http_failures_do_not_retry_or_expose_body(status, expected) -> None:
    count = 0
    def handle(request):
        nonlocal count
        count += 1
        return httpx.Response(status, text="secret endpoint and key")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIResponsesProvider(settings=make_llm_settings(), client=client)
        runner, _ = make_runner(provider)
        result = await runner.run("查询")
    assert result.error.code == expected
    assert result.stop_reason == expected
    assert result.error.details == {"httpStatus": status}
    assert "secret" not in result.model_dump_json()
    assert result.tool_calls == 0
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "expected"), [
    (httpx.ConnectError, "LLM_CONNECTION_ERROR"),
    (httpx.RemoteProtocolError, "LLM_TRANSPORT_ERROR"),
    (httpx.ReadTimeout, "LLM_TIMEOUT"),
])
async def test_transport_failures_are_distinct_and_sanitized(failure, expected) -> None:
    count = 0

    def handle(request):
        nonlocal count
        count += 1
        raise failure("secret endpoint and key", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIResponsesProvider(settings=make_llm_settings(), client=client)
        runner, _ = make_runner(provider)
        result = await runner.run("查询")

    assert result.error.code == expected
    assert result.error.details is None
    assert "secret" not in result.model_dump_json()
    assert result.tool_calls == 0
    assert count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "invalid_json", "oversized"])
async def test_transport_and_response_limits(failure) -> None:
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret", request=request)
        return httpx.Response(200, content=b"not json" if failure == "invalid_json"
                              else b"x" * 1_000_001)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIResponsesProvider(settings=make_llm_settings(), client=client)
        runner, _ = make_runner(provider)
        result = await runner.run("查询")
    assert result.error.code == {
        "timeout": "LLM_TIMEOUT", "invalid_json": "LLM_INVALID_RESPONSE",
        "oversized": "LLM_RESPONSE_LIMIT",
    }[failure]


@pytest.mark.parametrize("payload", [
    {}, [], response_payload([]), response_payload([{"type": "web_search_call"}]),
    response_payload([{"type": "function_call", "name": "x", "arguments": "{}"}]),
    response_payload([{"type": "message", "role": "user", "content": []}]),
    {**response_payload(), "usage": {"input_tokens": -1, "output_tokens": 2}},
    {**response_payload(), "usage": {}},
])
def test_malformed_model_response_is_rejected(payload) -> None:
    with pytest.raises(ModelProviderError):
        parse_response(payload)


def test_refusal_text_is_a_final_answer() -> None:
    turn = parse_response(response_payload([{
        "type": "message", "role": "assistant", "content": [
            {"type": "refusal", "refusal": "I cannot help with that."},
        ],
    }]))
    assert turn.text == "I cannot help with that."


def test_cli_reads_stdin_and_returns_json(monkeypatch, capsys) -> None:
    investigate = AsyncMock(return_value=AgentResult(
        status="completed", stop_reason="ANSWER", answer="请提供地址",
    ))
    monkeypatch.setattr(cli, "_investigate", investigate)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("查询余额"))
    assert cli.main(["-"]) == 0
    investigate.assert_awaited_once_with("查询余额")
    assert json.loads(capsys.readouterr().out)["answer"] == "请提供地址"


def test_cli_bootstrap_failure_is_sanitized(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_investigate", AsyncMock(side_effect=ValueError("secret key")))
    assert cli.main(["查询"]) == 1
    output = capsys.readouterr().out
    assert "secret" not in output
    assert json.loads(output)["status"] == "error"


@pytest.mark.asyncio
async def test_application_closes_chain_even_when_context_body_fails() -> None:
    chain = FakeChainProvider()
    app = create_app(settings=make_test_settings(), provider=chain)
    with pytest.raises(RuntimeError):
        async with app.router.lifespan_context(app):
            raise RuntimeError("cancelled investigation")
    assert chain.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["certifi", "system"])
async def test_cli_wiring_roundtrip_uses_adapter_registry_and_closes_clients(
    monkeypatch, mode,
) -> None:
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        output = [call_item()] if len(requests) == 1 else None
        return httpx.Response(200, json=response_payload(output))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    chain = FakeChainProvider()
    app = create_app(settings=make_test_settings(), provider=chain)
    monkeypatch.setattr(cli, "LlmSettings", lambda: make_llm_settings(tls_trust_store=mode))
    monkeypatch.setattr(cli, "create_app", lambda: app)
    options = []

    def factory(**kwargs):
        options.append(kwargs)
        return client

    monkeypatch.setattr(cli.httpx, "AsyncClient", factory)
    result = await cli._investigate("查询余额")
    assert result.status == "completed"
    assert len(requests) == 2
    assert requests[1]["input"][-1]["type"] == "function_call_output"
    assert result.trace[1].result.data.block_number == 123
    assert chain.closed is True
    assert client.is_closed
    assert options[0]["trust_env"] is True
    if mode == "system":
        assert options[0]["verify"].check_hostname is True
    else:
        assert options[0]["verify"] is True


@pytest.mark.asyncio
async def test_total_timeout_cancels_rpc_read() -> None:
    chain = FakeChainProvider()
    async def slow_balance(*args, **kwargs):
        await asyncio.sleep(1)
    chain.get_balance = AsyncMock(side_effect=slow_balance)
    runner, _ = make_runner(
        FakeModel([call_item()]), chain=chain, run_timeout_seconds=0.01,
    )
    result = await runner.run("查询")
    assert result.status == "stopped"
    assert result.stop_reason == "RUN_TIMEOUT"
    assert result.tool_calls == 1
    assert result.answer is None


@pytest.mark.asyncio
async def test_multiple_calls_are_paired_and_returned_in_order() -> None:
    model = FakeModel([call_item(), call_item(call_id="second")], None)
    runner, chain = make_runner(model)
    result = await runner.run("查询两次")
    assert result.status == "completed"
    assert len(chain.balance_requests) == 2
    outputs = model.requests[1]["inputs"][-2:]
    assert [item["call_id"] for item in outputs] == ["call_balance", "second"]
    assert [json.loads(item["output"])["callId"] for item in outputs] == [
        event.call_id for event in result.trace if event.kind == "tool"
    ]


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
def test_incomplete_responses_do_not_become_successful_answers(status) -> None:
    with pytest.raises(ModelProviderError) as error:
        parse_response({**response_payload(), "status": status})
    assert error.value.error.code == "LLM_INCOMPLETE"
