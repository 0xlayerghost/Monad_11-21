from unittest.mock import AsyncMock

import pytest
from web3 import Web3

from onchain_risk_api.providers.web3_rpc import TRANSFER_TOPIC, Web3RpcProvider
from tests.unit.test_allowance_api import OWNER, TOKEN


@pytest.mark.asyncio
async def test_transfer_logs_query_binds_token_owner_and_decodes_events():
    provider = Web3RpcProvider(rpc_url="https://example.invalid/private", timeout_seconds=1)
    tx_hash = "0x" + "aa" * 32
    to = "0x" + "33" * 20
    log = {
        "topics": [
            Web3.to_bytes(hexstr=TRANSFER_TOPIC),
            Web3.to_bytes(hexstr="0x" + OWNER[2:].rjust(64, "0")),
            Web3.to_bytes(hexstr="0x" + to[2:].rjust(64, "0")),
        ],
        "data": "0x" + (7).to_bytes(32, "big").hex(),
        "transactionHash": Web3.to_bytes(hexstr=tx_hash),
        "blockNumber": 123, "logIndex": 0,
    }
    second_log = {**log, "logIndex": 1, "topics": [
        Web3.to_bytes(hexstr=TRANSFER_TOPIC),
        Web3.to_bytes(hexstr="0x" + ("44" * 20).rjust(64, "0")),
        Web3.to_bytes(hexstr="0x" + OWNER[2:].rjust(64, "0")),
    ]}
    provider._web3.eth.get_logs = AsyncMock(side_effect=[[log], [second_log]])
    events = await provider.get_erc20_transfer_logs(TOKEN, OWNER, from_block=100, to_block=123)
    assert len(events) == 2
    assert events[0].amount_smallest_unit == "7"
    assert provider._web3.eth.get_logs.await_count == 2
    first_filter = provider._web3.eth.get_logs.await_args_list[0].args[0]
    assert first_filter["address"] == TOKEN
    assert first_filter["fromBlock"] == 100
    assert first_filter["toBlock"] == 123
    assert first_filter["topics"][0] == TRANSFER_TOPIC
