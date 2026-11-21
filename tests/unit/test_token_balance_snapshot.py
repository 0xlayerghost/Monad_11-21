import json
from datetime import timedelta
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from onchain_risk_api import token_balance_snapshot as cli
from onchain_risk_api.domain.errors import RpcUnavailableError, TokenCallFailedError
from onchain_risk_api.tools.models import Erc20BalanceArguments
from tests.helpers import FakeChainProvider, make_test_settings
from tests.unit.test_token_balance import ARGUMENTS, OWNER, TOKEN


def capture_settings(**updates):
    return make_test_settings().model_copy(update={
        "erc20_allowed_tokens": [TOKEN], "erc20_allowed_spenders": [], **updates,
    })


def fake_provider():
    provider = FakeChainProvider()
    provider.get_erc20_balance = AsyncMock(return_value=10**30 + 1)
    provider.get_erc20_decimals = AsyncMock(return_value=6)
    return provider


@pytest.fixture
async def snapshot(monkeypatch):
    provider = fake_provider()
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: provider)
    return await cli.capture_snapshot(capture_settings(), Erc20BalanceArguments(**ARGUMENTS))


def reference_for(snapshot, **updates):
    values = snapshot.first.evidence.model_dump(include=set(cli.SNAPSHOT_FIELDS))
    values.update(source_label="Independent fixed-block read", observed_at=(
        snapshot.repeated.evidence.observed_at
    ))
    values.update(updates)
    return cli.TokenBalanceReference.model_validate(values)


@pytest.mark.asyncio
@pytest.mark.parametrize("height", [None, 0, 123])
async def test_capture_pins_repeat_closes_provider_and_preserves_original_identity(
    monkeypatch, height,
):
    provider = fake_provider()
    if height == 0:
        provider.block = provider.block.model_copy(update={"number": 0})
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: provider)
    result = await cli.capture_snapshot(capture_settings(), Erc20BalanceArguments(
        **ARGUMENTS, block_number=height,
    ))
    evidence = result.first.evidence
    assert provider.block_requests == [
        "latest" if height is None else height, evidence.block_number,
        evidence.block_number, evidence.block_number,
    ]
    assert provider.closed is True
    assert provider.get_erc20_balance.await_count == 2
    assert provider.get_erc20_decimals.await_count == 2
    assert result.independent_source_verified is False
    original_identity = json.dumps([
        "erc20-balance", "v1", 84532, evidence.block_number, evidence.block_hash.lower(),
        TOKEN.lower(), OWNER.lower(), str(10**30 + 1), 6,
    ], separators=(",", ":"))
    assert evidence.evidence_id == "evidence:" + sha256(original_identity.encode()).hexdigest()
    assert result.repeated.evidence.evidence_id == evidence.evidence_id


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_erc20_balance", "get_chain_id"])
async def test_query_failure_closes_provider(monkeypatch, method):
    provider = fake_provider()
    setattr(provider, method, AsyncMock(side_effect=RpcUnavailableError(provider_name="test")))
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: provider)
    with pytest.raises(RpcUnavailableError):
        await cli.capture_snapshot(capture_settings(), Erc20BalanceArguments(**ARGUMENTS))
    assert provider.closed is True


@pytest.mark.asyncio
async def test_wrong_configured_network_does_not_construct_provider(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("No RPC for wrong network.")

    monkeypatch.setattr(cli, "Web3RpcProvider", fail)
    with pytest.raises(ValueError):
        await cli.capture_snapshot(
            capture_settings(network_name="other"), Erc20BalanceArguments(**ARGUMENTS),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["balance", "decimals", "metadata"])
async def test_changed_repeated_read_is_not_captured(monkeypatch, field):
    provider = fake_provider()
    if field == "balance":
        provider.get_erc20_balance.side_effect = [1, 2]
    elif field == "decimals":
        provider.get_erc20_decimals.side_effect = [6, 18]
    else:
        provider.get_erc20_decimals.side_effect = [TokenCallFailedError(), 6]
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: provider)
    with pytest.raises(ValidationError):
        await cli.capture_snapshot(capture_settings(), Erc20BalanceArguments(**ARGUMENTS))
    assert provider.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", ["id", "hash", "time", "limitations", "flag", "formatted"])
