import json
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from onchain_risk_api.app import create_app
from onchain_risk_api.domain.errors import (
    BlockNotFoundError,
    RpcUnavailableError,
    TokenCallFailedError,
)
from onchain_risk_api.domain.models import Erc20AllowanceResponse
from onchain_risk_api.llm.evidence import EvidenceRecorder, InvestigationEvidence
from onchain_risk_api.llm.models import AgentResult
from onchain_risk_api.llm.review import summarize_directory
from onchain_risk_api.llm.runner import InvestigationRunner
from tests.helpers import FakeChainProvider, make_test_settings
from tests.unit.test_llm import FakeModel, call_item, make_llm_settings

TOKEN = "0x" + "11" * 20
OWNER = "0x" + "22" * 20
SPENDER = "0x" + "33" * 20
ARGUMENTS = {
    "network_name": "base-sepolia", "token_address": TOKEN,
    "owner_address": OWNER, "spender_address": SPENDER, "block_number": 123,
}


def make_allowance_app(*, amount=0, settings=None):
    chain = FakeChainProvider()
    chain.get_erc20_allowance = AsyncMock(return_value=amount)
    settings = settings or make_test_settings().model_copy(update={
        "erc20_allowed_tokens": [TOKEN], "erc20_allowed_spenders": [SPENDER],
    })
    return create_app(settings=settings, provider=chain), chain


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 1, 10**30 + 1, 2**256 - 2, 2**256 - 1])
async def test_allowance_tool_reuses_service_and_preserves_exact_evidence(amount):
    app, chain = make_allowance_app(amount=amount)
    result = await app.state.tool_registry.execute("get_erc20_allowance", ARGUMENTS)

    assert result.status == "ok"
    assert isinstance(result.data, Erc20AllowanceResponse)
    payload = result.model_dump(mode="json", by_alias=True)
    evidence = payload["data"]["evidence"]
    assert evidence["allowanceSmallestUnit"] == str(amount)
    assert evidence["blockNumber"] == 123
    assert evidence["blockHash"] == chain.block.block_hash
    assert chain.block_requests == [123, 123]
    chain.get_erc20_allowance.assert_awaited_once_with(TOKEN, OWNER, SPENDER, block_number=123)
    if amount:
        assert payload["data"]["findings"][0]["evidenceIds"] == [evidence["evidenceId"]]
    else:
        assert payload["data"]["findings"] == []
    assert payload["data"]["limitations"]
    restored = type(result).model_validate_json(result.model_dump_json(by_alias=True))
    assert restored == result


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"owner_address": None}, {"token_address": "0x123"}, {"spender_address": ""},
    {"block_number": -1}, {"block_number": True}, {"block_number": "123"},
    {"private_key": "secret"}, {"rpc_url": "https://secret.invalid"},
])
async def test_allowance_tool_invalid_arguments_never_reach_rpc(updates):
    app, chain = make_allowance_app()
    result = await app.state.tool_registry.execute("get_erc20_allowance", {**ARGUMENTS, **updates})
    assert result.status == "error"
    assert result.error.code == "INVALID_TOOL_ARGUMENTS"
    assert result.data is None
    assert chain.chain_calls == 0
    chain.get_erc20_allowance.assert_not_awaited()
    assert "secret" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(("updates", "code"), [
    ({"network_name": "other-network"}, "NETWORK_NOT_CONFIGURED"),
    ({"token_address": OWNER}, "TOKEN_NOT_CONFIGURED"),
    ({"spender_address": OWNER}, "SPENDER_NOT_CONFIGURED"),
])
async def test_allowance_tool_cannot_bypass_network_or_allowlists(updates, code):
    app, chain = make_allowance_app()
    result = await app.state.tool_registry.execute("get_erc20_allowance", {**ARGUMENTS, **updates})
    assert result.error.code == code
    assert result.data is None
    assert chain.chain_calls == 0
    chain.get_erc20_allowance.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowance_tool_with_default_empty_spender_allowlist_fails_closed():
    app, chain = make_allowance_app(settings=make_test_settings())
    result = await app.state.tool_registry.execute("get_erc20_allowance", ARGUMENTS)
    assert result.error.code == "SPENDER_NOT_CONFIGURED"
    assert chain.chain_calls == 0
    chain.get_erc20_allowance.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "code"), [
    (TokenCallFailedError(), "TOKEN_CALL_FAILED"),
    (RpcUnavailableError(provider_name="blockpi"), "RPC_UNAVAILABLE"),
    (RuntimeError("secret endpoint"), "TOOL_EXECUTION_FAILED"),
])
async def test_allowance_tool_failures_are_not_zero_or_leaked_details(failure, code):
    app, chain = make_allowance_app()
    chain.get_erc20_allowance.side_effect = failure
    result = await app.state.tool_registry.execute("get_erc20_allowance", ARGUMENTS)
    assert result.status == "error"
    assert result.error.code == code
    assert result.data is None
    assert "secret" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_allowance_tool_rejects_changed_or_missing_snapshot(changed):
    app, chain = make_allowance_app()
    second = chain.block.model_copy(update={"block_hash": "0x" + "ef" * 32})
    chain.get_block = AsyncMock(
        side_effect=[chain.block, second if changed else BlockNotFoundError()]
    )
    result = await app.state.tool_registry.execute("get_erc20_allowance", ARGUMENTS)
    assert result.error.code == "SNAPSHOT_CHANGED"
    assert result.data is None


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_network", [False, True])
async def test_allowance_investigation_http_and_export_preserve_nested_evidence(
    tmp_path, wrong_network,
):
    app, chain = make_allowance_app(amount=2**256 - 1)
    model = FakeModel([call_item("get_erc20_allowance", ARGUMENTS, "call_allowance")], None)
    app.state.investigation_runner = InvestigationRunner(
        settings=make_llm_settings(), provider=model, tools=app.state.tool_registry,
        network_name="base-sepolia", chain_id=84532,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/investigations", json={"prompt": "Inspect this allowance"}
        )
    assert response.status_code == 200
    payload = response.json()
    assert (payload["modelCalls"], payload["toolCalls"]) == (2, 1)
    tool = payload["trace"][1]
    assert tool["callId"] == "call_allowance"
    assert tool["result"]["data"]["evidence"]["allowanceSmallestUnit"] == str(2**256 - 1)
    output = json.loads(model.requests[1]["inputs"][-1]["output"])
    assert output["callId"] == "call_allowance"
    assert output["data"] == tool["result"]["data"]
    instructions = model.requests[0]["instructions"]
    assert "ask for missing addresses, never guess" in instructions
    assert "empty token list permits any valid token address" in instructions
    assert "spender allowlist is always enforced" in instructions
    assert "empty list does not mean safe" in instructions
    assert "Tool errors never mean zero allowance" in instructions
    assert "mint-like or burn-like event shapes only" in instructions
    assert "Empty activity findings do not mean safe" in instructions
    assert "Never request keys, sign, send transactions" in instructions
    chain.get_erc20_allowance.assert_awaited_once()
    recorder = EvidenceRecorder(
        scenario_id="S01", prompt="Offline allowance test, not real evidence"
    )
    recorder.configure_network(app.state.settings)
    if wrong_network:
        payload["trace"][1]["result"]["data"]["evidence"]["chainId"] = 8453
    serialized = recorder.serialize(AgentResult.model_validate(payload))
    restored = InvestigationEvidence.model_validate_json(serialized)
    assert isinstance(restored.result.trace[1].result.data, Erc20AllowanceResponse)
    (tmp_path / "allowance.json").write_text(serialized, encoding="utf-8")
    report = summarize_directory(tmp_path)
    if wrong_network:
        assert report.records[0].issues == ["NETWORK_MISMATCH"]
    else:
        assert report.valid_files == 1
        assert report.review_counts["pending"] == 1


@pytest.mark.asyncio
async def test_allowance_investigation_retains_rejection_without_querying_balance():
    app, chain = make_allowance_app(settings=make_test_settings())
    model = FakeModel([call_item("get_erc20_allowance", ARGUMENTS, "call_rejected")], None)
    runner = InvestigationRunner(
        settings=make_llm_settings(), provider=model, tools=app.state.tool_registry,
        network_name="base-sepolia", chain_id=84532,
    )
    result = await runner.run("Query allowance")
    output = json.loads(model.requests[1]["inputs"][-1]["output"])
    assert output["callId"] == "call_rejected"
    assert output["data"] is None
    assert output["error"]["code"] == "SPENDER_NOT_CONFIGURED"
    assert result.trace[1].result.error.code == "SPENDER_NOT_CONFIGURED"
    assert chain.balance_requests == []
    chain.get_erc20_allowance.assert_not_awaited()
