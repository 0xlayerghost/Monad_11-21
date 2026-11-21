from datetime import UTC, datetime

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import BlockNotFoundError, SnapshotChangedError
from onchain_risk_api.domain.models import NativeBalanceResponse
from onchain_risk_api.providers.base import ChainProvider
from onchain_risk_api.services.network import NetworkService


class BalanceService:
    def __init__(self, *, settings: Settings, provider: ChainProvider) -> None:
        self._settings = settings
        self._provider = provider
        self._network = NetworkService(settings=settings, provider=provider)

    async def get_native_balance(
        self,
        address: str,
        *,
        network_name: str | None = None,
        block_number: int | None = None,
    ) -> NativeBalanceResponse:
        await self._network.get_status(network_name=network_name)
        block = await self._provider.get_block(
            block_number if block_number is not None else "latest"
        )
        balance = await self._provider.get_balance(address, block_number=block.number)
        try:
            confirmed_block = await self._provider.get_block(block.number)
        except BlockNotFoundError as exc:
            raise SnapshotChangedError() from exc
        if confirmed_block.block_hash != block.block_hash:
            raise SnapshotChangedError()

        whole_units, fractional_units = divmod(
            balance, 10**self._settings.native_decimals
        )
        return NativeBalanceResponse(
            network=self._settings.network_name,
            chain_id=self._settings.expected_chain_id,
            provider=self._settings.rpc_provider_name,
            address=address,
            asset=self._settings.native_symbol,
            decimals=self._settings.native_decimals,
            balance_smallest_unit=str(balance),
            balance_native=(
                f"{whole_units}.{fractional_units:0{self._settings.native_decimals}d}"
                if self._settings.native_decimals
                else str(whole_units)
            ),
            block_number=block.number,
            block_hash=block.block_hash,
            block_timestamp=block.timestamp,
            observed_at=datetime.now(UTC),
        )
