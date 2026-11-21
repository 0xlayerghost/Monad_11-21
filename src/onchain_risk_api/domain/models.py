from datetime import datetime
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from onchain_risk_api.domain.validation import EvmAddress, TransactionHash


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=_to_camel, populate_by_name=True)


class HealthResponse(ApiModel):
    status: Literal["ok"]
    service: str
    version: str


class NetworkStatusResponse(ApiModel):
    status: Literal["ready"]
    network: str
    chain_id: int
    expected_chain_id: int
    provider: str
    observed_at: datetime


class BlockSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int = Field(strict=True, ge=0)
    block_hash: str = Field(pattern=r"^0x[0-9a-fA-F]{64}$")
    timestamp: AwareDatetime


class NativeBalanceResponse(ApiModel):
    network: str
    chain_id: int
    provider: str
    address: str
    asset: str
    decimals: int
    balance_smallest_unit: str
    balance_native: str
    block_number: int
    block_hash: str
    block_timestamp: datetime
    observed_at: datetime


class ApiError(ApiModel):
    code: str
    message: str
    details: dict[str, int | str] | None = None


class TransactionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    transaction_hash: TransactionHash
    block_number: int | None = Field(strict=True, ge=0)
    block_hash: TransactionHash | None

    @model_validator(mode="after")
    def validate_block_context(self) -> Self:
        if (self.block_number is None) != (self.block_hash is None):
            raise ValueError("Transaction block number and hash must both be present or absent.")
        return self


class TransactionReceiptSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    transaction_hash: TransactionHash
    block_number: int = Field(strict=True, ge=0)
    block_hash: TransactionHash
    transaction_index: int = Field(strict=True, ge=0)
    status: int = Field(strict=True, ge=0, le=1)
    from_address: EvmAddress
    to_address: EvmAddress | None
    contract_address: EvmAddress | None
    gas_used: int = Field(strict=True, ge=0, lt=2**256)
    effective_gas_price: int | None = Field(default=None, strict=True, ge=0, lt=2**256)


class TransactionReceiptResponse(ApiModel):
    status: Literal["pending", "mined"]
    network: str
    chain_id: int
    provider: str
    transaction_hash: str
    observed_at: datetime
    execution_status: Literal["success", "reverted"] | None = None
    block_number: int | None = None
    block_hash: str | None = None
    block_timestamp: datetime | None = None
    transaction_index: int | None = None
    from_address: str | None = None
    to_address: str | None = None
    contract_address: str | None = None
    gas_used: str | None = None
    effective_gas_price: str | None = None


class ErrorResponse(ApiModel):
    error: ApiError


class Erc20AllowanceEvidence(ApiModel):
    evidence_id: str = Field(pattern=r"^evidence:[0-9a-f]{64}$")
    network: str
    chain_id: int = Field(strict=True, gt=0)
    provider: str
    token_address: EvmAddress
    owner_address: EvmAddress
    spender_address: EvmAddress
    allowance_smallest_unit: str = Field(pattern=r"^(0|[1-9][0-9]{0,77})$")
    block_number: int = Field(strict=True, ge=0)
    block_hash: TransactionHash
    block_timestamp: AwareDatetime
    observed_at: AwareDatetime

    @field_validator("allowance_smallest_unit")
    @classmethod
    def validate_allowance(cls, value: str) -> str:
        if int(value) >= 2**256:
            raise ValueError("Allowance must fit in uint256.")
        return value


class RiskFinding(ApiModel):
    finding_id: str = Field(pattern=r"^finding:[0-9a-f]{64}$")
    rule_id: str
    rule_version: int = Field(default=1, ge=1)
    severity: Literal["attention"] = "attention"
    evidence_ids: list[str] = Field(min_length=1)
    summary: str


class Erc20BalanceEvidence(ApiModel):
    evidence_id: str = Field(pattern=r"^evidence:[0-9a-f]{64}$")
    network: str
    chain_id: int = Field(strict=True, gt=0)
    provider: str
    token_address: EvmAddress
    owner_address: EvmAddress
    balance_smallest_unit: str = Field(pattern=r"^(0|[1-9][0-9]{0,77})$")
    decimals: int | None = Field(default=None, strict=True, ge=0, le=255)
    balance_formatted: str | None = None
    metadata_error: ApiError | None = None
    block_number: int = Field(strict=True, ge=0)
    block_hash: TransactionHash
    block_timestamp: AwareDatetime
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_balance(self) -> Self:
        amount = int(self.balance_smallest_unit)
        if amount >= 2**256:
            raise ValueError("Balance must fit in uint256.")
        if self.decimals is None:
            if self.balance_formatted is not None or self.metadata_error is None:
                raise ValueError(
                    "Unknown decimals require a metadata error and no formatted balance."
                )
        else:
            whole, fraction = divmod(amount, 10**self.decimals)
            expected = (
                f"{whole}.{fraction:0{self.decimals}d}" if self.decimals else str(whole)
            )
            if self.balance_formatted != expected or self.metadata_error is not None:
                raise ValueError("Formatted balance must exactly match the amount and decimals.")
        return self


class Erc20BalanceResponse(ApiModel):
    evidence: Erc20BalanceEvidence
    limitations: list[str]


class Erc20TransferEvent(ApiModel):
    transaction_hash: TransactionHash
    block_number: int = Field(strict=True, ge=0)
    log_index: int = Field(strict=True, ge=0)
    from_address: EvmAddress
    to_address: EvmAddress
    amount_smallest_unit: str = Field(pattern=r"^(0|[1-9][0-9]{0,77})$")

    @field_validator("amount_smallest_unit")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        if int(value) >= 2**256:
            raise ValueError("Transfer amount must fit in uint256.")
        return value


class Erc20TransferActivityResponse(ApiModel):
    network: str
    chain_id: int = Field(strict=True, gt=0)
    provider: str
    token_address: EvmAddress
    owner_address: EvmAddress
    from_block: int = Field(strict=True, ge=0)
    to_block: int = Field(strict=True, ge=0)
    events: list[Erc20TransferEvent]
    evidence_id: str = Field(pattern=r"^evidence:[0-9a-f]{64}$")
    findings: list[RiskFinding]
    observed_at: AwareDatetime
    limitations: list[str]

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        if self.to_block < self.from_block:
            raise ValueError("Activity range is reversed.")
        if len(self.events) > 100:
            raise ValueError("Too many activity events.")
        if any(finding.evidence_ids != [self.evidence_id] for finding in self.findings):
            raise ValueError("Activity findings must reference the activity evidence.")
        return self


class Erc20AllowanceResponse(ApiModel):
    evidence: Erc20AllowanceEvidence
    findings: list[RiskFinding]
    limitations: list[str]