async def test_snapshot_tampering_is_rejected(snapshot, tamper):
    values = snapshot.model_dump()
    if tamper == "id":
        values["first"]["evidence"]["evidence_id"] = "evidence:" + "00" * 32
    elif tamper == "hash":
        values["repeated"]["evidence"]["block_hash"] = "0x" + "cd" * 32
    elif tamper == "time":
        values["repeated"]["evidence"]["observed_at"] = (
            snapshot.first.evidence.observed_at - timedelta(seconds=1)
        )
    elif tamper == "limitations":
        values["first"]["limitations"] = []
    elif tamper == "flag":
        values["independent_source_verified"] = True
    else:
        values["first"]["evidence"]["balance_formatted"] = "1.0"
    with pytest.raises(ValidationError):
        cli.TokenBalanceSnapshot.model_validate(values)


@pytest.mark.asyncio
async def test_missing_metadata_is_preserved_but_cannot_fully_match_known_reference(monkeypatch):
    provider = fake_provider()
    provider.get_erc20_decimals.side_effect = TokenCallFailedError()
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: provider)
    result = await cli.capture_snapshot(capture_settings(), Erc20BalanceArguments(**ARGUMENTS))
    assert result.first.evidence.decimals is None
    assert result.first.evidence.balance_formatted is None
    report = cli.compare_reference(result, reference_for(result, decimals=6))
    assert report["status"] == "mismatch"
    assert report["mismatchedFields"] == ["decimals"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value", "alias"), [
    ("token_address", "0x" + "44" * 20, "tokenAddress"),
    ("owner_address", "0x" + "44" * 20, "ownerAddress"),
    ("block_number", 124, "blockNumber"),
    ("block_hash", "0x" + "cd" * 32, "blockHash"),
    ("balance_smallest_unit", "0", "balanceSmallestUnit"),
    ("decimals", 18, "decimals"),
])
async def test_reference_mismatch_reports_only_field_names(snapshot, field, value, alias):
    report = cli.compare_reference(snapshot, reference_for(snapshot, **{field: value}))
    assert report["status"] == "mismatch"
    assert report["mismatchedFields"] == [alias]
    assert report["fieldsCompared"] == 9
    assert report["independentSourceVerified"] is False
    assert report["reviewRequired"] is True
    assert value not in report.values()


@pytest.mark.asyncio
@pytest.mark.parametrize("updates", [
    {"balance_smallest_unit": str(2**256)}, {"balance_smallest_unit": 1},
    {"decimals": None}, {"decimals": True}, {"decimals": 256},
    {"source_label": "https://secret.invalid/key"}, {"source_label": " "},
    {"rpc_url": "secret"}, {"chain_id": 1}, {"block_number": True},
])
async def test_invalid_reference_is_rejected(snapshot, updates):
    with pytest.raises(ValidationError):
        reference_for(snapshot, **updates)


