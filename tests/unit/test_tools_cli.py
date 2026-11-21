import io
import json
from unittest.mock import AsyncMock

import pytest

from onchain_risk_api.app import create_app
from onchain_risk_api.domain.errors import RpcUnavailableError
from onchain_risk_api.domain.models import ApiError
from onchain_risk_api.tools import __main__ as cli
from onchain_risk_api.tools.models import ToolCallResult
from tests.helpers import FakeChainProvider, make_test_settings


def test_list_command_does_not_load_configuration_or_start_the_app(monkeypatch, capsys) -> None:
    def fail_if_started():
        raise AssertionError("No app or RPC is needed to list schemas.")

    monkeypatch.setattr(cli, "create_app", fail_if_started)

    assert cli.main(["list"]) == 0
    definitions = json.loads(capsys.readouterr().out)
    assert len(definitions) == 5
    assert all(item["readOnly"] for item in definitions)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_call_command_closes_its_provider_on_success_and_error(
    monkeypatch, failure: bool,
) -> None:
    provider = FakeChainProvider()
    if failure:
        provider.get_chain_id = AsyncMock(side_effect=RpcUnavailableError(provider_name="test"))
    app = create_app(settings=make_test_settings(), provider=provider)
    monkeypatch.setattr(cli, "create_app", lambda: app)

    result = await cli._call_tool(
        "get_native_balance",
        '{"network_name":"base-sepolia","address":"0x1111111111111111111111111111111111111111"}',
    )

    assert result.status == ("error" if failure else "ok")
    assert provider.closed is True


def test_cli_reads_json_from_stdin_and_returns_nonzero_for_failed_tools(
    monkeypatch, capsys,
) -> None:
    arguments = '{"network_name":"base-sepolia"}'
    call = AsyncMock(return_value=ToolCallResult(
        tool_name="get_native_balance", status="error",
        error=ApiError(code="INVALID_TOOL_ARGUMENTS", message="Tool arguments are invalid."),
    ))
    monkeypatch.setattr(cli, "_call_tool", call)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO(arguments))

    assert cli.main(["call", "get_native_balance", "-"]) == 1

    call.assert_awaited_once_with("get_native_balance", arguments)
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "INVALID_TOOL_ARGUMENTS"


def test_cli_hides_unexpected_bootstrap_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_call_tool", AsyncMock(side_effect=RuntimeError("secret endpoint")))

    assert cli.main(["call", "get_native_balance", "{}"]) == 1

    output = capsys.readouterr().out
    assert json.loads(output)["error"]["code"] == "TOOL_EXECUTION_FAILED"
    assert "secret" not in output
