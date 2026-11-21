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
from onchain_risk_api.llm.runner import InvestigationRunner
from tests.helpers import FakeChainProvider
from tests.unit.test_allowance_api import OWNER, TOKEN, allowance_settings
from tests.unit.test_llm import FakeModel, call_item, make_llm_settings

ARGUMENTS = {"network_name": "base-sepolia", "token_address": TOKEN, "owner_address": OWNER}


def balance_app(amount=10**30 + 1, decimals=6, **settings):
    chain = FakeChainProvider()
    chain.get_erc20_balance = AsyncMock(return_value=amount)
    chain.get_erc20_decimals = AsyncMock(return_value=decimals)
    return create_app(
        settings=allowance_settings(erc20_allowed_spenders=[], **settings), provider=chain,
    ), chain


async def query(app, *, token=TOKEN, network="base-sepolia", **params):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(
            f"/v1/networks/{network}/tokens/{token}/balance", params={"owner": OWNER, **params},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 1, 10**30 + 1, 2**256 - 1])
@pytest.mark.parametrize("decimals", [0, 6, 18, 255])
async def test_exact_balance_and_snapshot_without_spender(amount, decimals):
    app, chain = balance_app(amount, decimals)
    response = await query(app, blockNumber=123)
    assert response.status_code == 200
    evidence = response.json()["evidence"]
    whole, fraction = divmod(amount, 10**decimals)
    assert evidence["balanceSmallestUnit"] == str(amount)
    assert evidence["balanceFormatted"] == (
        f"{whole}.{fraction:0{decimals}d}" if decimals else str(whole)
    )
    assert evidence["metadataError"] is None
    assert evidence["chainId"] == 84532
    assert evidence["blockHash"] == chain.block.block_hash
    assert evidence["evidenceId"].startswith("evidence:")
    assert chain.block_requests == [123, 123]
    chain.get_erc20_balance.assert_awaited_once_with(TOKEN, OWNER, block_number=123)
    chain.get_erc20_decimals.assert_awaited_once_with(TOKEN, block_number=123)
    again = await query(app, blockNumber=123)
    assert again.json()["evidence"]["evidenceId"] == evidence["evidenceId"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    TokenCallFailedError(), RpcUnavailableError(provider_name="fake"),
])
async def test_metadata_failure_preserves_amount_without_assuming_precision(failure):
    app, chain = balance_app()
    chain.get_erc20_decimals.side_effect = failure
    response = await query(app)
    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert evidence["balanceSmallestUnit"] == str(10**30 + 1)
    assert evidence["balanceFormatted"] is None
    assert evidence["decimals"] is None
    assert evidence["metadataError"]["code"] in {"TOKEN_CALL_FAILED", "RPC_UNAVAILABLE"}
    assert chain.block_requests == ["latest", 123]


@pytest.mark.asyncio
@pytest.mark.parametrize(("params", "code"), [
    ({"owner": "bad"}, "VALIDATION_ERROR"),
    ({"token": "bad"}, "VALIDATION_ERROR"),
    ({"token": "0x" + "44" * 20}, "TOKEN_NOT_CONFIGURED"),
    ({"network": "other"}, "NETWORK_NOT_CONFIGURED"),
    ({"blockNumber": -1}, "VALIDATION_ERROR"),
])
async def test_rejected_queries_do_not_read_chain(params, code):
    app, chain = balance_app()
    response = await query(app, **params)
    assert response.json()["error"]["code"] == code
    assert chain.chain_calls == 0
    chain.get_erc20_balance.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_token_allowlist_permits_any_valid_token() -> None:
    token = "0x" + "44" * 20
    app, chain = balance_app(erc20_allowed_tokens=[])

    response = await query(app, token=token)

    assert response.status_code == 200
    assert response.json()["evidence"]["tokenAddress"] == token
    chain.get_erc20_balance.assert_awaited_once_with(token, OWNER, block_number=123)


@pytest.mark.asyncio
async def test_wrong_chain_prevents_token_calls():
    app, chain = balance_app()
    chain.chain_id = 1
    response = await query(app)
    assert response.json()["error"]["code"] == "CHAIN_ID_MISMATCH"
    chain.get_erc20_balance.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    TokenCallFailedError(), RpcUnavailableError(provider_name="fake"),
])
async def test_balance_failure_is_not_zero(failure):
    app, chain = balance_app()
    chain.get_erc20_balance.side_effect = failure
    response = await query(app)
    assert response.status_code in {422, 503}
    assert "evidence" not in response.json()
    chain.get_erc20_decimals.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [True, -1, 2**256, "1", None])
async def test_invalid_balance_is_rejected(amount):
    app, chain = balance_app(amount=amount)
    response = await query(app)
    assert response.json()["error"]["code"] == "RPC_UNAVAILABLE"
    chain.get_erc20_decimals.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("decimals", [True, -1, 256, "18", None])
async def test_invalid_decimals_cannot_fabricate_formatted_amount(decimals):
    app, _ = balance_app(decimals=decimals)
    response = await query(app)
    evidence = response.json()["evidence"]
    assert evidence["decimals"] is None
    assert evidence["balanceFormatted"] is None
    assert evidence["metadataError"]["code"] == "RPC_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_reorg_or_disappearing_block_rejects_balance(missing):
    app, chain = balance_app()
    chain.get_block = AsyncMock(side_effect=[
        chain.block,
        BlockNotFoundError() if missing else chain.block.model_copy(
            update={"block_hash": "0x" + "cd" * 32}
        ),
    ])
    response = await query(app)
    assert response.json()["error"]["code"] == "SNAPSHOT_CHANGED"


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"spender_address": OWNER}, {"owner_address": None}, {"block_number": True},
])
async def test_tool_rejects_invalid_arguments_before_rpc(updates):
    app, chain = balance_app()
    result = await app.state.tool_registry.execute("get_erc20_balance", {**ARGUMENTS, **updates})
    assert result.error.code == "INVALID_TOOL_ARGUMENTS"
    assert chain.chain_calls == 0


@pytest.mark.asyncio
async def test_ai_balance_query_uses_balance_tool_and_preserves_evidence():
    app, chain = balance_app()
    model = FakeModel([call_item("get_erc20_balance", ARGUMENTS, "call_token")], None)
    runner = InvestigationRunner(
        settings=make_llm_settings(), provider=model, tools=app.state.tool_registry,
        network_name="base-sepolia", chain_id=84532,
    )
    result = await runner.run("查询该 token 的 owner 余额，不是授权")
    assert result.status == "completed"
    assert result.tool_calls == 1
    assert result.trace[1].result.data.evidence.balance_smallest_unit == str(10**30 + 1)
    output = json.loads(model.requests[1]["inputs"][-1]["output"])
    assert output["callId"] == "call_token"
    assert "never ask for spender for a balance query" in model.requests[0]["instructions"]
    chain.get_erc20_balance.assert_awaited_once()
