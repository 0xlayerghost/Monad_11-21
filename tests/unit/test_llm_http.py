import ssl

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from onchain_risk_api.api import dependencies
from onchain_risk_api.app import create_app
from onchain_risk_api.llm.http import model_client_options
from tests.helpers import FakeChainProvider, make_test_settings
from tests.unit.test_llm import make_llm_settings, response_payload


def test_default_model_client_keeps_certifi_and_disables_environment_proxies() -> None:
    settings = make_llm_settings()
    assert settings.tls_trust_store == "certifi"
    assert model_client_options(settings) == {"trust_env": True, "verify": True}


def test_system_trust_requires_verified_certificates_and_hostnames() -> None:
    options = model_client_options(make_llm_settings(tls_trust_store="system"))
    assert options["trust_env"] is True
    context = options["verify"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.keylog_filename is None


@pytest.mark.parametrize("mode", ["false", "none", "insecure", "unknown"])
def test_invalid_tls_policy_is_rejected(mode) -> None:
    with pytest.raises(ValidationError):
        make_llm_settings(tls_trust_store=mode)


def test_tls_policy_loads_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("LLM_TLS_TRUST_STORE", "system")
    assert make_llm_settings().tls_trust_store == "system"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["certifi", "system"])
async def test_web_investigation_uses_tls_policy_and_closes_client(monkeypatch, mode) -> None:
    settings = make_llm_settings(tls_trust_store=mode)
    calls = []
    client = AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response_payload()),
    ))

    def factory(**options):
        calls.append(options)
        return client

    monkeypatch.setattr(dependencies, "LlmSettings", lambda: settings)
    monkeypatch.setattr(dependencies.httpx, "AsyncClient", factory)
    app = create_app(settings=make_test_settings(), provider=FakeChainProvider())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as web:
        response = await web.post("/v1/investigations", json={"prompt": "Explain pending."})

    assert response.json()["status"] == "completed"
    assert len(calls) == 1
    assert calls[0]["trust_env"] is True
    if mode == "system":
        assert calls[0]["verify"].verify_mode == ssl.CERT_REQUIRED
        assert calls[0]["verify"].check_hostname is True
    else:
        assert calls[0]["verify"] is True
    assert client.is_closed
