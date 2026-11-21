import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from onchain_risk_api.domain.models import ApiModel, Erc20AllowanceResponse, Erc20BalanceResponse
from onchain_risk_api.llm.evidence import EvidenceReview, InvestigationEvidence
from onchain_risk_api.llm.models import AgentResult

MAX_EVIDENCE_BYTES = 2_000_000
MAX_EVIDENCE_FILES = 200
SCENARIO_IDS = tuple(f"S{number:02}" for number in range(1, 21))
ReviewStatus = Literal["pending", "pass", "fail", "not_applicable"]
ExecutionStatus = Literal["completed", "stopped", "error"]


def _review_counts() -> dict[str, int]:
    return dict.fromkeys(("pending", "pass", "fail", "not_applicable"), 0)


def _execution_counts() -> dict[str, int]:
    return dict.fromkeys(("completed", "stopped", "error"), 0)


class RecordSummary(ApiModel):
    file_index: int
    scenario_id: str | None = None
    execution_status: ExecutionStatus | None = None
    review_status: ReviewStatus | None = None
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    issues: list[str] = Field(default_factory=list)


class ScenarioSummary(ApiModel):
    scenario_id: str
    attempts: int = 0
    review_counts: dict[str, int] = Field(default_factory=_review_counts)
    execution_counts: dict[str, int] = Field(default_factory=_execution_counts)


class EvidenceSummary(ApiModel):
    schema_version: Literal[1] = 1
    facts_verified_automatically: Literal[False] = False
    files_scanned: int = 0
    valid_files: int = 0
    invalid_files: int = 0
    review_counts: dict[str, int] = Field(default_factory=_review_counts)
    execution_counts: dict[str, int] = Field(default_factory=_execution_counts)
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    missing_scenario_ids: list[str] = Field(default_factory=list)
    scenarios: list[ScenarioSummary] = Field(default_factory=list)
    records: list[RecordSummary] = Field(default_factory=list)


class EvidenceDirectoryError(Exception):
    pass


def _record_issues(record: InvestigationEvidence) -> list[str]:
    result = record.result
    if (
        record.model_fields_set != set(InvestigationEvidence.model_fields)
        or result.model_fields_set != set(AgentResult.model_fields)
        or record.review.model_fields_set != set(EvidenceReview.model_fields)
    ):
        return ["INVALID_EVIDENCE"]
    issues = []
    if min(result.model_calls, result.tool_calls, result.input_tokens, result.output_tokens) < 0:
        issues.append("INVALID_COUNTERS")
    if (
        result.model_calls != sum(event.kind == "model" for event in result.trace)
        or result.tool_calls != sum(event.kind == "tool" for event in result.trace)
    ):
        issues.append("TRACE_COUNT_MISMATCH")
    if any(
        event.kind == "tool" and (
            not event.call_id or event.result is None
            or event.tool_name != event.result.tool_name
        )
        for event in result.trace
    ):
        issues.append("INVALID_TOOL_TRACE")
    if (
        record.started_at.utcoffset() is None or record.finished_at.utcoffset() is None
        or record.finished_at < record.started_at
    ):
        issues.append("INVALID_TIME_RANGE")
    if (
        record.network not in {None, "base-sepolia"}
        or record.expected_chain_id not in {None, 84532}
        or any(
            event.result is not None and event.result.data is not None
            and (
                (event.result.data.evidence.network != "base-sepolia"
                 or event.result.data.evidence.chain_id != 84532)
                if isinstance(event.result.data, (Erc20AllowanceResponse, Erc20BalanceResponse))
                else (event.result.data.network != "base-sepolia"
                      or event.result.data.chain_id != 84532)
            )
            for event in result.trace
        )
    ):
        issues.append("NETWORK_MISMATCH")
    if (
        result.status == "completed"
        and (not result.answer or not result.answer.strip()
             or result.stop_reason != "ANSWER" or result.error is not None)
        or result.status == "error" and (result.error is None or result.answer is not None)
        or result.status == "stopped" and (result.error is not None or result.answer is not None)
    ):
        issues.append("INVALID_EXECUTION_STATE")
    if record.review.fact_check == "pass" and record.review.unsupported_claims:
        issues.append("REVIEW_CONFLICT")
    return issues


def _summarize_record(path: Path, file_index: int) -> RecordSummary:
    summary = RecordSummary(file_index=file_index)
    try:
        if path.is_symlink():
            summary.issues = ["SYMLINK_NOT_ALLOWED"]
            return summary
        with path.open("rb") as stream:
            payload = stream.read(MAX_EVIDENCE_BYTES + 1)
    except OSError:
        summary.issues = ["EVIDENCE_READ_FAILED"]
        return summary
    if len(payload) > MAX_EVIDENCE_BYTES:
        summary.issues = ["FILE_TOO_LARGE"]
        return summary
    try:
        record = InvestigationEvidence.model_validate_json(payload, strict=True)
    except (ValidationError, ValueError, RecursionError):
        summary.issues = ["INVALID_EVIDENCE"]
        return summary
    summary.issues = _record_issues(record)
    if not summary.issues:
        summary.scenario_id = record.scenario_id
        summary.execution_status = record.result.status
        summary.review_status = record.review.fact_check
        summary.model_calls = record.result.model_calls
        summary.tool_calls = record.result.tool_calls
        summary.input_tokens = record.result.input_tokens
        summary.output_tokens = record.result.output_tokens
    return summary


def summarize_directory(directory: Path) -> EvidenceSummary:
    paths = []
    try:
        for path in directory.iterdir():
            if path.suffix.lower() == ".json" and not path.is_dir():
                paths.append(path)
                if len(paths) > MAX_EVIDENCE_FILES:
                    raise EvidenceDirectoryError("TOO_MANY_EVIDENCE_FILES")
    except OSError:
        raise EvidenceDirectoryError("EVIDENCE_DIRECTORY_UNAVAILABLE") from None
    scenarios = {scenario: ScenarioSummary(scenario_id=scenario) for scenario in SCENARIO_IDS}
    report = EvidenceSummary(scenarios=list(scenarios.values()), files_scanned=len(paths))
    for file_index, path in enumerate(sorted(paths), start=1):
        record = _summarize_record(path, file_index)
        report.records.append(record)
        if record.issues:
            report.invalid_files += 1
            continue
        report.valid_files += 1
        report.model_calls += record.model_calls
        report.tool_calls += record.tool_calls
        report.input_tokens += record.input_tokens
        report.output_tokens += record.output_tokens
        report.review_counts[record.review_status] += 1
        report.execution_counts[record.execution_status] += 1
        scenario = scenarios[record.scenario_id]
        scenario.attempts += 1
        scenario.review_counts[record.review_status] += 1
        scenario.execution_counts[record.execution_status] += 1
    report.missing_scenario_ids = [
        scenario.scenario_id for scenario in report.scenarios if scenario.attempts == 0
    ]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize local evidence without API calls.")
    parser.add_argument("directory", type=Path, help="Read immediate JSON evidence files only.")
    args = parser.parse_args(argv)
    try:
        report = summarize_directory(args.directory)
    except EvidenceDirectoryError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(report.model_dump_json(by_alias=True, indent=2))
    return 1 if report.invalid_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
