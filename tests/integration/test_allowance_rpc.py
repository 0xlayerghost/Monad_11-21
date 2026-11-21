import os

import pytest
from pydantic import TypeAdapter, ValidationError

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.validation import EvmAddress
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider
from onchain_risk_api.services.allowance import AllowanceService


@pytest.mark.integration
@pytest.mark.asyncio
async def test_base_sepolia_allowance_has_repeatable_snapshot_evidence() -> None:
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to call the configured RPC.")
    inputs = [os.getenv(f"INTEGRATION_ALLOWANCE_{name}") for name in ("TOKEN", "OWNER", "SPENDER")]
    if not all(inputs):
        pytest.skip("Set INTEGRATION_ALLOWANCE_TOKEN, OWNER and SPENDER to verified addresses.")

    try:
        settings = Settings()
        token, owner, spender = [TypeAdapter(EvmAddress).validate_python(value) for value in inputs]
    except ValidationError:
        pytest.fail(
            "Configure RPC_URL, allowance allowlists and valid integration addresses locally."
        )
    assert settings.expected_chain_id == 84532, "This phase requires Base Sepolia, not Mainnet."
    assert settings.network_name == "base-sepolia"

    provider = Web3RpcProvider(
        rpc_url=str(settings.rpc_url),
        timeout_seconds=settings.rpc_timeout_seconds,
        provider_name=settings.rpc_provider_name,
    )
    try:
        service = AllowanceService(settings=settings, provider=provider)
        first = await service.get_allowance(
            token, owner, spender, network_name=settings.network_name
        )
        repeated = await service.get_allowance(
            token, owner, spender,
            network_name=settings.network_name, block_number=first.evidence.block_number,
        )
        assert first.evidence.chain_id == 84532
        assert first.evidence.token_address == token
        assert first.evidence.owner_address == owner
        assert first.evidence.spender_address == spender
        assert 0 <= int(first.evidence.allowance_smallest_unit) < 2**256
        assert first.evidence.evidence_id == repeated.evidence.evidence_id
        assert first.findings == repeated.findings
        assert first.limitations
    finally:
        await provider.close()
