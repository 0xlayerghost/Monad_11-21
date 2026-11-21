from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from onchain_risk_api.app import create_app
from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import (
    BlockNotFoundError,
    RpcUnavailableError,
    TokenCallFailedError,
)
from tests.helpers import FakeChainProvider

TOKEN = "0x" + "11" * 20
OWNER = "0x" + "22" * 20
SPENDER = "0x" + "33" * 20
OTHER = "0x" + "44" * 20
MAX_UINT256 = 2**256 - 1


def allowance_settings(**updates) -> Settings:
    values = {
        "rpc_url": "https://example.invalid/private-endpoint",
        "rpc_provider_name": "blockpi",
        "erc20_allowed_tokens": [TOKEN],
        "erc20_allowed_spenders": [SPENDER],
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


async def query_allowance(provider, *, settings=None, **updates):
    arguments = {"token": TOKEN, "owner": OWNER, "spender": SPENDER, "network": "base-sepolia"}
    arguments.update(updates)
    params = {"owner": arguments["owner"], "spender": arguments["spender"]}
    if "block_number" in arguments:
        params["blockNumber"] = str(arguments["block_number"])
    app = create_app(settings=settings or allowance_settings(), provider=provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(
            f"/v1/networks/{arguments['network']}/tokens/{arguments['token']}/allowance",
            params=params,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 1, 10**30 + 1, MAX_UINT256 - 1, MAX_UINT256])
async def test_allowance_is_exact_with_provenance_and_referenced_findings(amount: int) -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=amount)
    response = await query_allowance(provider)
    assert response.status_code == 200
    payload = response.json()
    evidence = payload["evidence"]
    assert evidence["allowanceSmallestUnit"] == str(amount)
    assert evidence["chainId"] == 84532
    assert evidence["network"] == "base-sepolia"
    assert evidence["provider"] == "blockpi"
    assert evidence["tokenAddress"] == TOKEN
    assert evidence["ownerAddress"] == OWNER
    assert evidence["spenderAddress"] == SPENDER
    assert evidence["blockNumber"] == 123
    assert evidence["blockHash"] == provider.block.block_hash
    assert evidence["blockTimestamp"] == "2026-01-01T00:00:00Z"
    assert datetime.fromisoformat(evidence["observedAt"]).utcoffset().total_seconds() == 0
    assert evidence["evidenceId"].startswith("evidence:")
    assert provider.chain_calls == 1
    assert provider.block_requests == ["latest", 123]
    provider.get_erc20_allowance.assert_awaited_once_with(TOKEN, OWNER, SPENDER, block_number=123)
    assert payload["limitations"]
    assert len(payload["findings"]) == (0 if amount == 0 else 1)
    if payload["findings"]:
        finding = payload["findings"][0]
        expected_rule = (
            "ERC20_MAX_ALLOWANCE" if amount == MAX_UINT256 else "ERC20_NONZERO_ALLOWANCE"
        )
        assert finding["ruleId"] == expected_rule
        assert finding["ruleVersion"] == 1
        assert finding["severity"] == "attention"
        assert finding["evidenceIds"] == [evidence["evidenceId"]]
        assert finding["findingId"].startswith("finding:")


@pytest.mark.asyncio
async def test_ids_are_repeatable_and_change_with_owner_amount_or_block() -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=MAX_UINT256)
    first = (await query_allowance(provider)).json()
    repeated = (await query_allowance(provider)).json()
    assert first["evidence"]["evidenceId"] == repeated["evidence"]["evidenceId"]
    assert first["findings"] == repeated["findings"]
    other_owner = (await query_allowance(provider, owner=OTHER)).json()
    assert other_owner["evidence"]["evidenceId"] != first["evidence"]["evidenceId"]
    assert other_owner["findings"][0]["findingId"] != first["findings"][0]["findingId"]
    provider.get_erc20_allowance.return_value = 0
    other_amount = (await query_allowance(provider)).json()
    assert other_amount["evidence"]["evidenceId"] != first["evidence"]["evidenceId"]
    assert other_amount["findings"] == []
    provider.block = provider.block.model_copy(update={"block_hash": "0x" + "ef" * 32})
    other_block = (await query_allowance(provider)).json()
    assert other_block["evidence"]["evidenceId"] != other_amount["evidence"]["evidenceId"]


@pytest.mark.asyncio
@pytest.mark.parametrize("block_number", [0, 123])
async def test_explicit_block_including_genesis_is_respected(block_number: int) -> None:
    provider = FakeChainProvider()
    provider.block = provider.block.model_copy(update={"number": block_number})
    provider.get_erc20_allowance = AsyncMock(return_value=1)
    response = await query_allowance(provider, block_number=block_number)
    assert response.status_code == 200
    assert provider.block_requests == [block_number, block_number]


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"token": "bad"}, {"owner": "bad"}, {"spender": "bad"},
    {"block_number": -1}, {"block_number": "1.5"},
])
async def test_invalid_input_is_rejected_before_rpc(arguments: dict) -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=0)
    response = await query_allowance(provider, **arguments)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert provider.chain_calls == 0
    provider.get_erc20_allowance.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(("arguments", "expected_code"), [
    ({"token": OTHER}, "TOKEN_NOT_CONFIGURED"),
    ({"spender": OTHER}, "SPENDER_NOT_CONFIGURED"),
    ({"network": "base"}, "NETWORK_NOT_CONFIGURED"),
])
async def test_unconfigured_scope_does_not_read_contract(
    arguments: dict, expected_code: str
) -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=0)
    response = await query_allowance(provider, **arguments)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == expected_code
    provider.get_erc20_allowance.assert_not_awaited()
    assert provider.block_requests == []


