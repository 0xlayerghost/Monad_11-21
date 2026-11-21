import os

import pytest
from pydantic import TypeAdapter, ValidationError

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.validation import TransactionHash
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider
from onchain_risk_api.services.balance import BalanceService
from onchain_risk_api.services.transaction import TransactionService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_configured_rpc_endpoint_matches_expected_network() -> None:
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to call the configured RPC.")

    try:
        settings = Settings()
    except ValidationError as exc:
        pytest.fail(f"Integration configuration is invalid: {exc}")

    provider = Web3RpcProvider(
        rpc_url=str(settings.rpc_url),
        timeout_seconds=settings.rpc_timeout_seconds,
        provider_name=settings.rpc_provider_name,
    )
    try:
        assert await provider.get_chain_id() == settings.expected_chain_id
    finally:
        await provider.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_configured_rpc_balance_snapshot_has_block_context() -> None:
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to call the configured RPC.")

    try:
        settings = Settings()
    except ValidationError:
        pytest.fail("Configure RPC_URL locally before running integration tests.")

    provider = Web3RpcProvider(
        rpc_url=str(settings.rpc_url),
        timeout_seconds=settings.rpc_timeout_seconds,
        provider_name=settings.rpc_provider_name,
    )
    try:
        service = BalanceService(settings=settings, provider=provider)
        result = await service.get_native_balance("0x0000000000000000000000000000000000000000")

        assert result.chain_id == settings.expected_chain_id
        assert int(result.balance_smallest_unit) >= 0
        assert result.block_number >= 0
        assert len(result.block_hash) == 66
        assert result.block_timestamp.tzinfo is not None
    finally:
        await provider.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_configured_rpc_receipt_has_matching_block_context() -> None:
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to call the configured RPC.")
    transaction_hash = os.getenv("INTEGRATION_TRANSACTION_HASH")
    if not transaction_hash:
        pytest.skip("Set INTEGRATION_TRANSACTION_HASH to a mined transaction on this network.")

    try:
        settings = Settings()
        transaction_hash = TypeAdapter(TransactionHash).validate_python(transaction_hash)
    except ValidationError:
        pytest.fail("Configure RPC_URL and a valid INTEGRATION_TRANSACTION_HASH locally.")

    provider = Web3RpcProvider(
        rpc_url=str(settings.rpc_url),
        timeout_seconds=settings.rpc_timeout_seconds,
        provider_name=settings.rpc_provider_name,
    )
    try:
        service = TransactionService(settings=settings, provider=provider)
        result = await service.get_receipt(transaction_hash)

        assert result.status == "mined"
        assert result.transaction_hash == transaction_hash
        assert result.chain_id == settings.expected_chain_id
        assert result.execution_status in {"success", "reverted"}
        assert result.block_number is not None
        assert result.block_timestamp.tzinfo is not None
        assert len(result.block_hash) == 66
        assert int(result.gas_used) >= 0
    finally:
        await provider.close()
