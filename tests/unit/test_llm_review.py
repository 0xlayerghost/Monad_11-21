import json
from pathlib import Path

import httpx
import pytest

from onchain_risk_api.core.config import Settings
from onchain_risk_api.llm import review
from onchain_risk_api.llm.config import LlmSettings
from onchain_risk_api.llm.evidence import EvidenceRecorder
from onchain_risk_api.llm.models import AgentResult, TraceEvent
from tests.helpers import make_test_settings
from tests.unit.test_llm import make_llm_settings


def write_record(directory: Path, name: str = "record.json", **updates) -> Path:
    recorder = EvidenceRecorder(scenario_id="S01", prompt="private prompt")
    recorder.configure_model(make_llm_settings())
    recorder.configure_network(make_test_settings())
    result = AgentResult(
        status="completed", stop_reason="ANSWER", answer="private answer",
        model_calls=1, input_tokens=12, output_tokens=3,
        trace=[TraceEvent(step=1, kind="model")],
    )
    record = json.loads(recorder.serialize(result))
    record.update(updates)
    destination = directory / name
    destination.write_text(json.dumps(record), encoding="utf-8")
    return destination


def change_record(path: Path, field: str, value) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    target = record
    parts = field.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    path.write_text(json.dumps(record), encoding="utf-8")


def test_empty_directory_reports_all_twenty_scenarios_missing(tmp_path) -> None:
    report = review.summarize_directory(tmp_path)
    assert report.files_scanned == report.valid_files == report.invalid_files == 0
    assert report.missing_scenario_ids == [f"S{number:02}" for number in range(1, 21)]
    assert len(report.scenarios) == 20
    assert report.facts_verified_automatically is False


def test_completed_record_remains_pending_and_input_is_unchanged(tmp_path) -> None:
    source = write_record(tmp_path)
    original = source.read_bytes()
    report = review.summarize_directory(tmp_path)
    assert report.valid_files == 1
    assert report.invalid_files == 0
    assert report.review_counts == {"pending": 1, "pass": 0, "fail": 0, "not_applicable": 0}
    assert report.execution_counts == {"completed": 1, "stopped": 0, "error": 0}
    assert (report.input_tokens, report.output_tokens) == (12, 3)
    assert (report.model_calls, report.tool_calls) == (1, 0)
    assert report.scenarios[0].attempts == 1
    assert report.records[0].review_status == "pending"
    assert source.read_bytes() == original


def test_duplicate_attempts_do_not_inflate_scenario_coverage(tmp_path) -> None:
    write_record(tmp_path, "first.json")
    second = write_record(tmp_path, "second.json")
    change_record(second, "review.factCheck", "pass")
    report = review.summarize_directory(tmp_path)
    assert report.files_scanned == report.valid_files == 2
    assert report.scenarios[0].attempts == 2
    assert report.scenarios[0].review_counts["pass"] == 1
    assert len(report.missing_scenario_ids) == 19
    assert report.review_counts["pending"] == report.review_counts["pass"] == 1


@pytest.mark.parametrize("status", ["pending", "pass", "fail", "not_applicable"])
def test_manual_review_status_is_reported_without_reinterpretation(tmp_path, status) -> None:
    source = write_record(tmp_path)
    change_record(source, "review.factCheck", status)
    report = review.summarize_directory(tmp_path)
    assert report.review_counts[status] == 1
    assert report.valid_files == 1


@pytest.mark.parametrize("status", ["stopped", "error"])
def test_noncompleted_runs_are_preserved_not_retried(tmp_path, status) -> None:
    source = write_record(tmp_path)
    change_record(source, "result.status", status)
    change_record(source, "result.answer", None)
    change_record(source, "result.stopReason", "RUN_TIMEOUT")
    if status == "error":
        change_record(source, "result.error", {"code": "LLM_TIMEOUT", "message": "private"})
    report = review.summarize_directory(tmp_path)
    assert report.execution_counts[status] == 1
    assert report.review_counts["pending"] == 1


@pytest.mark.parametrize(("field", "value", "issue"), [
    ("schemaVersion", 2, "INVALID_EVIDENCE"),
    ("schemaVersion", True, "INVALID_EVIDENCE"),
    ("scenarioId", "S99", "INVALID_EVIDENCE"),
    ("result.inputTokens", "12", "INVALID_EVIDENCE"),
    ("result.outputTokens", -1, "INVALID_COUNTERS"),
    ("result.modelCalls", 2, "TRACE_COUNT_MISMATCH"),
    ("result.toolCalls", 1, "TRACE_COUNT_MISMATCH"),
    ("finishedAt", "2000-01-01T00:00:00Z", "INVALID_TIME_RANGE"),
    ("startedAt", "2026-01-01T00:00:00", "INVALID_TIME_RANGE"),
    ("network", "base-mainnet", "NETWORK_MISMATCH"),
    ("expectedChainId", 8453, "NETWORK_MISMATCH"),
    ("result.answer", None, "INVALID_EXECUTION_STATE"),
    ("review.factCheck", "approved", "INVALID_EVIDENCE"),
])
def test_invalid_records_are_flagged_and_excluded_from_totals(
    tmp_path, field, value, issue,
) -> None:
    source = write_record(tmp_path)
    change_record(source, field, value)
    report = review.summarize_directory(tmp_path)
    assert report.invalid_files == 1
    assert report.valid_files == report.input_tokens == report.output_tokens == 0
    assert issue in report.records[0].issues
    assert len(report.missing_scenario_ids) == 20


