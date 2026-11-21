import io
import json
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from onchain_risk_api.app import create_app
from onchain_risk_api.core.config import Settings
from onchain_risk_api.llm import __main__ as cli
from onchain_risk_api.llm.evidence import EvidenceRecorder
from onchain_risk_api.llm.models import AgentResult
from tests.helpers import FakeChainProvider, make_test_settings
from tests.unit.test_llm import call_item, make_llm_settings, response_payload


def test_record_contains_metadata_and_requires_manual_review() -> None:
    recorder = EvidenceRecorder(scenario_id="S01", prompt="查询余额")
    recorder.configure_model(make_llm_settings())
    recorder.configure_network(make_test_settings())
    result = AgentResult(status="completed", stop_reason="ANSWER", answer="请提供地址")
    record = json.loads(recorder.serialize(result))
    assert record["schemaVersion"] == 1
    assert record["scenarioId"] == "S01"
    assert record["modelId"] == "test-model"
    assert record["network"] == "base-sepolia"
    assert record["expectedChainId"] == 84532
    assert record["prompt"] == "查询余额"
    assert record["result"] == result.model_dump(mode="json", by_alias=True)
    assert record["review"]["factCheck"] == "pending"
    assert record["review"]["providerBillingChecked"] is False
    started = datetime.fromisoformat(record["startedAt"])
    finished = datetime.fromisoformat(record["finishedAt"])
    assert started.utcoffset().total_seconds() == 0
    assert finished >= started


def test_redacts_known_credentials_in_prompt_answer_and_nested_trace() -> None:
    recorder = EvidenceRecorder(scenario_id="S17", prompt="test-key-not-real rpc-token-123")
    recorder.configure_model(make_llm_settings())
    recorder.configure_network(Settings(
        _env_file=None,
        rpc_url="https://rpc.example/v1/rpc-token-123?key=query-token-123",
    ))
    result = AgentResult(
        status="completed", stop_reason="ANSWER",
        answer="test-key-not-real https://rpc.example/v1/rpc-token-123?key=query-token-123",
    )
    serialized = recorder.serialize(result)
    for secret in ("test-key-not-real", "rpc-token-123", "query-token-123", "rpc.example"):
        assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert recorder.redact({"nested": [{"message": "query-token-123"}]}) == {
        "nested": [{"message": "[REDACTED]"}],
    }
    assert result.answer.startswith("test-key-not-real")


def test_redacts_url_encoded_credentials_without_breaking_json() -> None:
    recorder = EvidenceRecorder(scenario_id="S17", prompt='quoted"key user-password')
    recorder.configure_network(Settings(
        _env_file=None,
        rpc_url="https://user:user-password@rpc.example/quoted%22key",
    ))
    record = json.loads(recorder.serialize(AgentResult()))
    assert record["prompt"] == "[REDACTED] [REDACTED]"


@pytest.mark.parametrize("status", ["completed", "stopped", "error"])
def test_cli_saves_all_result_states_without_changing_exit_semantics(
    monkeypatch, capsys, tmp_path, status,
) -> None:
    result = AgentResult(status=status)
    investigate = AsyncMock(return_value=result)
    monkeypatch.setattr(cli, "_investigate", investigate)
    target = tmp_path / "evidence.json"
    exit_code = cli.main([
        "查询", "--scenario-id", "S01", "--save-evidence", str(target),
    ])
    assert exit_code == (0 if status == "completed" else 1)
    assert json.loads(target.read_text(encoding="utf-8"))["result"]["status"] == status
    assert json.loads(capsys.readouterr().out)["status"] == status
    assert investigate.await_args.args == ("查询",)
    assert isinstance(investigate.await_args.kwargs["evidence"], EvidenceRecorder)


def test_existing_evidence_is_not_overwritten_or_investigated(monkeypatch, capsys, tmp_path):
    investigate = AsyncMock()
    monkeypatch.setattr(cli, "_investigate", investigate)
    target = tmp_path / "evidence.json"
    target.write_text("existing evidence", encoding="utf-8")
    assert cli.main([
        "查询", "--scenario-id", "S01", "--save-evidence", str(target),
    ]) == 2
    investigate.assert_not_awaited()
    assert target.read_text(encoding="utf-8") == "existing evidence"
    assert "EVIDENCE_WRITE_FAILED" in capsys.readouterr().err


