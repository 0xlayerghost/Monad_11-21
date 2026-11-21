from unittest.mock import AsyncMock

import pytest

from onchain_risk_api.domain.errors import TokenCallFailedError
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider
from tests.unit.test_allowance_api import OWNER, TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "amount", "selector"), [
    ("get_erc20_balance", 0, "70a08231"),
    ("get_erc20_balance", 2**256 - 1, "70a08231"),
    ("get_erc20_decimals", 0, "313ce567"),
    ("get_erc20_decimals", 6, "313ce567"),
    ("get_erc20_decimals", 255, "313ce567"),
])
async def test_real_abi_encoding_and_decoding_without_network(method, amount, selector):
    provider = Web3RpcProvider(rpc_url="https://example.invalid/private", timeout_seconds=1)
    call = AsyncMock(return_value=amount.to_bytes(32, "big"))
    provider._web3.eth.call = call
    arguments = [TOKEN, OWNER] if method == "get_erc20_balance" else [TOKEN]
    assert await getattr(provider, method)(*arguments, block_number=123) == amount
    transaction = call.call_args.args[0]
    assert transaction["to"] == TOKEN
    assert transaction["data"] == "0x" + selector + (
        f"{OWNER[2:]:0>64}" if method == "get_erc20_balance" else ""
    )
    assert call.call_args.kwargs["block_identifier"] == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_erc20_balance", "get_erc20_decimals"])
async def test_undecodable_return_is_not_zero(method):
    provider = Web3RpcProvider(rpc_url="https://example.invalid/private", timeout_seconds=1)
    provider._web3.eth.call = AsyncMock(return_value=b"")
    provider._web3.eth.get_code = AsyncMock(return_value=b"\x01")
    arguments = [TOKEN, OWNER] if method == "get_erc20_balance" else [TOKEN]
    with pytest.raises(TokenCallFailedError):
        await getattr(provider, method)(*arguments, block_number=123)
