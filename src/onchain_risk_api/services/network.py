from datetime import UTC, datetime

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import ChainMismatchError, NetworkNotConfiguredError
from onchain_risk_api.domain.models import NetworkStatusResponse
from onchain_risk_api.providers.base import ChainProvider


class NetworkService:
    def __init__(self, *, settings: Settings, provider: ChainProvider) -> None:
        self._settings = settings
        self._provider = provider

    async def get_status(self, *, network_name: str | None = None) -> NetworkStatusResponse:
        if network_name is not None and network_name != self._settings.network_name:
            raise NetworkNotConfiguredError()
        actual_chain_id = await self._provider.get_chain_id()
        if actual_chain_id != self._settings.expected_chain_id:
            raise ChainMismatchError(
                expected_chain_id=self._settings.expected_chain_id,
                actual_chain_id=actual_chain_id,
            )

        return NetworkStatusResponse(
            status="ready",
            network=self._settings.network_name,
            chain_id=actual_chain_id,
            expected_chain_id=self._settings.expected_chain_id,
            provider=self._settings.rpc_provider_name,
            observed_at=datetime.now(UTC),
        )
