from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient, Response

from onchain_risk_api.app import create_app
from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import BlockNotFoundError, RpcUnavailableError
from tests.helpers import TRANSACTION_HASH, FakeChainProvider, make_test_settings


async def _get_receipt(
    provider: FakeChainProvider,
    *,
    transaction_hash: str = TRANSACTION_HASH,
    network_name: str | None = None,
    settings: Settings | None = None,
) -> Response:
    resolved_settings = settings or make_test_settings()
    network = network_name or resolved_settings.network_name
    app = create_app(settings=resolved_settings, provider=provider)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(
            f"/v1/networks/{network}/transactions/{transaction_hash}/receipt"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_status, execution_status", [(0, "reverted"), (1, "success")])
async def test_mined_receipt_has_execution_status_and_block_provenance(
    receipt_status: int, execution_status: str
) -> None:
    provider = FakeChainProvider()
    provider.receipt = provider.receipt.model_copy(update={"status": receipt_status})

    response = await _get_receipt(provider)

    assert response.status_code == 200
    payload = response.json()
    observed_at = payload.pop("observedAt")
    assert datetime.fromisoformat(observed_at).utcoffset().total_seconds() == 0
    assert payload == {
        "status": "mined",
        "network": "base-sepolia",
        "chainId": 84532,
        "provider": "blockpi",
        "transactionHash": TRANSACTION_HASH,
        "executionStatus": execution_status,
        "blockNumber": 123,
        "blockHash": provider.block.block_hash,
        "blockTimestamp": "2026-01-01T00:00:00Z",
        "transactionIndex": 0,
        "fromAddress": "0x" + "11" * 20,
        "toAddress": "0x" + "22" * 20,
        "contractAddress": None,
        "gasUsed": "21000",
        "effectiveGasPrice": "1000000000",
    }
    assert provider.chain_calls == 1
    assert provider.receipt_requests == [TRANSACTION_HASH]
    assert provider.transaction_requests == []
    assert provider.block_requests == [123]


@pytest.mark.asyncio
async def test_pending_requires_a_known_transaction_without_a_block() -> None:
    provider = FakeChainProvider()
    provider.receipt = None
    provider.transaction = provider.transaction.model_copy(
        update={"block_number": None, "block_hash": None}
    )

    response = await _get_receipt(provider)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["transactionHash"] == TRANSACTION_HASH
    for field in (
        "executionStatus", "blockNumber", "blockHash", "blockTimestamp",
        "transactionIndex", "fromAddress", "toAddress", "contractAddress",
        "gasUsed", "effectiveGasPrice",
    ):
        assert payload[field] is None
    assert provider.transaction_requests == [TRANSACTION_HASH]
    assert provider.block_requests == []


@pytest.mark.asyncio
async def test_absent_receipt_and_transaction_are_not_pending() -> None:
    provider = FakeChainProvider()
    provider.receipt = None
    provider.transaction = None

    response = await _get_receipt(provider)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRANSACTION_NOT_FOUND"
    assert provider.block_requests == []


@pytest.mark.asyncio
async def test_mined_transaction_without_receipt_is_unavailable_not_pending() -> None:
    provider = FakeChainProvider()
    provider.receipt = None

    response = await _get_receipt(provider)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RECEIPT_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "transaction_hash",
    ["0x", "ab" * 32, "0x" + "ab" * 31, "0x" + "ab" * 33, "0x" + "gg" * 32],
)
async def test_invalid_hash_is_rejected_before_rpc(transaction_hash: str) -> None:
    provider = FakeChainProvider()

    response = await _get_receipt(provider, transaction_hash=transaction_hash)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert provider.chain_calls == 0
    assert provider.receipt_requests == []


@pytest.mark.asyncio
async def test_transaction_hash_is_normalized() -> None:
    provider = FakeChainProvider()

    response = await _get_receipt(provider, transaction_hash="0x" + "CD" * 32)

    assert response.status_code == 200
    assert provider.receipt_requests == [TRANSACTION_HASH]
    assert response.json()["transactionHash"] == TRANSACTION_HASH