def test_missing_destination_parent_does_not_call_model(monkeypatch, capsys, tmp_path):
    investigate = AsyncMock()
    monkeypatch.setattr(cli, "_investigate", investigate)
    assert cli.main([
        "查询", "--scenario-id", "S01", "--save-evidence", str(tmp_path / "missing" / "file"),
    ]) == 2
    investigate.assert_not_awaited()
    assert "EVIDENCE_WRITE_FAILED" in capsys.readouterr().err


@pytest.mark.parametrize("arguments", [
    ["--scenario-id", "S01"], ["--save-evidence", "unused.json"],
    ["--scenario-id", "S21", "--save-evidence", "unused.json"],
])
def test_invalid_evidence_options_are_rejected_before_execution(monkeypatch, arguments):
    investigate = AsyncMock()
    monkeypatch.setattr(cli, "_investigate", investigate)
    with pytest.raises(SystemExit) as error:
        cli.main(["查询", *arguments])
    assert error.value.code == 2
    investigate.assert_not_awaited()


def test_bootstrap_failure_is_saved_without_exception_details(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "_investigate", AsyncMock(side_effect=ValueError("secret key")))
    target = tmp_path / "failure.json"
    assert cli.main([
        "查询", "--scenario-id", "S19", "--save-evidence", str(target),
    ]) == 1
    serialized = target.read_text(encoding="utf-8")
    assert "secret key" not in serialized
    record = json.loads(serialized)
    assert record["result"]["stopReason"] == "AGENT_EXECUTION_FAILED"
    assert record["modelId"] is None
    assert "secret key" not in capsys.readouterr().out


def test_cli_evidence_wiring_preserves_trace_and_closes_clients(monkeypatch, capsys, tmp_path):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        output = [call_item()] if len(requests) == 1 else None
        return httpx.Response(200, json=response_payload(output))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    chain = FakeChainProvider()
    app = create_app(settings=make_test_settings(), provider=chain)
    monkeypatch.setattr(cli, "LlmSettings", make_llm_settings)
    monkeypatch.setattr(cli, "create_app", lambda: app)
    monkeypatch.setattr(cli.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("查询余额"))
    target = tmp_path / "roundtrip.json"

    assert cli.main(["-", "--scenario-id", "S01", "--save-evidence", str(target)]) == 0

    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["prompt"] == "查询余额"
    assert record["modelId"] == "test-model"
    assert record["expectedChainId"] == 84532
    assert record["result"]["trace"][1]["result"]["data"]["blockNumber"] == 123
    assert json.loads(capsys.readouterr().out) == record["result"]
    assert len(requests) == 2
    assert chain.closed is True
    assert client.is_closed


def test_evidence_mode_also_redacts_stdout(monkeypatch, capsys, tmp_path):
    async def investigate(prompt, *, evidence):
        evidence.configure_model(make_llm_settings())
        return AgentResult(status="completed", stop_reason="ANSWER", answer="test-key-not-real")

    monkeypatch.setattr(cli, "_investigate", investigate)
    target = tmp_path / "redacted.json"
    assert cli.main([
        "查询", "--scenario-id", "S17", "--save-evidence", str(target),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["answer"] == "[REDACTED]"
    assert "test-key-not-real" not in target.read_text(encoding="utf-8")


def test_disk_write_failure_keeps_stdout_result_and_does_not_retry(monkeypatch, capsys):
    class FailingWriter(io.StringIO):
        def write(self, text):
            raise OSError("secret filesystem details")

    investigate = AsyncMock(return_value=AgentResult(status="completed", stop_reason="ANSWER"))
    monkeypatch.setattr(cli, "_investigate", investigate)
    monkeypatch.setattr(cli.Path, "open", lambda *args, **kwargs: FailingWriter())

    assert cli.main([
        "查询", "--scenario-id", "S01", "--save-evidence", "unused.json",
    ]) == 2

    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "completed"
    assert "EVIDENCE_WRITE_FAILED" in output.err
    assert "secret filesystem details" not in output.err
    investigate.assert_awaited_once()
