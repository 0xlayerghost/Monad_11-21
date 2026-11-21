import os

import pytest
from pydantic import ValidationError

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import QueryError
from onchain_risk_api.domain.failures import describe_query_error
from onchain_risk_api.token_balance_snapshot import capture_snapshot
from onchain_risk_api.tools.models import Erc20BalanceArguments


@pytest.mark.integration
@pytest.mark.asyncio
async def test_base_sepolia_token_balance_has_repeatable_snapshot():
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_INTEGRATION_TESTS=1 to call the configured RPC.")
    token = os.getenv("INTEGRATION_TOKEN_BALANCE_TOKEN")
    owner = os.getenv("INTEGRATION_TOKEN_BALANCE_OWNER")
    if not token or not owner:
        pytest.skip("Set INTEGRATION_TOKEN_BALANCE_TOKEN and OWNER to verified addresses.")
    try:
        settings = Settings()
        height = os.getenv("INTEGRATION_TOKEN_BALANCE_BLOCK_NUMBER")
        arguments = Erc20BalanceArguments(
            network_name="base-sepolia", token_address=token, owner_address=owner,
            block_number=int(height) if height is not None else None,
        )
    except (ValidationError, ValueError):
        pytest.fail(
            "Configure RPC, token allowlist and valid balance inputs locally.", pytrace=False,
        )
    assert settings.network_name == "base-sepolia" and settings.expected_chain_id == 84532
    try:
        snapshot = await capture_snapshot(settings, arguments)
    except QueryError as exc:
        _, error = describe_query_error(exc)
        pytest.fail(f"Token balance RPC smoke failed: {error.code}.", pytrace=False)
    evidence = snapshot.first.evidence
    assert evidence.token_address == arguments.token_address
    assert evidence.owner_address == arguments.owner_address
    assert evidence.chain_id == 84532
    assert evidence.evidence_id == snapshot.repeated.evidence.evidence_id
    assert snapshot.independent_source_verified is False
    assert evidence.decimals is not None, (
        "Metadata unavailable; raw balance is not full acceptance."
    )
