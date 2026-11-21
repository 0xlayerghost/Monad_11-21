import json
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from onchain_risk_api import allowance_snapshot as cli
from onchain_risk_api.domain.errors import RpcUnavailableError
from onchain_risk_api.tools.models import Erc20AllowanceArguments
from tests.helpers import FakeChainProvider, make_test_settings
from tests.unit.test_allowance_tools import ARGUMENTS, OWNER, SPENDER, TOKEN


def capture_settings():
    return make_test_settings().model_copy(update={
        "erc20_allowed_tokens": [TOKEN], "erc20_allowed_spenders": [SPENDER],
    })


@pytest.fixture
async def snapshot(monkeypatch):
    chain = FakeChainProvider()
    chain.get_erc20_allowance = AsyncMock(return_value=2**256 - 1)
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: chain)
    return await cli.capture_snapshot(
        capture_settings(), Erc20AllowanceArguments(**ARGUMENTS)
    )


def reference_for(snapshot, **updates):
    values = snapshot.first.evidence.model_dump(include=set(cli.SNAPSHOT_FIELDS))
    values.update(source_label="Independent fixed-block read", observed_at=(
        snapshot.repeated.evidence.observed_at
    ))
    values.update(updates)
    return cli.AllowanceReference.model_validate(values)


@pytest.mark.asyncio
@pytest.mark.parametrize("height", [None, 0, 123])
async def test_capture_pins_repeat_and_closes_provider(monkeypatch, height):
    chain = FakeChainProvider()
    if height == 0:
        chain.block = chain.block.model_copy(update={"number": 0})
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: chain)
    result = await cli.capture_snapshot(
        capture_settings(), Erc20AllowanceArguments(**{**ARGUMENTS, "block_number": height})
    )
    assert chain.block_requests == [height if height is not None else "latest"] + [
        chain.block.number
    ] * 3
    assert result.first.evidence.evidence_id == result.repeated.evidence.evidence_id
    assert result.independent_source_verified is False
    assert chain.closed is True


@pytest.mark.asyncio
async def test_failed_capture_closes_provider_and_preserves_failure(monkeypatch):
    chain = FakeChainProvider(unavailable=True)
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: chain)
    with pytest.raises(RpcUnavailableError):
        await cli.capture_snapshot(capture_settings(), Erc20AllowanceArguments(**ARGUMENTS))
    assert chain.closed is True


@pytest.mark.asyncio
async def test_wrong_network_is_rejected_before_provider_creation(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("Must reject before constructing a provider.")

    monkeypatch.setattr(cli, "Web3RpcProvider", fail)
    settings = capture_settings().model_copy(update={"expected_chain_id": 8453})
    with pytest.raises(ValueError):
        await cli.capture_snapshot(settings, Erc20AllowanceArguments(**ARGUMENTS))


@pytest.mark.asyncio
async def test_snapshot_schema_detects_tampered_identity_rules_and_time(snapshot):
    original = snapshot.model_dump(mode="json", by_alias=True)
    for field, value in [
        ("schemaVersion", True), ("schemaVersion", 2), ("independentSourceVerified", True),
    ]:
        with pytest.raises(ValidationError):
            cli.AllowanceSnapshot.model_validate({**original, field: value})
    for field, value in [
        ("evidenceId", "evidence:" + "00" * 32),
        ("allowanceSmallestUnit", "1"), ("chainId", 8453),
    ]:
        changed = json.loads(json.dumps(original))
        changed["first"]["evidence"][field] = value
        with pytest.raises(ValidationError):
            cli.AllowanceSnapshot.model_validate(changed)
    for field, value in [("findings", []), ("limitations", [])]:
        changed = json.loads(json.dumps(original))
        changed["first"][field] = value
        with pytest.raises(ValidationError):
            cli.AllowanceSnapshot.model_validate(changed)
    changed = json.loads(json.dumps(original))
    changed["repeated"]["evidence"]["observedAt"] = (
        snapshot.first.evidence.observed_at - timedelta(seconds=1)
    ).isoformat()
    with pytest.raises(ValidationError):
        cli.AllowanceSnapshot.model_validate(changed)


@pytest.mark.asyncio
async def test_repeat_must_match_all_snapshot_fields(snapshot):
    changed = snapshot.model_dump(mode="json", by_alias=True)
    changed["repeated"]["evidence"]["blockTimestamp"] = (
        snapshot.first.evidence.block_timestamp + timedelta(seconds=1)
    ).isoformat()
    with pytest.raises(ValidationError):
        cli.AllowanceSnapshot.model_validate(changed)


@pytest.mark.asyncio
async def test_matching_reference_never_claims_independent_verification(snapshot):
    report = cli.compare_reference(snapshot, reference_for(snapshot))
    assert report == {
        "status": "matched", "mismatchedFields": [], "fieldsCompared": 9,
        "independentSourceVerified": False, "reviewRequired": True,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value", "alias"), [
    ("token_address", OWNER, "tokenAddress"),
    ("owner_address", TOKEN, "ownerAddress"),
    ("spender_address", TOKEN, "spenderAddress"),
    ("block_number", 124, "blockNumber"),
    ("block_hash", "0x" + "ef" * 32, "blockHash"),
    ("allowance_smallest_unit", "0", "allowanceSmallestUnit"),
])
async def test_reference_mismatch_is_reported_without_values(snapshot, field, value, alias):
    report = cli.compare_reference(snapshot, reference_for(snapshot, **{field: value}))
    assert report["status"] == "mismatch"
    assert report["mismatchedFields"] == [alias]
    assert "secret" not in json.dumps(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"allowance_smallest_unit": str(2**256)}, {"allowance_smallest_unit": 1},
    {"chain_id": 8453}, {"source_label": "https://secret.invalid/?key=secret"},
    {"source_label": " "}, {"block_number": True}, {"rpc_url": "secret"},
])
async def test_invalid_reference_is_rejected(snapshot, updates):
    with pytest.raises(ValidationError):
        reference_for(snapshot, **updates)


