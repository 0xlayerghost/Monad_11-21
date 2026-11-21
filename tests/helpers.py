from datetime import UTC, datetime
from typing import Literal

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import BlockNotFoundError, RpcUnavailableError
from onchain_risk_api.domain.models import (
    BlockSnapshot,
    TransactionReceiptSnapshot,
    TransactionSnapshot,
)

TRANSACTION_HASH = "0x" + "cd" * 32


def make_test_settings(
    *,
    network_name: str = "base-sepolia",
    expected_chain_id: int = 84532,
    native_symbol: str = "ETH",
    native_decimals: int = 18,
    rpc_provider_name: str = "blockpi",
) -> Settings:
    return Settings(
        _env_file=None,
        rpc_url="https://example.invalid/test-rpc-endpoint",
        network_name=network_name,
        expected_chain_id=expected_chain_id,
        native_symbol=native_symbol,
        native_decimals=native_decimals,
        rpc_provider_name=rpc_provider_name,
    )


class FakeChainProvider:
    def __init__(
        self,
        *,
        chain_id: int = 84532,
        unavailable: bool = False,
        balance_smallest_unit: int = 10**18 + 1,
    ) -> None:
        self.chain_id = chain_id
        self.unavailable = unavailable
        self.closed = False
        self.balance_smallest_unit = balance_smallest_unit
        self.block = BlockSnapshot(
            number=123,
            block_hash="0x" + "ab" * 32,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.chain_calls = 0
        self.block_requests: list[int | str] = []
        self.balance_requests: list[tuple[str, int]] = []
        self.transaction_requests: list[str] = []
        self.receipt_requests: list[str] = []
        self.transaction: TransactionSnapshot | None = TransactionSnapshot(
            transaction_hash=TRANSACTION_HASH,
            block_number=self.block.number,
            block_hash=self.block.block_hash,
        )
        self.receipt: TransactionReceiptSnapshot | None = TransactionReceiptSnapshot(
            transaction_hash=TRANSACTION_HASH,
            block_number=self.block.number,
            block_hash=self.block.block_hash,
            transaction_index=0,
            status=1,
            from_address="0x" + "11" * 20,
            to_address="0x" + "22" * 20,
            contract_address=None,
            gas_used=21000,
            effective_gas_price=10**9,
        )

    async def get_chain_id(self) -> int:
        self.chain_calls += 1
        if self.unavailable:
            raise RpcUnavailableError(provider_name="test-provider")
        return self.chain_id

    async def get_block(self, block_identifier: int | Literal["latest"]) -> BlockSnapshot:
        self.block_requests.append(block_identifier)
        if block_identifier != "latest" and block_identifier != self.block.number:
            raise BlockNotFoundError()
        return self.block

    async def get_balance(self, address: str, *, block_number: int) -> int:
        self.balance_requests.append((address, block_number))
        return self.balance_smallest_unit

    async def close(self) -> None:
        self.closed = True

    async def get_erc20_allowance(
        self,
        token_address: str,
        owner_address: str,
        spender_address: str,
        *,
        block_number: int,
    ) -> int:
        return 0

    async def get_transaction(self, transaction_hash: str) -> TransactionSnapshot | None:
        self.transaction_requests.append(transaction_hash)
        return self.transaction

    async def get_transaction_receipt(
        self, transaction_hash: str
    ) -> TransactionReceiptSnapshot | None:
        self.receipt_requests.append(transaction_hash)
        return self.receipt
