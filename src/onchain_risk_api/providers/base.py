from typing import Literal, Protocol

from onchain_risk_api.domain.models import (
    BlockSnapshot,
    Erc20TransferEvent,
    TransactionReceiptSnapshot,
    TransactionSnapshot,
)


class ChainProvider(Protocol):
    async def get_chain_id(self) -> int: ...

    async def get_block(self, block_identifier: int | Literal["latest"]) -> BlockSnapshot: ...

    async def get_balance(self, address: str, *, block_number: int) -> int: ...

    async def get_erc20_balance(
        self, token_address: str, owner_address: str, *, block_number: int,
    ) -> int: ...

    async def get_erc20_decimals(self, token_address: str, *, block_number: int) -> int: ...

    async def get_erc20_transfer_logs(
        self, token_address: str, owner_address: str, *, from_block: int, to_block: int,
    ) -> list[Erc20TransferEvent]: ...

    async def get_erc20_allowance(
        self,
        token_address: str,
        owner_address: str,
        spender_address: str,
        *,
        block_number: int,
    ) -> int: ...

    async def get_transaction(self, transaction_hash: str) -> TransactionSnapshot | None: ...

    async def get_transaction_receipt(
        self, transaction_hash: str
    ) -> TransactionReceiptSnapshot | None: ...

    async def close(self) -> None: ...