@pytest.mark.asyncio
async def test_empty_token_allowlist_allows_token_but_empty_spenders_reject_query() -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=0)
    response = await query_allowance(provider, settings=allowance_settings(
        erc20_allowed_tokens=[], erc20_allowed_spenders=[],
    ))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SPENDER_NOT_CONFIGURED"
    provider.get_erc20_allowance.assert_not_awaited()


@pytest.mark.asyncio
async def test_empty_token_allowlist_permits_allowance_for_configured_spender() -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=7)
    response = await query_allowance(
        provider,
        settings=allowance_settings(erc20_allowed_tokens=[]),
        token=OTHER,
    )

    assert response.status_code == 200
    assert response.json()["evidence"]["tokenAddress"] == OTHER
    provider.get_erc20_allowance.assert_awaited_once_with(
        OTHER, OWNER, SPENDER, block_number=provider.block.number,
    )


@pytest.mark.asyncio
async def test_base_mainnet_is_rejected_before_contract_read() -> None:
    provider = FakeChainProvider(chain_id=8453)
    provider.get_erc20_allowance = AsyncMock(return_value=0)
    response = await query_allowance(provider)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAIN_ID_MISMATCH"
    provider.get_erc20_allowance.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_block_does_not_become_zero_allowance() -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=0)
    response = await query_allowance(provider, block_number=999)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BLOCK_NOT_FOUND"
    provider.get_erc20_allowance.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("disappeared", [False, True])
async def test_reorg_or_disappearing_block_discards_evidence(disappeared: bool) -> None:
    provider = FakeChainProvider()
    next_block = BlockNotFoundError() if disappeared else provider.block.model_copy(
        update={"block_hash": "0x" + "ef" * 32}
    )
    provider.get_block = AsyncMock(side_effect=[provider.block, next_block])
    provider.get_erc20_allowance = AsyncMock(return_value=MAX_UINT256)
    response = await query_allowance(provider)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SNAPSHOT_CHANGED"
    assert "evidence" not in response.json()
    assert "findings" not in response.json()


@pytest.mark.asyncio
async def test_rpc_failure_is_not_zero_or_a_leaked_endpoint() -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(
        side_effect=RpcUnavailableError(provider_name="blockpi")
    )
    response = await query_allowance(provider)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RPC_UNAVAILABLE"
    assert "private-endpoint" not in response.text
    assert "evidence" not in response.json()


@pytest.mark.asyncio
async def test_token_call_failure_is_distinct_from_rpc_failure() -> None:
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(side_effect=TokenCallFailedError())
    response = await query_allowance(provider)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TOKEN_CALL_FAILED"
    assert "evidence" not in response.json()
    assert "findings" not in response.json()
    assert provider.block_requests == ["latest"]


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_step", ["chain", "select_block", "recheck_block"])
async def test_rpc_failure_at_each_snapshot_step_discards_results(failed_step: str) -> None:
    provider = FakeChainProvider()
    error = RpcUnavailableError(provider_name="blockpi")
    provider.get_erc20_allowance = AsyncMock(return_value=MAX_UINT256)
    if failed_step == "chain":
        provider.get_chain_id = AsyncMock(side_effect=error)
    elif failed_step == "select_block":
        provider.get_block = AsyncMock(side_effect=error)
    else:
        provider.get_block = AsyncMock(side_effect=[provider.block, error])
    response = await query_allowance(provider)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RPC_UNAVAILABLE"
    assert "evidence" not in response.json()
    assert "findings" not in response.json()
    if failed_step != "recheck_block":
        provider.get_erc20_allowance.assert_not_awaited()


@pytest.mark.asyncio
async def test_address_case_is_normalized_before_allowlist_matching_and_hashing() -> None:
    token = "0x" + "ab" * 20
    owner = "0x" + "cd" * 20
    spender = "0x" + "ef" * 20
    settings = allowance_settings(erc20_allowed_tokens=[token], erc20_allowed_spenders=[spender])
    provider = FakeChainProvider()
    provider.get_erc20_allowance = AsyncMock(return_value=MAX_UINT256)
    first = await query_allowance(
        provider, settings=settings, token=token, owner=owner, spender=spender
    )
    upper = await query_allowance(
        provider,
        settings=settings,
        token="0x" + token[2:].upper(),
        owner="0x" + owner[2:].upper(),
        spender="0x" + spender[2:].upper(),
    )
    assert first.status_code == upper.status_code == 200
    first_evidence = first.json()["evidence"]
    upper_evidence = upper.json()["evidence"]
    assert first_evidence["evidenceId"] == upper_evidence["evidenceId"]
    assert first.json()["findings"] == upper.json()["findings"]
    for field in ("tokenAddress", "ownerAddress", "spenderAddress"):
        assert first_evidence[field] == upper_evidence[field]
    provider.get_erc20_allowance.assert_awaited_with(
        settings.erc20_allowed_tokens[0],
        first_evidence["ownerAddress"],
        settings.erc20_allowed_spenders[0],
        block_number=123,
    )


def test_allowance_contract_is_in_openapi() -> None:
    app = create_app(settings=allowance_settings(), provider=FakeChainProvider())
    operation = app.openapi()["paths"][
        "/v1/networks/{network_name}/tokens/{token_address}/allowance"
    ]["get"]
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "network_name", "token_address", "owner", "spender", "blockNumber"
    }
    assert {"200", "404", "422", "503"} <= operation["responses"].keys()
