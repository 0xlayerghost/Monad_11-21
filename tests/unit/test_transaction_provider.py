from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from web3.exceptions import TransactionIndexingInProgress, TransactionNotFound

from onchain_risk_api.domain.errors import RpcUnavailableError
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider
from tests.helpers import TRANSACTION_HASH


def _provider(method: str, mock: AsyncMock) -> Web3RpcProvider:
    provider = Web3RpcProvider(
        rpc_url="https://example.invalid/secret", timeout_seconds=1, provider_name="test-rpc"
    )
    provider._web3 = SimpleNamespace(eth=SimpleNamespace(**{method: mock}))
    return provider


def _raw_receipt() -> dict:
    return {
        "transactionHash": b"\xcd" * 32,
        "blockNumber": 123,
        "blockHash": b"\xab" * 32,
        "transactionIndex": 0,
        "status": 1,
        "from": "0x" + "11" * 20,
        "to": "0x" + "22" * 20,
        "contractAddress": None,
        "gasUsed": 21000,
        "effectiveGasPrice": 10**9,
    }


@pytest.mark.asyncio
async def test_receipt_is_converted_to_validated_snapshot() -> None:
    get_receipt = AsyncMock(return_value=_raw_receipt())
    provider = _provider("get_transaction_receipt", get_receipt)

    receipt = await provider.get_transaction_receipt(TRANSACTION_HASH)

    assert receipt.transaction_hash == TRANSACTION_HASH
    assert receipt.block_hash == "0x" + "ab" * 32
    assert receipt.block_number == 123
    assert receipt.gas_used == 21000
    assert receipt.effective_gas_price == 10**9
    get_receipt.assert_awaited_once_with(TRANSACTION_HASH)


@pytest.mark.asyncio
@pytest.mark.parametrize("mined", [False, True])
async def test_transaction_lookup_preserves_pending_or_mined_context(mined: bool) -> None:
    raw = {
        "hash": b"\xcd" * 32,
        "blockNumber": 123 if mined else None,
        "blockHash": b"\xab" * 32 if mined else None,
    }
    get_transaction = AsyncMock(return_value=raw)

    provider = _provider("get_transaction", get_transaction)
    transaction = await provider.get_transaction(TRANSACTION_HASH)

    assert transaction.transaction_hash == TRANSACTION_HASH
    assert transaction.block_number == raw["blockNumber"]
    assert transaction.block_hash == ("0x" + "ab" * 32 if mined else None)
    get_transaction.assert_awaited_once_with(TRANSACTION_HASH)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_transaction", "get_transaction_receipt"])
@pytest.mark.parametrize("raises", [False, True])
async def test_only_null_and_transaction_not_found_mean_absence(method: str, raises: bool) -> None:
    mock = (
        AsyncMock(side_effect=TransactionNotFound("missing"))
        if raises else AsyncMock(return_value=None)
    )
    provider = _provider(method, mock)

    assert await getattr(provider, method)(TRANSACTION_HASH) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field, value",
    [
        ("transactionHash", b"\xff" * 32),
        ("transactionHash", b"\xcd" * 31),
        ("blockNumber", None),
        ("blockNumber", -1),
        ("blockNumber", True),
        ("blockHash", None),
        ("blockHash", b"\xab" * 31),
        ("transactionIndex", -1),
        ("status", None),
        ("status", 2),
        ("status", True),
        ("from", "invalid"),
        ("to", "invalid"),
        ("contractAddress", "invalid"),
        ("gasUsed", -1),
        ("gasUsed", 2**256),
        ("gasUsed", "21000"),
        ("effectiveGasPrice", -1),
        ("effectiveGasPrice", True),
    ],
)
async def test_malformed_receipts_are_not_valid_data(field: str, value: object) -> None:
    raw = _raw_receipt()
    raw[field] = value
    provider = _provider("get_transaction_receipt", AsyncMock(return_value=raw))

    with pytest.raises(RpcUnavailableError):
        await provider.get_transaction_receipt(TRANSACTION_HASH)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"hash": b"\xef" * 32, "blockNumber": None, "blockHash": None},
        {"hash": b"\xcd" * 32, "blockNumber": 123, "blockHash": None},
        {"hash": b"\xcd" * 32, "blockNumber": None, "blockHash": b"\xab" * 32},
        {"hash": b"\xcd" * 32, "blockNumber": True, "blockHash": b"\xab" * 32},
    ],
)
async def test_malformed_transactions_are_not_reported_as_pending(raw: dict) -> None:
    provider = _provider("get_transaction", AsyncMock(return_value=raw))

    with pytest.raises(RpcUnavailableError):
        await provider.get_transaction(TRANSACTION_HASH)


@pytest.mark.asyncio
async def test_optional_effective_gas_price_and_contract_creation() -> None:
    raw = _raw_receipt()
    del raw["effectiveGasPrice"]
    raw["to"] = None
    raw["contractAddress"] = "0x" + "33" * 20
    provider = _provider("get_transaction_receipt", AsyncMock(return_value=raw))

    receipt = await provider.get_transaction_receipt(TRANSACTION_HASH)

    assert receipt.effective_gas_price is None
    assert receipt.to_address is None
    assert receipt.contract_address == "0x" + "33" * 20


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_transaction", "get_transaction_receipt"])
@pytest.mark.parametrize(
    "error_type", [TimeoutError, ConnectionError, ValueError, TransactionIndexingInProgress]
)
async def test_rpc_errors_preserve_configured_provider_without_leaking_details(
    method: str, error_type: type[Exception]
) -> None:
    provider = _provider(method, AsyncMock(side_effect=error_type("https://example.invalid/secret")))

    with pytest.raises(RpcUnavailableError) as captured:
        await getattr(provider, method)(TRANSACTION_HASH)

    assert captured.value.provider_name == "test-rpc"
    assert str(captured.value) == "RPC provider test-rpc is unavailable."
    assert "secret" not in str(captured.value)