@pytest.mark.asyncio
async def test_unknown_network_never_calls_rpc() -> None:
    provider = FakeChainProvider()

    response = await _get_receipt(provider, network_name="other-network")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NETWORK_NOT_CONFIGURED"
    assert provider.chain_calls == 0
    assert provider.receipt_requests == []


@pytest.mark.asyncio
async def test_chain_mismatch_never_queries_receipts() -> None:
    provider = FakeChainProvider(chain_id=1)

    response = await _get_receipt(provider)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAIN_ID_MISMATCH"
    assert provider.receipt_requests == []


@pytest.mark.asyncio
async def test_configured_network_and_provider_are_not_hardcoded() -> None:
    settings = make_test_settings(
        network_name="bsc", expected_chain_id=56, rpc_provider_name="other"
    )

    response = await _get_receipt(FakeChainProvider(chain_id=56), settings=settings)

    assert response.status_code == 200
    assert response.json()["network"] == "bsc"
    assert response.json()["chainId"] == 56
    assert response.json()["provider"] == "other"


@pytest.mark.asyncio
@pytest.mark.parametrize("disappeared", [False, True])
async def test_receipt_block_change_or_disappearance_is_not_a_valid_snapshot(
    disappeared: bool,
) -> None:
    provider = FakeChainProvider()
    if disappeared:
        provider.get_block = AsyncMock(side_effect=BlockNotFoundError())
    else:
        provider.block = provider.block.model_copy(update={"block_hash": "0x" + "ef" * 32})

    response = await _get_receipt(provider)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SNAPSHOT_CHANGED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method", ["get_chain_id", "get_transaction_receipt", "get_transaction", "get_block"]
)
async def test_rpc_failures_at_each_step_are_not_reported_as_missing(method: str) -> None:
    provider = FakeChainProvider()
    if method == "get_transaction":
        provider.receipt = None
    setattr(provider, method, AsyncMock(side_effect=RpcUnavailableError(provider_name="test-rpc")))

    response = await _get_receipt(provider)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "RPC_UNAVAILABLE"
    assert response.json()["error"]["details"]["provider"] == "test-rpc"


@pytest.mark.asyncio
@pytest.mark.parametrize("gas_used, gas_price", [(0, 0), (2**256 - 1, 2**256 - 1), (21000, None)])
async def test_gas_values_are_exact_strings_or_explicitly_unknown(
    gas_used: int, gas_price: int | None
) -> None:
    provider = FakeChainProvider()
    provider.receipt = provider.receipt.model_copy(
        update={"gas_used": gas_used, "effective_gas_price": gas_price}
    )

    response = await _get_receipt(provider)

    assert response.status_code == 200
    assert response.json()["gasUsed"] == str(gas_used)
    assert response.json()["effectiveGasPrice"] == (None if gas_price is None else str(gas_price))


@pytest.mark.asyncio
async def test_contract_creation_preserves_null_recipient_and_contract_address() -> None:
    provider = FakeChainProvider()
    provider.receipt = provider.receipt.model_copy(
        update={"to_address": None, "contract_address": "0x" + "33" * 20}
    )

    response = await _get_receipt(provider)

    assert response.status_code == 200
    assert response.json()["toAddress"] is None
    assert response.json()["contractAddress"] == "0x" + "33" * 20


def test_receipt_is_documented_in_openapi() -> None:
    schema = create_app(settings=make_test_settings(), provider=FakeChainProvider()).openapi()
    path = "/v1/networks/{network_name}/transactions/{transaction_hash}/receipt"
    route = schema["paths"][path]["get"]

    assert {"200", "404", "422", "503"} <= set(route["responses"])
    hash_parameter = next(
        item for item in route["parameters"] if item["name"] == "transaction_hash"
    )
    assert hash_parameter["schema"]["pattern"] == r"^0x[0-9a-fA-F]{64}$"
