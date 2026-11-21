import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from onchain_risk_api.app import create_app
from onchain_risk_api.domain.errors import (
    BlockNotFoundError,
    ChainMismatchError,
    NetworkNotConfiguredError,
    QueryError,
    ReceiptUnavailableError,
    RpcUnavailableError,
    SnapshotChangedError,
    TransactionNotFoundError,
)
from onchain_risk_api.domain.models import ApiError, TransactionReceiptResponse
from onchain_risk_api.tools.models import ToolCallResult
from onchain_risk_api.tools.registry import ReadOnlyToolRegistry, get_tool_definitions
from tests.helpers import TRANSACTION_HASH, FakeChainProvider, make_test_settings

ADDRESS = "0x" + "11" * 20
BALANCE_ARGUMENTS = {"network_name": "base-sepolia", "address": ADDRESS}
RECEIPT_ARGUMENTS = {"network_name": "base-sepolia", "transaction_hash": TRANSACTION_HASH}


def _registry(provider: FakeChainProvider) -> ReadOnlyToolRegistry:
    app = create_app(settings=make_test_settings(), provider=provider)
    return app.state.tool_registry


def test_definitions_only_expose_five_read_only_tools_with_closed_argument_schemas() -> None:
    definitions = get_tool_definitions()

    assert {item.name for item in definitions} == {
        "get_native_balance", "get_transaction_receipt", "get_erc20_allowance",
        "get_erc20_balance", "get_erc20_transfer_activity",
    }
    for definition in definitions:
        assert definition.read_only is True
        assert definition.input_schema["additionalProperties"] is False
        assert "network_name" in definition.input_schema["required"]
        assert "rpc_url" not in definition.input_schema["properties"]
        assert "private_key" not in definition.input_schema["properties"]
        if definition.name in {"get_erc20_allowance", "get_erc20_balance"}:
            assert definition.output_schema["properties"]["evidence"]
        elif definition.name == "get_erc20_transfer_activity":
            assert definition.output_schema["properties"]["evidenceId"]
            assert definition.output_schema["properties"]["findings"]
            assert "Empty findings do not mean safe" in definition.description
        else:
            assert definition.output_schema["properties"]["observedAt"]
    token_definitions = [item for item in definitions if "erc20" in item.name]
    assert all(
        "empty token list permits any valid token address" in item.description.lower()
        for item in token_definitions
    )


def test_exported_schema_mutations_do_not_modify_the_registry_contract() -> None:
    definition = next(item for item in get_tool_definitions() if item.name == "get_native_balance")
    definition.input_schema["properties"].clear()

    fresh = next(item for item in get_tool_definitions() if item.name == "get_native_balance")
    assert "address" in fresh.input_schema["properties"]


def test_captured_public_receipt_matches_the_tool_response_schema() -> None:
    path = Path(__file__).parents[1] / "fixtures" / "base_sepolia_receipt.json"
    captured = ToolCallResult.model_validate_json(path.read_text(encoding="utf-8"))

    assert captured.tool_name == "get_transaction_receipt"
    assert captured.status == "ok"
    assert isinstance(captured.data, TransactionReceiptResponse)
    assert captured.data.network == "base-sepolia"
    assert captured.data.chain_id == 84532
    assert captured.data.block_number == 52118979
    assert captured.data.execution_status == "success"
    assert captured.data.gas_used == "46158"
    assert captured.data.effective_gas_price == "0"


@pytest.mark.asyncio
@pytest.mark.parametrize("as_json", [False, True])
async def test_balance_tool_uses_real_service_and_preserves_exact_amounts(as_json: bool) -> None:
    provider = FakeChainProvider(balance_smallest_unit=2**256 - 1)
    arguments = json.dumps(BALANCE_ARGUMENTS) if as_json else dict(BALANCE_ARGUMENTS)

    result = await _registry(provider).execute("get_native_balance", arguments)

    assert result.status == "ok"
    assert result.error is None
    payload = result.model_dump(mode="json", by_alias=True)
    assert payload["toolName"] == "get_native_balance"
    assert payload["data"]["balanceSmallestUnit"] == str(2**256 - 1)
    assert payload["data"]["blockHash"] == provider.block.block_hash
    assert payload["data"]["observedAt"].endswith("Z")
    assert provider.chain_calls == 1
    assert provider.block_requests == ["latest", 123]


@pytest.mark.asyncio
async def test_explicit_block_zero_is_preserved() -> None:
    provider = FakeChainProvider()
    provider.block = provider.block.model_copy(update={"number": 0})

    result = await _registry(provider).execute(
        "get_native_balance", {**BALANCE_ARGUMENTS, "block_number": 0}
    )

    assert result.status == "ok"
    assert provider.block_requests == [0, 0]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["success", "reverted", "pending"])
async def test_transaction_states_remain_tool_data_not_execution_errors(state: str) -> None:
    provider = FakeChainProvider()
    if state == "pending":
        provider.receipt = None
        provider.transaction = provider.transaction.model_copy(
            update={"block_number": None, "block_hash": None}
        )
    elif state == "reverted":
        provider.receipt = provider.receipt.model_copy(update={"status": 0})

    result = await _registry(provider).execute("get_transaction_receipt", RECEIPT_ARGUMENTS)

    assert result.status == "ok"
    assert result.error is None
    assert result.data.status == ("pending" if state == "pending" else "mined")
    assert result.data.execution_status == (None if state == "pending" else state)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["send_transaction", "get_block", "__import__", "os.system"])