@pytest.mark.asyncio
@pytest.mark.parametrize("matches", [False, True])
async def test_check_cli_is_offline_and_reports_real_comparison(
    tmp_path, monkeypatch, capsys, snapshot, matches,
):
    candidate = tmp_path / "candidate.json"
    reference = tmp_path / "reference.json"
    candidate.write_text(snapshot.model_dump_json(by_alias=True), encoding="utf-8")
    values = {} if matches else {"allowance_smallest_unit": "0"}
    reference.write_text(reference_for(snapshot, **values).model_dump_json(), encoding="utf-8")

    def fail(**kwargs):
        raise AssertionError("Offline check cannot load configuration or construct a provider.")

    monkeypatch.setattr(cli, "Settings", fail)
    monkeypatch.setattr(cli, "Web3RpcProvider", fail)
    assert cli.main(["check", str(candidate), "--reference", str(reference)]) == (
        0 if matches else 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == ("matched" if matches else "mismatch")
    assert report["independentSourceVerified"] is False


@pytest.mark.asyncio
async def test_windows_utf8_bom_is_supported(tmp_path, snapshot):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(snapshot.model_dump_json(by_alias=True), encoding="utf-8-sig")
    assert cli._load(candidate, cli.AllowanceSnapshot) == snapshot


def capture_arguments(path):
    return [
        "capture", "--token", TOKEN, "--owner", OWNER, "--spender", SPENDER,
        "--output", str(path),
    ]


def test_capture_cli_refuses_overwrite_before_loading_env(tmp_path, monkeypatch, capsys):
    destination = tmp_path / "existing.json"
    destination.write_text("original", encoding="utf-8")

    def fail():
        raise AssertionError("Do not load .env for an existing output path.")

    monkeypatch.setattr(cli, "Settings", fail)
    assert cli.main(capture_arguments(destination)) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "SNAPSHOT_FILE_ERROR"
    assert destination.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("failure", [False, True])
def test_capture_cli_writes_only_success_and_never_exposes_endpoints(
    tmp_path, monkeypatch, capsys, failure,
):
    chain = FakeChainProvider(unavailable=failure)
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: chain)
    monkeypatch.setattr(cli, "Settings", capture_settings)
    destination = tmp_path / "capture.json"
    assert cli.main(capture_arguments(destination)) == (2 if failure else 0)
    output = capsys.readouterr().out
    assert "test-rpc-endpoint" not in output
    assert destination.exists() is not failure
    assert chain.closed is True
    if not failure:
        record = cli.AllowanceSnapshot.model_validate_json(destination.read_bytes())
        assert record.independent_source_verified is False
        assert "test-rpc-endpoint" not in destination.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content", ["not JSON secret", "{}", "a" * (cli.MAX_FILE_BYTES + 1)],
    ids=["invalid-json", "missing-fields", "oversized"],
)
def test_check_cli_rejects_invalid_or_oversized_files_without_echoing_them(
    tmp_path, capsys, content,
):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(content, encoding="utf-8")
    assert cli.main(["check", str(candidate), "--reference", str(candidate)]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INVALID_SNAPSHOT_INPUT"
