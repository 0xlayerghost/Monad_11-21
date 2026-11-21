from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from web3.exceptions import BadFunctionCallOutput, ContractLogicError

from onchain_risk_api.domain.errors import RpcUnavailableError, TokenCallFailedError
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider

TOKEN = "0x" + "11" * 20
OWNER = "0x" + "22" * 20
SPENDER = "0x" + "33" * 20


def provider_with_call(call: AsyncMock) -> tuple[Web3RpcProvider, Mock]:
    functions = SimpleNamespace(allowance=Mock(return_value=SimpleNamespace(call=call)))
    contract = Mock(return_value=SimpleNamespace(functions=functions))
    provider = Web3RpcProvider(
        rpc_url="https://example.invalid/private-endpoint", timeout_seconds=1,
        provider_name="blockpi",
    )
    provider._web3 = SimpleNamespace(eth=SimpleNamespace(contract=contract))
    return provider, contract


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 1, 2**256 - 1])
async def test_call_is_read_only_and_block_pinned(amount: int) -> None:
    call = AsyncMock(return_value=amount)
    provider, contract = provider_with_call(call)
    assert await provider.get_erc20_allowance(TOKEN, OWNER, SPENDER, block_number=123) == amount
    assert contract.call_args.kwargs["address"] == TOKEN
    abi = contract.call_args.kwargs["abi"]
    assert len(abi) == 1
    assert abi[0]["name"] == "allowance"
    assert abi[0]["stateMutability"] == "view"
    functions = contract.return_value.functions
    functions.allowance.assert_called_once_with(OWNER, SPENDER)
    call.assert_awaited_once_with(block_identifier=123)


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [None, -1, 2**256, True, 1.5, "1"])
async def test_invalid_allowance_is_not_valid_state(amount: object) -> None:
    provider, _ = provider_with_call(AsyncMock(return_value=amount))
    with pytest.raises(RpcUnavailableError):
        await provider.get_erc20_allowance(TOKEN, OWNER, SPENDER, block_number=123)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [BadFunctionCallOutput, ContractLogicError])
async def test_contract_failure_is_distinct_and_sanitized(error_type) -> None:
    provider, _ = provider_with_call(
        AsyncMock(side_effect=error_type("https://example.invalid/private-endpoint"))
    )
    with pytest.raises(TokenCallFailedError) as captured:
        await provider.get_erc20_allowance(TOKEN, OWNER, SPENDER, block_number=123)
    assert "private-endpoint" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [TimeoutError, ConnectionError, ValueError])
async def test_transport_errors_are_sanitized(error_type) -> None:
    provider, _ = provider_with_call(
        AsyncMock(side_effect=error_type("https://example.invalid/private-endpoint"))
    )
    with pytest.raises(RpcUnavailableError) as captured:
        await provider.get_erc20_allowance(TOKEN, OWNER, SPENDER, block_number=123)
    assert str(captured.value) == "RPC provider blockpi is unavailable."


@pytest.mark.asyncio
@pytest.mark.parametrize("amount", [0, 10**30 + 1, 2**256 - 1])
async def test_real_abi_encoding_and_decoding_without_network(amount: int) -> None:
    provider = Web3RpcProvider(
        rpc_url="https://example.invalid/private-endpoint", timeout_seconds=1
    )
    call = AsyncMock(return_value=amount.to_bytes(32, "big"))
    provider._web3.eth.call = call

    result = await provider.get_erc20_allowance(TOKEN, OWNER, SPENDER, block_number=123)

    assert result == amount
    call.assert_awaited_once()
    transaction = call.call_args.args[0]
    assert transaction["to"] == TOKEN
    assert transaction["data"] == f"0xdd62ed3e{OWNER[2:]:0>64}{SPENDER[2:]:0>64}"
    assert call.call_args.kwargs["block_identifier"] == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [b"", b"invalid"])
async def test_undecodable_abi_output_is_a_token_failure(output: bytes) -> None:
    provider = Web3RpcProvider(
        rpc_url="https://example.invalid/private-endpoint", timeout_seconds=1
    )
    provider._web3.eth.call = AsyncMock(return_value=output)
    provider._web3.eth.get_code = AsyncMock(return_value=b"\x01")

    with pytest.raises(TokenCallFailedError):
        await provider.get_erc20_allowance(TOKEN, OWNER, SPENDER, block_number=123)
