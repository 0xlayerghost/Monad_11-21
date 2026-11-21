import pytest
from httpx import ASGITransport, AsyncClient

from onchain_risk_api.app import create_app
from onchain_risk_api.llm.models import AgentResult, TraceEvent
from tests.helpers import FakeChainProvider, make_test_settings


class FakeInvestigationRunner:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def run(self, prompt: str) -> AgentResult:
        self.prompts.append(prompt)
        return AgentResult(
            status="completed",
            stop_reason="ANSWER",
            answer="Read-only investigation completed.",
            model_calls=2,
            tool_calls=1,
            input_tokens=100,
            output_tokens=20,
            trace=[TraceEvent(step=1, kind="model")],
        )


@pytest.mark.asyncio
async def test_investigation_api_reuses_the_bounded_runner() -> None:
    app = create_app(settings=make_test_settings(), provider=FakeChainProvider())
    runner = FakeInvestigationRunner()
    app.state.investigation_runner = runner

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/investigations", json={"prompt": "Inspect address"})

    assert response.status_code == 200
    assert runner.prompts == ["Inspect address"]
    assert response.json() == {
        "status": "completed",
        "stopReason": "ANSWER",
        "answer": "Read-only investigation completed.",
        "answerIsModelGenerated": True,
        "modelCalls": 2,
        "toolCalls": 1,
        "inputTokens": 100,
        "outputTokens": 20,
        "trace": [{
            "step": 1,
            "kind": "model",
            "callId": None,
            "toolName": None,
            "result": None,
        }],
        "error": None,
    }


@pytest.mark.asyncio
async def test_investigation_api_reports_missing_server_configuration() -> None:
    app = create_app(settings=make_test_settings(), provider=FakeChainProvider())
    app.state.investigation_runner = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/investigations", json={"prompt": "Inspect"})

    assert response.status_code == 200
    assert response.json()["stopReason"] == "LLM_NOT_CONFIGURED"
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_investigation_api_validates_prompt_length() -> None:
    app = create_app(settings=make_test_settings(), provider=FakeChainProvider())
    app.state.investigation_runner = FakeInvestigationRunner()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/v1/investigations", json={"prompt": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
