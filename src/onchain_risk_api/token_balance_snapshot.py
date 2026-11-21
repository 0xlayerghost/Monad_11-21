import argparse
import asyncio
import json
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, ConfigDict, Field, ValidationError, model_validator

from onchain_risk_api.core.config import Settings
from onchain_risk_api.domain.errors import QueryError
from onchain_risk_api.domain.failures import describe_query_error
from onchain_risk_api.domain.models import ApiModel, Erc20BalanceResponse
from onchain_risk_api.domain.token_balance import token_balance_identity
from onchain_risk_api.domain.validation import EvmAddress, TransactionHash
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider
from onchain_risk_api.services.token_balance import TokenBalanceService
from onchain_risk_api.tools.models import Erc20BalanceArguments

MAX_FILE_BYTES = 200_000
SNAPSHOT_FIELDS = (
    "network", "chain_id", "token_address", "owner_address", "block_number",
    "block_hash", "block_timestamp", "balance_smallest_unit", "decimals",
)


class TokenBalanceSnapshot(ApiModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=1, strict=True, ge=1, le=1)
    independent_source_verified: Literal[False] = False
    first: Erc20BalanceResponse
    repeated: Erc20BalanceResponse

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        for response in (self.first, self.repeated):
            evidence = response.evidence
            if evidence.network != "base-sepolia" or evidence.chain_id != 84532:
                raise ValueError("This capture requires Base Sepolia.")
            identity = token_balance_identity(
                chain_id=evidence.chain_id, block_number=evidence.block_number,
                block_hash=evidence.block_hash, token_address=evidence.token_address,
                owner_address=evidence.owner_address,
                balance_smallest_unit=evidence.balance_smallest_unit, decimals=evidence.decimals,
            )
            if evidence.evidence_id != "evidence:" + sha256(identity.encode()).hexdigest():
                raise ValueError("Evidence identity does not match its content.")
            if not response.limitations:
                raise ValueError("Snapshot limitations are required.")
        if self.first.evidence.model_dump(exclude={"observed_at"}) != (
            self.repeated.evidence.model_dump(exclude={"observed_at"})
        ) or self.first.limitations != self.repeated.limitations:
            raise ValueError("The fixed-block reads did not match.")
        if self.repeated.evidence.observed_at < self.first.evidence.observed_at:
            raise ValueError("The repeated read predates the first read.")
        return self


class TokenBalanceReference(ApiModel):
    model_config = ConfigDict(extra="forbid")

    source_label: str = Field(min_length=1, max_length=120, pattern=r"^[\w .-]+$")
    observed_at: AwareDatetime
    network: Literal["base-sepolia"]
    chain_id: int = Field(strict=True, ge=84532, le=84532)
    token_address: EvmAddress
    owner_address: EvmAddress
    block_number: int = Field(strict=True, ge=0)
    block_hash: TransactionHash
    block_timestamp: AwareDatetime
    balance_smallest_unit: str = Field(pattern=r"^(0|[1-9][0-9]{0,77})$")
    decimals: int = Field(strict=True, ge=0, le=255)

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        if not self.source_label.strip() or int(self.balance_smallest_unit) >= 2**256:
            raise ValueError("Invalid source label or uint256 value.")
        return self


async def capture_snapshot(
    settings: Settings, arguments: Erc20BalanceArguments,
) -> TokenBalanceSnapshot:
    if settings.network_name != "base-sepolia" or settings.expected_chain_id != 84532:
        raise ValueError("This capture requires Base Sepolia.")
    provider = Web3RpcProvider(
        rpc_url=str(settings.rpc_url), timeout_seconds=settings.rpc_timeout_seconds,
        provider_name=settings.rpc_provider_name,
    )
    try:
        service = TokenBalanceService(settings=settings, provider=provider)
        first = await service.get_token_balance(**arguments.model_dump())
        pinned = arguments.model_copy(update={"block_number": first.evidence.block_number})
        repeated = await service.get_token_balance(**pinned.model_dump())
        return TokenBalanceSnapshot(first=first, repeated=repeated)
    finally:
        await provider.close()


def compare_reference(snapshot: TokenBalanceSnapshot, reference: TokenBalanceReference) -> dict:
    mismatches = [
        field for field in SNAPSHOT_FIELDS
        if getattr(snapshot.first.evidence, field) != getattr(reference, field)
    ]
    return {
        "status": "mismatch" if mismatches else "matched",
        "mismatchedFields": [
            TokenBalanceReference.model_fields[field].alias for field in mismatches
        ],
        "fieldsCompared": len(SNAPSHOT_FIELDS),
        "independentSourceVerified": False,
        "reviewRequired": True,
    }


def _load(path: Path, model: type[TokenBalanceSnapshot] | type[TokenBalanceReference]):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Use a regular JSON file.")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("JSON file is too large.")
    return model.model_validate_json(data.decode("utf-8-sig"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture or compare read-only ERC-20 balance snapshots."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser(
        "capture", help="Reads token balance twice using configured RPC; never calls a model."
    )
    capture.add_argument("--token", required=True)
    capture.add_argument("--owner", required=True)
    capture.add_argument("--block-number", type=int)
    capture.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("check", help="Offline comparison; never loads .env or calls RPC.")
    check.add_argument("snapshot", type=Path)
    check.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            snapshot = _load(args.snapshot, TokenBalanceSnapshot)
            reference = _load(args.reference, TokenBalanceReference)
            report = compare_reference(snapshot, reference)
            print(json.dumps(report, indent=2))
            return 0 if report["status"] == "matched" else 1
        arguments = Erc20BalanceArguments(
            network_name="base-sepolia", token_address=args.token, owner_address=args.owner,
            block_number=args.block_number,
        )
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise OSError("Use a new file in an existing directory.")
        try:
            settings = Settings()
        except ValidationError:
            print(json.dumps({"status": "error", "code": "CONFIGURATION_ERROR"}))
            return 2
        snapshot = asyncio.run(capture_snapshot(settings, arguments))
        payload = snapshot.model_dump_json(by_alias=True, indent=2) + "\n"
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(payload)
        print(json.dumps({
            "status": "captured", "repeatReadMatched": True,
            "metadataAvailable": snapshot.first.evidence.decimals is not None,
            "independentSourceVerified": False, "reviewRequired": True,
        }))
        return 0
    except QueryError as exc:
        _, error = describe_query_error(exc)
        code = error.code
    except OSError:
        code = "SNAPSHOT_FILE_ERROR"
    except (ValueError, RecursionError):
        code = "INVALID_SNAPSHOT_INPUT"
    except Exception:
        code = "SNAPSHOT_FAILED"
    print(json.dumps({"status": "error", "code": code}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
