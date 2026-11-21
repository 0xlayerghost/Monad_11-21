import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from onchain_risk_api.core.config import Settings


def test_example_allowlists_are_valid_json_address_arrays() -> None:
    example = Path(__file__).parents[2] / ".env.example"
    values = dict(
        line.split("=", 1)
        for line in example.read_text(encoding="utf-8").splitlines()
        if line.startswith(("ERC20_ALLOWED_TOKENS=", "ERC20_ALLOWED_SPENDERS="))
    )

    assert set(values) == {"ERC20_ALLOWED_TOKENS", "ERC20_ALLOWED_SPENDERS"}
    for value in values.values():
        addresses = json.loads(value)
        assert isinstance(addresses, list)
        Settings(
            _env_file=None,
            rpc_url="https://example.invalid/rpc",
            erc20_allowed_tokens=addresses,
        )


def test_network_configuration_is_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RPC_URL", "https://example.invalid/rpc")
    monkeypatch.setenv("NETWORK_NAME", "arbitrum-one")
    monkeypatch.setenv("EXPECTED_CHAIN_ID", "42161")
    monkeypatch.setenv("NATIVE_SYMBOL", "ETH")
    monkeypatch.setenv("NATIVE_DECIMALS", "18")
    monkeypatch.setenv("RPC_PROVIDER_NAME", "alchemy")

    settings = Settings(_env_file=None)

    assert settings.network_name == "arbitrum-one"
    assert settings.expected_chain_id == 42161
    assert settings.native_symbol == "ETH"
    assert settings.native_decimals == 18
    assert settings.rpc_provider_name == "alchemy"
    assert str(settings.rpc_url) == "https://example.invalid/rpc"


@pytest.mark.parametrize(
    ("environment", "value"),
    [
        ("EXPECTED_CHAIN_ID", "0"),
        ("NATIVE_DECIMALS", "-1"),
        ("NATIVE_DECIMALS", "256"),
        ("NETWORK_NAME", "../other-chain"),
    ],
)
def test_invalid_environment_network_settings_are_rejected(
    monkeypatch: pytest.MonkeyPatch, environment: str, value: str
) -> None:
    monkeypatch.setenv("RPC_URL", "https://example.invalid/rpc")
    monkeypatch.setenv(environment, value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_allowlists_are_loaded_from_json_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RPC_URL", "https://example.invalid/rpc")
    monkeypatch.setenv("ERC20_ALLOWED_TOKENS", '["0x' + "ab" * 20 + '"]')
    monkeypatch.setenv("ERC20_ALLOWED_SPENDERS", '["0x' + "cd" * 20 + '"]')

    settings = Settings(_env_file=None)

    assert len(settings.erc20_allowed_tokens) == 1
    assert settings.erc20_allowed_tokens[0].lower() == "0x" + "ab" * 20
    assert len(settings.erc20_allowed_spenders) == 1
    assert settings.erc20_allowed_spenders[0].lower() == "0x" + "cd" * 20


@pytest.mark.parametrize("field", ["erc20_allowed_tokens", "erc20_allowed_spenders"])
@pytest.mark.parametrize(
    "addresses",
    [
        ["bad"],
        ["0xaBcdefabcdefabcdefabcdefabcdefabcdefabcdef"],
        ["0x" + "11" * 20] * 51,
    ],
)
def test_invalid_allowlists_are_rejected(field: str, addresses: list[str]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rpc_url="https://example.invalid/rpc", **{field: addresses})
