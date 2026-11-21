import pytest
from httpx import ASGITransport, AsyncClient

from onchain_risk_api.app import create_app
from tests.helpers import FakeChainProvider, make_test_settings


async def _get_status(
    provider: FakeChainProvider,
    *,
    network_name: str = "base-sepolia",
    settings=None,
):
    app = create_app(settings=settings or make_test_settings(), provider=provider)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        return await client.get(f"/v1/networks/{network_name}/status")


@pytest.mark.asyncio
async def test_configured_network_is_ready_when_chain_id_matches() -> None:
    response = await _get_status(FakeChainProvider(chain_id=84532))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["network"] == "base-sepolia"
    assert payload["chainId"] == 84532
    assert payload["expectedChainId"] == 84532
    assert payload["provider"] == "blockpi"
    assert payload["observedAt"].endswith("Z")


@pytest.mark.asyncio
@pytest.mark.parametrize("actual_chain_id", [1, 8453])
async def test_chain_mismatch_is_a_structured_service_error(actual_chain_id: int) -> None:
    response = await _get_status(FakeChainProvider(chain_id=actual_chain_id))

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "CHAIN_ID_MISMATCH",
            "message": "RPC network does not match the configured network.",
            "details": {"expectedChainId": 84532, "actualChainId": actual_chain_id},
        }
    }


@pytest.mark.asyncio
async def test_rpc_failure_does_not_expose_endpoint_details() -> None:
    response = await _get_status(FakeChainProvider(unavailable=True))

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "RPC_UNAVAILABLE",
            "message": "The configured RPC provider is temporarily unavailable.",
            "details": {"provider": "test-provider"},
        }
    }
    assert "example.invalid" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("network_name", "chain_id", "symbol", "provider_name"),
    [
        ("bsc", 56, "BNB", "ankr"),
        ("arbitrum-one", 42161, "ETH", "alchemy"),
    ],
)
async def test_network_and_provider_are_loaded_from_generic_settings(
    network_name: str, chain_id: int, symbol: str, provider_name: str
) -> None:
    settings = make_test_settings(
        network_name=network_name,
        expected_chain_id=chain_id,
        native_symbol=symbol,
        rpc_provider_name=provider_name,
    )
    response = await _get_status(
        FakeChainProvider(chain_id=chain_id),
        network_name=network_name,
        settings=settings,
    )

    assert response.status_code == 200
    assert response.json()["network"] == network_name
    assert response.json()["chainId"] == chain_id
    assert response.json()["provider"] == provider_name


@pytest.mark.asyncio
async def test_unconfigured_network_is_rejected_before_rpc() -> None:
    provider = FakeChainProvider(chain_id=56)
    response = await _get_status(
        provider,
        network_name="arbitrum-one",
        settings=make_test_settings(network_name="bsc", expected_chain_id=56),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NETWORK_NOT_CONFIGURED"
    assert provider.chain_calls == 0
