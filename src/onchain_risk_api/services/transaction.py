from datetime import UTC, datetime

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import (
    BlockNotFoundError,
    ReceiptUnavailableError,
    SnapshotChangedError,
    TransactionNotFoundError,
)
from onchain_risk_api.domain.models import TransactionReceiptResponse
from onchain_risk_api.providers.base import ChainProvider
from onchain_risk_api.services.network import NetworkService


class TransactionService:
    def __init__(self, *, settings: Settings, provider: ChainProvider) -> None:
        self._settings = settings
        self._provider = provider
        self._network = NetworkService(settings=settings, provider=provider)

    async def get_receipt(
        self, transaction_hash: str, *, network_name: str | None = None
    ) -> TransactionReceiptResponse:
        await self._network.get_status(network_name=network_name)
        receipt = await self._provider.get_transaction_receipt(transaction_hash)
        if receipt is None:
            transaction = await self._provider.get_transaction(transaction_hash)
            if transaction is None:
                raise TransactionNotFoundError()
            if transaction.block_number is not None:
                raise ReceiptUnavailableError()
            return TransactionReceiptResponse(
                status="pending",
                network=self._settings.network_name,
                chain_id=self._settings.expected_chain_id,
                provider=self._settings.rpc_provider_name,
                transaction_hash=transaction_hash,
                observed_at=datetime.now(UTC),
            )

        try:
            block = await self._provider.get_block(receipt.block_number)
        except BlockNotFoundError as exc:
            raise SnapshotChangedError() from exc
        if block.block_hash != receipt.block_hash:
            raise SnapshotChangedError()

        return TransactionReceiptResponse(
            status="mined",
            network=self._settings.network_name,
            chain_id=self._settings.expected_chain_id,
            provider=self._settings.rpc_provider_name,
            transaction_hash=receipt.transaction_hash,
            observed_at=datetime.now(UTC),
            execution_status="success" if receipt.status == 1 else "reverted",
            block_number=block.number,
            block_hash=block.block_hash,
            block_timestamp=block.timestamp,
            transaction_index=receipt.transaction_index,
            from_address=receipt.from_address,
            to_address=receipt.to_address,
            contract_address=receipt.contract_address,
            gas_used=str(receipt.gas_used),
            effective_gas_price=(
                str(receipt.effective_gas_price)
                if receipt.effective_gas_price is not None
                else None
            ),
        )
