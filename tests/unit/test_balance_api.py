from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient, Response

from onchain_risk_api.app import create_app
from onchain_risk_api.domain.errors import BlockNotFoundError, RpcUnavailableError
from tests.helpers import FakeChainProvider, make_test_settings

ADDRESS = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
BASE_PATH = "/v1/networks/{network_name}/addresses"


async def _get_balance(
    provider: FakeChainProvider,
    *,
    address: str = ADDRESS,
    query: str = "",
    settings=None,
) -> Response:
    resolved_settings = settings or make_test_settings()
    path = f"/v1/networks/{resolved_settings.network_name}/addresses"
    app = create_app(settings=resolved_settings, provider=provider)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(f"{path}/{address}/balance{query}")


@pytest.mark.asyncio
async def test_balance_is_a_fixed_block_snapshot_with_provenance() -> None:
    provider = FakeChainProvider()
    response = await _get_balance(provider, address=ADDRESS.lower())

    assert response.status_code == 200
    payload = response.json()
    observed_at = payload.pop("observedAt")
    assert datetime.fromisoformat(observed_at).utcoffset().total_seconds() == 0
    assert payload == {
        "network": "base-sepolia",
        "chainId": 84532,
        "provider": "blockpi",
        "address": ADDRESS,
        "asset": "ETH",
        "decimals": 18,
        "balanceSmallestUnit": "1000000000000000001",
        "balanceNative": "1.000000000000000001",
        "blockNumber": 123,
        "blockHash": provider.block.block_hash,
        "blockTimestamp": "2026-01-01T00:00:00Z",
    }
    assert provider.chain_calls == 1
    assert provider.block_requests == ["latest", 123]
    assert provider.balance_requests == [(ADDRESS, 123)]


@pytest.mark.asyncio
@pytest.mark.parametrize("block_number", [0, 123])
async def test_explicit_block_including_genesis_is_not_replaced_with_latest(
    block_number: int,
) -> None:
    provider = FakeChainProvider()
    provider.block = provider.block.model_copy(update={"number": block_number})

    response = await _get_balance(provider, query=f"?blockNumber={block_number}")

    assert response.status_code == 200
    assert provider.block_requests == [block_number, block_number]
    assert provider.balance_requests == [(ADDRESS, block_number)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("balance_smallest_unit", "expected_native"),
    [
        (0, "0.000000000000000000"),
        (1, "0.000000000000000001"),
        (10**18 + 1, "1.000000000000000001"),
        (
            2**256 - 1,
            "115792089237316195423570985008687907853269984665640564039457.584007913129639935",
        ),
    ],
)
async def test_balance_display_is_exact(
    balance_smallest_unit: int, expected_native: str
) -> None:
    response = await _get_balance(
        FakeChainProvider(balance_smallest_unit=balance_smallest_unit)
    )

    assert response.status_code == 200
    assert response.json()["balanceSmallestUnit"] == str(balance_smallest_unit)
    assert response.json()["balanceNative"] == expected_native


@pytest.mark.asyncio
async def test_configured_non_eth_network_uses_its_native_decimals() -> None:
    settings = make_test_settings(
        network_name="bsc",
        expected_chain_id=56,
        native_symbol="BNB",
        native_decimals=18,
        rpc_provider_name="ankr",
    )
    provider = FakeChainProvider(chain_id=56, balance_smallest_unit=10**18)
    response = await _get_balance(
        provider,
        settings=settings,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["network"] == "bsc"
    assert payload["chainId"] == 56
    assert payload["provider"] == "ankr"
    assert payload["asset"] == "BNB"
    assert payload["balanceNative"] == "1.000000000000000000"


@pytest.mark.asyncio
async def test_native_balance_supports_zero_decimals() -> None:
    settings = make_test_settings(
        network_name="example-chain",
        expected_chain_id=1337,
        native_symbol="UNIT",
        native_decimals=0,
    )
    provider = FakeChainProvider(chain_id=1337, balance_smallest_unit=123)

    response = await _get_balance(provider, settings=settings)

    assert response.status_code == 200
    assert response.json()["asset"] == "UNIT"
    assert response.json()["balanceNative"] == "123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    ["not-an-address", "0x1234", "0x" + "gg" * 20, ADDRESS[:-1] + "D", "1" * 40],
)
async def test_invalid_address_is_rejected_before_rpc(address: str) -> None:
    provider = FakeChainProvider()
    response = await _get_balance(provider, address=address)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert provider.chain_calls == 0
    assert provider.block_requests == []
    assert provider.balance_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address",
    [ADDRESS, ADDRESS.lower(), ADDRESS.upper().replace("0X", "0x"), "0x" + "0" * 40],
)
async def test_valid_address_forms_are_accepted(address: str) -> None:
    response = await _get_balance(FakeChainProvider(), address=address)

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["-1", "1.5", "latest", "abc", ""])
async def test_invalid_block_number_is_rejected_before_rpc(value: str) -> None:
    provider = FakeChainProvider()
    response = await _get_balance(provider, query=f"?blockNumber={value}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert provider.chain_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("chain_id", [1, 8453])
async def test_wrong_network_is_rejected_before_reading_state(chain_id: int) -> None:
    provider = FakeChainProvider(chain_id=chain_id)
    response = await _get_balance(provider)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAIN_ID_MISMATCH"
    assert provider.block_requests == []
    assert provider.balance_requests == []


@pytest.mark.asyncio
async def test_unconfigured_balance_network_is_rejected_before_rpc() -> None:
    provider = FakeChainProvider(chain_id=56)
    settings = make_test_settings(network_name="bsc", expected_chain_id=56)
    app = create_app(settings=settings, provider=provider)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/networks/arbitrum-one/addresses/{ADDRESS}/balance")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NETWORK_NOT_CONFIGURED"
    assert provider.chain_calls == 0
    assert provider.block_requests == []
    assert provider.balance_requests == []


@pytest.mark.asyncio
async def test_unknown_block_is_not_a_zero_balance() -> None:
    provider = FakeChainProvider()
    response = await _get_balance(provider, query="?blockNumber=124")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BLOCK_NOT_FOUND"
    assert provider.balance_requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", [False, True])
async def test_changed_or_disappearing_block_does_not_return_a_balance(missing: bool) -> None:
    provider = FakeChainProvider()
    changed = provider.block.model_copy(update={"block_hash": "0x" + "cd" * 32})
    provider.get_block = AsyncMock(
        side_effect=[provider.block, BlockNotFoundError() if missing else changed]
    )

    response = await _get_balance(provider)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SNAPSHOT_CHANGED"
    assert "balanceSmallestUnit" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_chain_id", "get_block", "get_balance"])
async def test_rpc_failure_at_each_boundary_is_sanitized(method: str) -> None:
    provider = FakeChainProvider()
    setattr(provider, method, AsyncMock(side_effect=RpcUnavailableError(provider_name="blockpi")))

    response = await _get_balance(provider)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RPC_UNAVAILABLE"
    assert "example.invalid" not in response.text


@pytest.mark.asyncio
async def test_openapi_documents_configured_balance_and_error_contracts() -> None:
    app = create_app(settings=make_test_settings(), provider=FakeChainProvider())
    operation = app.openapi()["paths"][BASE_PATH + "/{address}/balance"]["get"]

    assert {"200", "404", "422", "503"} <= operation["responses"].keys()
    assert next(item for item in operation["parameters"] if item["name"] == "address")[
        "schema"
    ]["pattern"] == "^0x[0-9a-fA-F]{40}$"
