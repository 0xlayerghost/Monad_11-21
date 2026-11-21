from datetime import UTC, datetime
from hashlib import sha256

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import (
    BlockNotFoundError,
    NetworkNotConfiguredError,
    RpcUnavailableError,
    SnapshotChangedError,
    TokenCallFailedError,
    TokenNotConfiguredError,
)
from onchain_risk_api.domain.failures import describe_query_error
from onchain_risk_api.domain.models import Erc20BalanceEvidence, Erc20BalanceResponse
from onchain_risk_api.domain.token_balance import token_balance_identity
from onchain_risk_api.providers.base import ChainProvider
from onchain_risk_api.services.network import NetworkService


class TokenBalanceService:
    def __init__(self, *, settings: Settings, provider: ChainProvider) -> None:
        self._settings = settings
        self._provider = provider
        self._network = NetworkService(settings=settings, provider=provider)
        self._tokens = {address.lower() for address in settings.erc20_allowed_tokens}

    async def get_token_balance(
        self, token_address: str, owner_address: str, *,
        network_name: str | None = None, block_number: int | None = None,
    ) -> Erc20BalanceResponse:
        if network_name is not None and network_name != self._settings.network_name:
            raise NetworkNotConfiguredError()
        if self._tokens and token_address.lower() not in self._tokens:
            raise TokenNotConfiguredError()
        network = await self._network.get_status(network_name=network_name)
        block = await self._provider.get_block(
            block_number if block_number is not None else "latest"
        )
        amount = await self._provider.get_erc20_balance(
            token_address, owner_address, block_number=block.number,
        )
        if type(amount) is not int or not 0 <= amount < 2**256:
            raise RpcUnavailableError(provider_name=network.provider)
        decimals = None
        formatted = None
        metadata_error = None
        try:
            decimals = await self._provider.get_erc20_decimals(
                token_address, block_number=block.number,
            )
            if type(decimals) is not int or not 0 <= decimals <= 255:
                raise RpcUnavailableError(provider_name=network.provider)
            whole, fraction = divmod(amount, 10**decimals)
            formatted = f"{whole}.{fraction:0{decimals}d}" if decimals else str(whole)
        except (TokenCallFailedError, RpcUnavailableError) as exc:
            decimals = None
            _, metadata_error = describe_query_error(exc)
        try:
            confirmed = await self._provider.get_block(block.number)
        except BlockNotFoundError as exc:
            raise SnapshotChangedError() from exc
        if confirmed.block_hash.lower() != block.block_hash.lower():
            raise SnapshotChangedError()
        identity = token_balance_identity(
            chain_id=network.chain_id, block_number=block.number, block_hash=block.block_hash,
            token_address=token_address, owner_address=owner_address,
            balance_smallest_unit=str(amount), decimals=decimals,
        )
        return Erc20BalanceResponse(
            evidence=Erc20BalanceEvidence(
                evidence_id="evidence:" + sha256(identity.encode()).hexdigest(),
                network=network.network, chain_id=network.chain_id, provider=network.provider,
                token_address=token_address, owner_address=owner_address,
                balance_smallest_unit=str(amount), decimals=decimals,
                balance_formatted=formatted, metadata_error=metadata_error,
                block_number=block.number, block_hash=block.block_hash,
                block_timestamp=block.timestamp, observed_at=datetime.now(UTC),
            ),
            limitations=[
                "Only the requested token and owner at the selected block were read.",
                "No other token holdings, allowances, transfers, prices or safety were assessed.",
                "Decimals are optional metadata; when unavailable only smallest units are known.",
                "Token identity, transferability and finality were not verified; "
                "an empty token allowlist permits any valid token address and is not a safety "
                "endorsement.",
                "Block-number reads with a hash recheck are not an atomic snapshot "
                "or a finality guarantee.",
            ],
        )
