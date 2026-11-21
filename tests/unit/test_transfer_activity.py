from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from onchain_risk_api.app import create_app
from onchain_risk_api.domain.models import Erc20TransferActivityResponse, Erc20TransferEvent
from onchain_risk_api.rules.transfer_activity import ZERO_ADDRESS
from onchain_risk_api.services.transfer_activity import MAX_BLOCK_SPAN
from tests.helpers import FakeChainProvider
from tests.unit.test_allowance_api import OWNER, TOKEN, allowance_settings


def activity_app(events=None, **settings):
    chain = FakeChainProvider()
    chain.get_erc20_transfer_logs = AsyncMock(return_value=events or [])
    return create_app(
        settings=allowance_settings(erc20_allowed_spenders=[], **settings), provider=chain,
    ), chain


def event(index=0, *, from_address=OWNER, to_address="0x" + "33" * 20):
    return Erc20TransferEvent(
        transaction_hash="0x" + f"{index + 1:064x}", block_number=123 + index,
        log_index=index, from_address=from_address, to_address=to_address,
        amount_smallest_unit=str(index + 1),
    )


@pytest.mark.asyncio
async def test_activity_returns_bounded_events_and_evidence():
    app, chain = activity_app([event(), event(1)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["chainId"] == 84532
    assert payload["tokenAddress"] == TOKEN
    assert payload["ownerAddress"] == OWNER
    assert [item["amountSmallestUnit"] for item in payload["events"]] == ["1", "2"]
    assert payload["evidenceId"].startswith("evidence:")
    assert payload["findings"] == []
    assert chain.get_erc20_transfer_logs.await_args.kwargs == {
        "from_block": 123, "to_block": 123,
    }
    assert chain.block_requests == [123, 123, 123]


@pytest.mark.asyncio
async def test_activity_flags_zero_address_event_shapes_with_stable_evidence() -> None:
    events = [
        event(from_address=ZERO_ADDRESS),
        event(1, to_address=ZERO_ADDRESS),
    ]
    app, _ = activity_app(events)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )
        repeated = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )

    payload = first.json()
    findings = payload["findings"]
    assert [finding["ruleId"] for finding in findings] == [
        "ERC20_ZERO_ADDRESS_SOURCE",
        "ERC20_ZERO_ADDRESS_DESTINATION",
    ]
    assert all(finding["evidenceIds"] == [payload["evidenceId"]] for finding in findings)
    assert "mint-like" in findings[0]["summary"]
    assert "burn-like" in findings[1]["summary"]
    assert findings[0]["findingId"] != findings[1]["findingId"]
    assert repeated.json()["findings"] == findings


@pytest.mark.asyncio
async def test_activity_response_rejects_finding_for_other_evidence() -> None:
    app, _ = activity_app([event(from_address=ZERO_ADDRESS)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )
    payload = response.json()
    payload["findings"][0]["evidenceIds"] = ["evidence:" + "ff" * 32]
    with pytest.raises(ValidationError, match="activity evidence"):
        Erc20TransferActivityResponse.model_validate(payload)


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    {"fromBlock": 100, "toBlock": 100 + MAX_BLOCK_SPAN + 1},
    {"fromBlock": 123, "toBlock": 122},
])
async def test_activity_rejects_unbounded_ranges_before_rpc(query):
    app, chain = activity_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": OWNER, **query},
        )
    assert response.json()["error"]["code"] == "BLOCK_RANGE_TOO_LARGE"
    assert chain.chain_calls == 0
    chain.get_erc20_transfer_logs.assert_not_awaited()


@pytest.mark.asyncio
async def test_activity_rejects_more_than_result_limit():
    app, chain = activity_app([event(index) for index in range(101)])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )
    assert response.json()["error"]["code"] == "ACTIVITY_LIMIT_EXCEEDED"
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_activity_allowlist_and_network_rejection_do_not_read_chain():
    app, chain = activity_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token_response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{'0x' + '44' * 20}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )
        network_response = await client.get(
            f"/v1/networks/other/tokens/{TOKEN}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )
    assert token_response.json()["error"]["code"] == "TOKEN_NOT_CONFIGURED"
    assert network_response.json()["error"]["code"] == "NETWORK_NOT_CONFIGURED"
    assert chain.chain_calls == 0


@pytest.mark.asyncio
async def test_activity_empty_token_allowlist_permits_any_valid_token() -> None:
    token = "0x" + "44" * 20
    app, chain = activity_app(erc20_allowed_tokens=[])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{token}/activity",
            params={"owner": OWNER, "fromBlock": 123, "toBlock": 123},
        )

    assert response.status_code == 200
    assert response.json()["tokenAddress"] == token
    chain.get_erc20_transfer_logs.assert_awaited_once_with(
        token, OWNER, from_block=123, to_block=123,
    )


@pytest.mark.asyncio
async def test_activity_reorg_is_rejected():
    app, chain = activity_app([event()])
    chain.get_block = AsyncMock(side_effect=[
        chain.block,
        chain.block,
        chain.block.model_copy(update={"block_hash": "0x" + "cd" * 32}),
    ])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": OWNER, "fromBlock": 100, "toBlock": 123},
        )
    assert response.json()["error"]["code"] == "SNAPSHOT_CHANGED"


@pytest.mark.asyncio
async def test_activity_invalid_parameters_are_rejected_before_rpc():
    app, chain = activity_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/networks/base-sepolia/tokens/{TOKEN}/activity",
            params={"owner": "bad", "fromBlock": "1.5", "toBlock": 2},
        )
    assert response.status_code == 422
    assert chain.chain_calls == 0

@pytest.mark.asyncio
async def test_transfer_activity_tool_returns_bounded_event_evidence():
    app, chain = activity_app([event()])
    result = await app.state.tool_registry.execute(
        "get_erc20_transfer_activity",
        {
            "network_name": "base-sepolia",
            "token_address": TOKEN,
            "owner_address": OWNER,
            "from_block": 123,
            "to_block": 123,
        },
    )
    assert result.status == "ok"
    assert result.data.events[0].amount_smallest_unit == "1"
    assert result.data.evidence_id.startswith("evidence:")
    chain.get_erc20_transfer_logs.assert_awaited_once_with(
        TOKEN, OWNER, from_block=123, to_block=123,
    )


@pytest.mark.asyncio
async def test_transfer_activity_tool_rejects_missing_or_unbounded_range_before_rpc():
    app, chain = activity_app()
    result = await app.state.tool_registry.execute(
        "get_erc20_transfer_activity",
        {"network_name": "base-sepolia", "token_address": TOKEN, "owner_address": OWNER},
    )
    assert result.status == "error"
    assert result.error.code == "INVALID_TOOL_ARGUMENTS"
    chain.get_erc20_transfer_logs.assert_not_awaited()

    result = await app.state.tool_registry.execute(
        "get_erc20_transfer_activity",
        {
            "network_name": "base-sepolia", "token_address": TOKEN,
            "owner_address": OWNER, "from_block": 1, "to_block": 2_002,
        },
    )
    assert result.error.code == "BLOCK_RANGE_TOO_LARGE"
    chain.get_erc20_transfer_logs.assert_not_awaited()
