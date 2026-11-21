from datetime import UTC, datetime
from hashlib import sha256

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import (
    ActivityLimitExceededError,
    BlockRangeTooLargeError,
    NetworkNotConfiguredError,
    SnapshotChangedError,
    TokenNotConfiguredError,
)
from onchain_risk_api.domain.models import Erc20TransferActivityResponse
from onchain_risk_api.providers.base import ChainProvider
from onchain_risk_api.rules.transfer_activity import evaluate_transfer_activity
from onchain_risk_api.services.network import NetworkService

MAX_BLOCK_SPAN = 2_000
MAX_EVENTS = 100


class TransferActivityService:
    def __init__(self, *, settings: Settings, provider: ChainProvider) -> None:
        self._settings = settings
        self._provider = provider
        self._network = NetworkService(settings=settings, provider=provider)
        self._tokens = {address.lower() for address in settings.erc20_allowed_tokens}

    async def get_activity(
        self, token_address: str, owner_address: str, *, from_block: int, to_block: int,
        network_name: str | None = None,
    ) -> Erc20TransferActivityResponse:
        if network_name is not None and network_name != self._settings.network_name:
            raise NetworkNotConfiguredError()
        if self._tokens and token_address.lower() not in self._tokens:
            raise TokenNotConfiguredError()
        if to_block < from_block:
            raise BlockRangeTooLargeError()
        if to_block - from_block > MAX_BLOCK_SPAN:
            raise BlockRangeTooLargeError()
        network = await self._network.get_status(network_name=network_name)
        start = await self._provider.get_block(from_block)
        end = await self._provider.get_block(to_block)
        events = await self._provider.get_erc20_transfer_logs(
            token_address, owner_address, from_block=from_block, to_block=to_block,
        )
        if len(events) > MAX_EVENTS:
            raise ActivityLimitExceededError()
        confirmed = await self._provider.get_block(to_block)
        if confirmed.block_hash.lower() != end.block_hash.lower():
            raise SnapshotChangedError()
        identity = "|".join([
            "erc20-transfer-activity", "v1", str(network.chain_id), str(from_block),
            str(to_block), end.block_hash.lower(), token_address.lower(), owner_address.lower(),
            ";".join(
                f"{event.transaction_hash}:{event.log_index}:{event.amount_smallest_unit}"
                for event in events
            ),
        ])
        evidence_id = "evidence:" + sha256(identity.encode()).hexdigest()
        return Erc20TransferActivityResponse(
            network=network.network, chain_id=network.chain_id, provider=network.provider,
            token_address=token_address, owner_address=owner_address,
            from_block=start.number, to_block=end.number, events=events,
            evidence_id=evidence_id,
            findings=evaluate_transfer_activity(evidence_id=evidence_id, events=events),
            observed_at=datetime.now(UTC), limitations=[
                "Only Transfer logs for the requested token and owner were queried.",
                "The range is bounded to 2,000 blocks and results to 100 events.",
                "Logs do not prove token legitimacy, price, solvency, or finality.",
                "Proxy, non-standard, or malicious contracts may emit misleading events.",
                "Zero-address findings describe mint-like or burn-like event shapes only; "
                "they do not prove supply changes or contract safety.",
            ],
        )
