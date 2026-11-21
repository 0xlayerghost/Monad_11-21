from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from onchain_risk_api.app import create_app
from tests.helpers import FakeChainProvider, make_test_settings


@pytest.fixture
def static_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("export {};", encoding="utf-8")
    (tmp_path / "index.html").write_text(
        '<!doctype html><title>链上手记</title>'
        '<script type="module" src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    monkeypatch.setattr("onchain_risk_api.app.STATIC_DIRECTORY", tmp_path)
    monkeypatch.setattr("onchain_risk_api.web.routes.STATIC_DIRECTORY", tmp_path)
    return tmp_path


@pytest.mark.asyncio
async def test_root_serves_build_without_rpc_or_model_credentials(static_site: Path) -> None:
    chain = FakeChainProvider(unavailable=True)
    app = create_app(settings=make_test_settings(), provider=chain)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "链上手记" in response.text
        assert "text/html" in response.headers["content-type"]
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-cache"
        assert (await client.get("/assets/app.js")).status_code == 200
    assert chain.chain_calls == 0


@pytest.mark.asyncio
async def test_api_works_and_root_explains_missing_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "not-built"
    monkeypatch.setattr("onchain_risk_api.app.STATIC_DIRECTORY", directory)
    monkeypatch.setattr("onchain_risk_api.web.routes.STATIC_DIRECTORY", directory)
    app = create_app(settings=make_test_settings(), provider=FakeChainProvider())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 503
        assert "npm run build" in response.text
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/v1/ui/config")).status_code == 200
        assert (await client.get("/assets/missing.js")).status_code == 404


@pytest.mark.asyncio
async def test_ui_configuration_is_sanitized_and_network_independent() -> None:
    settings = make_test_settings(
        network_name="bsc-testnet", expected_chain_id=97,
        native_symbol="tBNB", native_decimals=18, rpc_provider_name="test-node",
    )
    chain = FakeChainProvider(unavailable=True)
    app = create_app(settings=settings, provider=chain)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/ui/config")
    assert response.status_code == 200
    assert response.json() == {
        "networkName": "bsc-testnet", "expectedChainId": 97,
        "nativeSymbol": "tBNB", "nativeDecimals": 18, "provider": "test-node",
    }
    assert "rpc_url" not in response.text
    assert "example.invalid" not in response.text
    assert chain.chain_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/assets/.env", "/assets/../core/config.py", "/assets/missing.js",
    "/assets/%2e%2e/index.html",
])
async def test_frontend_cannot_serve_config_or_arbitrary_source_files(
    path: str, static_site: Path,
) -> None:
    app = create_app(settings=make_test_settings(), provider=FakeChainProvider())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 404