@pytest.mark.asyncio
@pytest.mark.parametrize("matches", [False, True])
async def test_check_cli_is_offline_supports_bom_and_never_claims_independence(
    snapshot, tmp_path, monkeypatch, capsys, matches,
):
    candidate = tmp_path / "candidate.json"
    reference = tmp_path / "reference.json"
    candidate.write_text(snapshot.model_dump_json(by_alias=True), encoding="utf-8-sig")
    reference.write_text(reference_for(
        snapshot, **({} if matches else {"balance_smallest_unit": "0"})
    ).model_dump_json(by_alias=True), encoding="utf-8-sig")

    def fail(**kwargs):
        raise AssertionError("Offline check must not load .env or construct a provider.")

    monkeypatch.setattr(cli, "Settings", fail)
    monkeypatch.setattr(cli, "Web3RpcProvider", fail)
    assert cli.main(["check", str(candidate), "--reference", str(reference)]) == (
        0 if matches else 1
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == ("matched" if matches else "mismatch")
    assert report["independentSourceVerified"] is False
    assert report["reviewRequired"] is True


def capture_arguments(path):
    return ["capture", "--token", TOKEN, "--owner", OWNER, "--output", str(path)]


def test_existing_file_is_never_overwritten_or_sent_to_rpc(tmp_path, monkeypatch, capsys):
    destination = tmp_path / "candidate.json"
    destination.write_text("original", encoding="utf-8")
    monkeypatch.setattr(cli, "Settings", lambda: pytest.fail("Do not load .env."))
    assert cli.main(capture_arguments(destination)) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "SNAPSHOT_FILE_ERROR"
    assert destination.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("failure", [False, True])
def test_capture_cli_writes_only_success_and_sanitizes_errors(
    tmp_path, monkeypatch, capsys, failure,
):
    provider = fake_provider()
    if failure:
        provider.get_erc20_balance.side_effect = RuntimeError("https://secret.invalid/key")
    monkeypatch.setattr(cli, "Web3RpcProvider", lambda **kwargs: provider)
    monkeypatch.setattr(cli, "Settings", capture_settings)
    destination = tmp_path / "candidate.json"
    assert cli.main(capture_arguments(destination)) == (2 if failure else 0)
    output = capsys.readouterr().out
    assert "secret" not in output
    assert "test-rpc-endpoint" not in output
    assert destination.exists() is not failure
    assert provider.closed is True
    if not failure:
        result = cli.TokenBalanceSnapshot.model_validate_json(destination.read_bytes())
        assert result.independent_source_verified is False
        assert json.loads(output)["metadataAvailable"] is True


def test_capture_cli_invalid_arguments_never_load_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Settings", lambda: pytest.fail("Do not load .env."))
    destination = tmp_path / "candidate.json"
    assert cli.main([*capture_arguments(destination), "--block-number", "-1"]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "INVALID_SNAPSHOT_INPUT"
    assert not destination.exists()


def test_capture_cli_invalid_configuration_does_not_leak_input(tmp_path, monkeypatch, capsys):
    settings_class = cli.Settings

    def invalid_settings():
        return settings_class(_env_file=None, rpc_url="secret-invalid-url")

    monkeypatch.setattr(cli, "Settings", invalid_settings)
    assert cli.main(capture_arguments(tmp_path / "candidate.json")) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == "CONFIGURATION_ERROR"
    assert "secret" not in output


def test_capture_cli_rejects_missing_parent_before_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Settings", lambda: pytest.fail("Do not load .env."))
    assert cli.main(capture_arguments(tmp_path / "missing" / "candidate.json")) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "SNAPSHOT_FILE_ERROR"


def test_symlink_input_is_rejected_before_read(tmp_path, monkeypatch, capsys):
    candidate = tmp_path / "candidate.json"
    candidate.write_text("secret", encoding="utf-8")
    monkeypatch.setattr(type(candidate), "is_symlink", lambda self: self == candidate)
    assert cli.main(["check", str(candidate), "--reference", str(candidate)]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == "INVALID_SNAPSHOT_INPUT"
    assert "secret" not in output


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_integration_smoke_requires_explicit_opt_in_and_both_addresses(monkeypatch, enabled):
    from tests.integration import test_token_balance_rpc as smoke

    monkeypatch.setenv("RUN_INTEGRATION_TESTS", "1" if enabled else "0")
    monkeypatch.delenv("INTEGRATION_TOKEN_BALANCE_TOKEN", raising=False)
    monkeypatch.delenv("INTEGRATION_TOKEN_BALANCE_OWNER", raising=False)
    monkeypatch.setattr(smoke, "Settings", lambda: pytest.fail("Do not load .env."))
    monkeypatch.setattr(smoke, "capture_snapshot", AsyncMock(
        side_effect=AssertionError("No external RPC without explicit inputs."),
    ))
    with pytest.raises(pytest.skip.Exception):
        await smoke.test_base_sepolia_token_balance_has_repeatable_snapshot()
    smoke.capture_snapshot.assert_not_awaited()


@pytest.mark.parametrize(
    "content", ["invalid secret", "{}", "a" * (cli.MAX_FILE_BYTES + 1)],
    ids=["invalid-json", "missing-fields", "oversized"],
)
def test_invalid_files_are_rejected_without_echo(tmp_path, capsys, content):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(content, encoding="utf-8")
    assert cli.main(["check", str(candidate), "--reference", str(candidate)]) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["code"] == "INVALID_SNAPSHOT_INPUT"
    assert "secret" not in output


def test_capture_cli_exclusive_write_handles_racing_file(
    snapshot, tmp_path, monkeypatch, capsys,
):
    destination = tmp_path / "candidate.json"

    async def capture(*args):
        destination.write_text("created by someone else", encoding="utf-8")
        return snapshot

    monkeypatch.setattr(cli, "Settings", capture_settings)
    monkeypatch.setattr(cli, "capture_snapshot", capture)
    assert cli.main(capture_arguments(destination)) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "SNAPSHOT_FILE_ERROR"
    assert destination.read_text(encoding="utf-8") == "created by someone else"