@pytest.mark.parametrize("field", ["schemaVersion", "result", "review"])
def test_required_record_fields_cannot_silently_use_defaults(tmp_path, field) -> None:
    source = write_record(tmp_path)
    record = json.loads(source.read_text(encoding="utf-8"))
    record.pop(field)
    source.write_text(json.dumps(record), encoding="utf-8")
    report = review.summarize_directory(tmp_path)
    assert report.invalid_files == 1
    assert report.records[0].issues == ["INVALID_EVIDENCE"]


def test_corrupt_file_does_not_hide_valid_records_or_leak_content(tmp_path) -> None:
    write_record(tmp_path, "good.json")
    (tmp_path / "secret-file-name.json").write_text('{"secret-key":', encoding="utf-8")
    report = review.summarize_directory(tmp_path)
    output = report.model_dump_json(by_alias=True)
    assert report.valid_files == report.invalid_files == 1
    assert "secret" not in output
    assert "private" not in output
    assert "test-key" not in output
    assert "record.json" not in output


def test_oversized_files_are_not_parsed(tmp_path, monkeypatch) -> None:
    write_record(tmp_path)
    monkeypatch.setattr(review, "MAX_EVIDENCE_BYTES", 8)
    report = review.summarize_directory(tmp_path)
    assert report.records[0].issues == ["FILE_TOO_LARGE"]


def test_report_scans_only_immediate_json_files(tmp_path) -> None:
    write_record(tmp_path, "record.JSON")
    (tmp_path / "notes.txt").write_text("not evidence", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    write_record(nested)
    assert review.summarize_directory(tmp_path).files_scanned == 1


def test_cli_does_not_read_env_or_construct_network_clients(tmp_path, monkeypatch, capsys) -> None:
    write_record(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline summary must not load settings or create HTTP clients")

    monkeypatch.setattr(Settings, "__init__", forbidden)
    monkeypatch.setattr(LlmSettings, "__init__", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_bytes(b"\xff\xfe\x00invalid settings")
    assert review.main(["."]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["validFiles"] == 1
    assert report["factsVerifiedAutomatically"] is False


def test_cli_invalid_evidence_returns_one_and_keeps_json_report(tmp_path, capsys) -> None:
    (tmp_path / "broken.json").write_text("", encoding="utf-8")
    assert review.main([str(tmp_path)]) == 1
    assert json.loads(capsys.readouterr().out)["invalidFiles"] == 1


def test_cli_missing_directory_is_sanitized(tmp_path, capsys) -> None:
    assert review.main([str(tmp_path / "secret-path")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "EVIDENCE_DIRECTORY_UNAVAILABLE" in captured.err
    assert "secret" not in captured.err


def test_directory_file_limit_prevents_partial_inventory(tmp_path, monkeypatch, capsys) -> None:
    write_record(tmp_path, "first.json")
    write_record(tmp_path, "second.json")
    monkeypatch.setattr(review, "MAX_EVIDENCE_FILES", 1)
    assert review.main([str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "TOO_MANY_EVIDENCE_FILES" in captured.err


def test_manual_pass_with_unsupported_claims_is_a_review_conflict(tmp_path) -> None:
    source = write_record(tmp_path)
    change_record(source, "review.factCheck", "pass")
    change_record(source, "review.unsupportedClaims", ["private unverified assertion"])
    report = review.summarize_directory(tmp_path)
    assert report.records[0].issues == ["REVIEW_CONFLICT"]
    assert report.review_counts["pass"] == 0
    assert "private" not in report.model_dump_json()


def test_tool_event_requires_result_and_call_id(tmp_path) -> None:
    source = write_record(tmp_path)
    change_record(source, "result.toolCalls", 1)
    change_record(source, "result.trace", [
        {"step": 1, "kind": "model"},
        {"step": 1, "kind": "tool", "toolName": "get_native_balance"},
    ])
    report = review.summarize_directory(tmp_path)
    assert report.records[0].issues == ["INVALID_TOOL_TRACE"]


@pytest.mark.parametrize("wrong_network", [False, True])
def test_real_fixture_shape_is_checked_for_tool_network_consistency(
    tmp_path, wrong_network,
) -> None:
    source = write_record(tmp_path)
    fixture = Path(__file__).parents[1] / "fixtures" / "base_sepolia_receipt.json"
    tool_result = json.loads(fixture.read_text(encoding="utf-8"))
    if wrong_network:
        tool_result["data"]["chainId"] = 8453
    change_record(source, "result.toolCalls", 1)
    change_record(source, "result.trace", [
        {"step": 1, "kind": "model"},
        {"step": 1, "kind": "tool", "callId": "call_receipt",
         "toolName": "get_transaction_receipt", "result": tool_result},
    ])
    report = review.summarize_directory(tmp_path)
    if wrong_network:
        assert report.records[0].issues == ["NETWORK_MISMATCH"]
    else:
        assert report.valid_files == 1
        assert report.tool_calls == 1


def test_unreadable_evidence_is_reported_without_exception_text(tmp_path, monkeypatch) -> None:
    source = write_record(tmp_path)
    original_open = Path.open

    def failing_open(path, *args, **kwargs):
        if path == source:
            raise PermissionError("secret credentials and endpoint")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    report = review.summarize_directory(tmp_path)
    assert report.records[0].issues == ["EVIDENCE_READ_FAILED"]
    assert "secret" not in report.model_dump_json()


def test_symlink_is_rejected_without_reading_target(tmp_path, monkeypatch) -> None:
    source = write_record(tmp_path)
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path == source or original_is_symlink(path),
    )
    report = review.summarize_directory(tmp_path)
    assert report.records[0].issues == ["SYMLINK_NOT_ALLOWED"]
