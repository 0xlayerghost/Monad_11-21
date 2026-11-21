from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from onchain_risk_api.domain.models import (
    ApiError,
    ApiModel,
    Erc20AllowanceResponse,
    Erc20BalanceResponse,
    Erc20TransferActivityResponse,
    NativeBalanceResponse,
    TransactionReceiptResponse,
)
from onchain_risk_api.domain.validation import EvmAddress, TransactionHash


class ToolArguments(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    network_name: str = Field(
        pattern=r"^[a-z0-9][a-z0-9-]{0,62}$",
        description="The single network configured for this service, not a chain ID.",
    )


class NativeBalanceArguments(ToolArguments):
    address: EvmAddress
    block_number: int | None = Field(
        default=None, ge=0, description="Explicit block height, or null for latest."
    )


class TransactionReceiptArguments(ToolArguments):
    transaction_hash: TransactionHash


class Erc20BalanceArguments(ToolArguments):
    token_address: EvmAddress
    owner_address: EvmAddress
    block_number: int | None = Field(
        default=None, ge=0, description="Explicit block height, or null for latest."
    )



class Erc20TransferActivityArguments(ToolArguments):
    token_address: EvmAddress
    owner_address: EvmAddress
    from_block: int = Field(ge=0, description="First block in the bounded activity range.")
    to_block: int = Field(ge=0, description="Last block in the bounded activity range.")

class Erc20AllowanceArguments(ToolArguments):
    token_address: EvmAddress
    owner_address: EvmAddress
    spender_address: EvmAddress
    block_number: int | None = Field(
        default=None, ge=0, description="Explicit block height, or null for latest."
    )


class ToolDefinition(ApiModel):
    name: str
    description: str
    read_only: Literal[True] = True
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class ToolCallResult(ApiModel):
    tool_name: str
    status: Literal["ok", "error"]
    data: (
        NativeBalanceResponse | TransactionReceiptResponse
        | Erc20AllowanceResponse | Erc20BalanceResponse | Erc20TransferActivityResponse | None
    ) = None
    error: ApiError | None = None

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status == "ok" and (self.data is None or self.error is not None):
            raise ValueError("Successful tool results require data and no error.")
        if self.status == "error" and (self.data is not None or self.error is None):
            raise ValueError("Failed tool results require an error and no data.")
        return self
