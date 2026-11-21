import pytest
from httpx import ASGITransport, AsyncClient

from onchain_risk_api.app import create_app
from tests.helpers import FakeChainProvider, make_test_settings


@pytest.mark.asyncio
async def test_health_does_not_require_rpc() -> None:
    provider = FakeChainProvider(unavailable=True)
    app = create_app(settings=make_test_settings(), provider=provider)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "onchain-risk-api",
        "version": "0.1.0",
    }