async def test_unknown_tools_never_call_rpc(name: str) -> None:
    provider = FakeChainProvider()

    result = await _registry(provider).execute(name, BALANCE_ARGUMENTS)

    assert result.status == "error"
    assert result.error.code == "UNKNOWN_TOOL"
    assert result.data is None
    assert provider.chain_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {**BALANCE_ARGUMENTS, "address": "invalid"},
        {**BALANCE_ARGUMENTS, "network_name": 84532},
        {**BALANCE_ARGUMENTS, "block_number": -1},
        {**BALANCE_ARGUMENTS, "block_number": True},
        {**BALANCE_ARGUMENTS, "block_number": "123"},
        {**BALANCE_ARGUMENTS, "block_number": 1.5},
        {**BALANCE_ARGUMENTS, "rpc_url": "https://example.invalid/secret"},
        {**BALANCE_ARGUMENTS, "private_key": "secret"},
        [], None, True, 123, "{", "null", "[]", "{}", '"hello"',
    ],
)
async def test_invalid_arguments_are_rejected_before_rpc_without_echoing_secrets(
    arguments: object,
) -> None:
    provider = FakeChainProvider()

    result = await _registry(provider).execute("get_native_balance", arguments)

    assert result.status == "error"
    assert result.error.code == "INVALID_TOOL_ARGUMENTS"
    assert provider.chain_calls == 0
    assert "secret" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_invalid_transaction_hash_never_calls_rpc() -> None:
    provider = FakeChainProvider()

    result = await _registry(provider).execute(
        "get_transaction_receipt", {**RECEIPT_ARGUMENTS, "transaction_hash": "0x123"}
    )

    assert result.error.code == "INVALID_TOOL_ARGUMENTS"
    assert provider.chain_calls == 0


@pytest.mark.asyncio
async def test_wrong_network_is_rejected_before_rpc() -> None:
    provider = FakeChainProvider()

    result = await _registry(provider).execute(
        "get_native_balance", {**BALANCE_ARGUMENTS, "network_name": "other-network"}
    )

    assert result.error.code == "NETWORK_NOT_CONFIGURED"
    assert provider.chain_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, status_code, code",
    [
        (BlockNotFoundError(), 404, "BLOCK_NOT_FOUND"),
        (NetworkNotConfiguredError(), 404, "NETWORK_NOT_CONFIGURED"),
        (TransactionNotFoundError(), 404, "TRANSACTION_NOT_FOUND"),
        (ReceiptUnavailableError(), 503, "RECEIPT_UNAVAILABLE"),
        (SnapshotChangedError(), 503, "SNAPSHOT_CHANGED"),
        (RpcUnavailableError(provider_name="test-provider"), 503, "RPC_UNAVAILABLE"),
        (ChainMismatchError(expected_chain_id=84532, actual_chain_id=1), 503, "CHAIN_ID_MISMATCH"),
        (QueryError("secret"), 503, "QUERY_UNAVAILABLE"),
    ],
)
async def test_tool_and_http_errors_have_identical_public_semantics(
    error: QueryError, status_code: int, code: str,
) -> None:
    provider = FakeChainProvider()
    provider.get_chain_id = AsyncMock(side_effect=error)
    app = create_app(settings=make_test_settings(), provider=provider)

    result = await app.state.tool_registry.execute("get_native_balance", BALANCE_ARGUMENTS)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/v1/networks/base-sepolia/addresses/{ADDRESS}/balance")

    assert response.status_code == status_code
    assert result.status == "error"
    assert result.error.code == code
    assert result.error.model_dump(mode="json", exclude_none=True) == response.json()["error"]
    assert "secret" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_result", [False, True])
async def test_unexpected_failures_and_malformed_results_do_not_leak_details(
    malformed_result: bool,
) -> None:
    handler = (
        AsyncMock(return_value={"bad": "secret"})
        if malformed_result else AsyncMock(side_effect=RuntimeError("secret"))
    )
    registry = ReadOnlyToolRegistry(
        balance_service=SimpleNamespace(get_native_balance=handler),
        transaction_service=SimpleNamespace(get_receipt=AsyncMock()),
        allowance_service=SimpleNamespace(get_allowance=AsyncMock()),
        token_balance_service=SimpleNamespace(get_token_balance=AsyncMock()),
        transfer_activity_service=SimpleNamespace(get_activity=AsyncMock()),
    )

    result = await registry.execute("get_native_balance", BALANCE_ARGUMENTS)

    assert result.status == "error"
    assert result.error.code == "TOOL_EXECUTION_FAILED"
    assert "secret" not in result.model_dump_json()


@pytest.mark.parametrize(
    "status, data, error",
    [
        ("ok", None, None),
        ("ok", None, ApiError(code="BAD", message="bad")),
        ("error", None, None),
    ],
)
def test_tool_result_cannot_hide_errors_as_success(
    status: str, data: object, error: object,
) -> None:
    with pytest.raises(ValidationError):
        ToolCallResult(tool_name="get_native_balance", status=status, data=data, error=error)
