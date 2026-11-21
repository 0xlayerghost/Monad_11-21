from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from web3.exceptions import BlockNotFound

from onchain_risk_api.domain.errors import BlockNotFoundError, RpcUnavailableError
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider

ADDRESS = "0x0000000000000000000000000000000000000000"


def _provider_with_eth(eth: SimpleNamespace) -> Web3RpcProvider:
    provider = Web3RpcProvider(
        rpc_url="https://example.invalid/secret", timeout_seconds=1, provider_name="blockpi"
    )
    provider._web3 = SimpleNamespace(eth=eth)
    return provider


@pytest.mark.asyncio
async def test_get_block_translates_hash_and_timestamp() -> None:
    get_block = AsyncMock(return_value={"number": 123, "hash": b"\xab" * 32, "timestamp": 0})
    provider = _provider_with_eth(SimpleNamespace(get_block=get_block))

    block = await provider.get_block("latest")

    assert block.number == 123
    assert block.block_hash == "0x" + "ab" * 32
    assert block.timestamp == datetime(1970, 1, 1, tzinfo=UTC)
    get_block.assert_awaited_once_with("latest")


@pytest.mark.asyncio
async def test_get_balance_uses_the_exact_block_number() -> None:
    get_balance = AsyncMock(return_value=10**18 + 1)
    provider = _provider_with_eth(SimpleNamespace(get_balance=get_balance))

    assert await provider.get_balance(ADDRESS, block_number=123) == 10**18 + 1
    get_balance.assert_awaited_once_with(ADDRESS, block_identifier=123)


@pytest.mark.asyncio
async def test_missing_block_is_distinct_from_transport_failure() -> None:
    provider = _provider_with_eth(
        SimpleNamespace(get_block=AsyncMock(side_effect=BlockNotFound("missing")))
    )

    with pytest.raises(BlockNotFoundError):
        await provider.get_block(123)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_block",
    [
        {},
        {"number": None, "hash": b"\xab" * 32, "timestamp": 0},
        {"number": 123, "hash": None, "timestamp": 0},
        {"number": 123, "hash": b"\xab", "timestamp": 0},
        {"number": 123, "hash": b"\xab" * 32, "timestamp": 10**30},
        {"number": 124, "hash": b"\xab" * 32, "timestamp": 0},
    ],
)
async def test_malformed_or_mismatched_block_is_not_trusted(raw_block: dict) -> None:
    provider = _provider_with_eth(SimpleNamespace(get_block=AsyncMock(return_value=raw_block)))

    with pytest.raises(RpcUnavailableError):
        await provider.get_block(123)


@pytest.mark.asyncio
@pytest.mark.parametrize("balance", [None, -1, 2**256, 1.5, True, "123"])
async def test_invalid_balance_is_not_treated_as_valid_state(balance: object) -> None:
    provider = _provider_with_eth(SimpleNamespace(get_balance=AsyncMock(return_value=balance)))

    with pytest.raises(RpcUnavailableError):
        await provider.get_balance(ADDRESS, block_number=123)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_block", "get_balance"])
@pytest.mark.parametrize("error_type", [TimeoutError, ConnectionError, ValueError])
async def test_provider_errors_are_sanitized(method: str, error_type: type[Exception]) -> None:
    provider = _provider_with_eth(
        SimpleNamespace(
            **{method: AsyncMock(side_effect=error_type("https://example.invalid/secret"))}
        )
    )

    with pytest.raises(RpcUnavailableError) as captured:
        if method == "get_block":
            await provider.get_block("latest")
        else:
            await provider.get_balance(ADDRESS, block_number=123)

    assert str(captured.value) == "RPC provider blockpi is unavailable."
    assert "secret" not in str(captured.value)
