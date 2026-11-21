from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from onchain_risk_api.domain.errors import QueryError
from onchain_risk_api.domain.failures import describe_query_error
from onchain_risk_api.domain.models import (
    ApiError,
    Erc20AllowanceResponse,
    Erc20BalanceResponse,
    Erc20TransferActivityResponse,
    NativeBalanceResponse,
    TransactionReceiptResponse,
)
from onchain_risk_api.services.allowance import AllowanceService
from onchain_risk_api.services.balance import BalanceService
from onchain_risk_api.services.token_balance import TokenBalanceService
from onchain_risk_api.services.transaction import TransactionService
from onchain_risk_api.services.transfer_activity import TransferActivityService
from onchain_risk_api.tools.models import (
    Erc20AllowanceArguments,
    Erc20BalanceArguments,
    Erc20TransferActivityArguments,
    NativeBalanceArguments,
    ToolCallResult,
    ToolDefinition,
    TransactionReceiptArguments,
)


@dataclass(frozen=True)
class _ToolContract:
    description: str
    arguments: type[BaseModel]
    response: (
        type[NativeBalanceResponse] | type[TransactionReceiptResponse]
        | type[Erc20AllowanceResponse] | type[Erc20BalanceResponse]
        | type[Erc20TransferActivityResponse]
    )


_CONTRACTS = {
    "get_erc20_balance": _ToolContract(
        description=(
            "Read balanceOf(owner) for one configured ERC-20 token at a verified block. "
            "Requires token and owner only, never spender. A non-empty token allowlist restricts "
            "queries; an empty token list permits any valid token address. "
            "Returns an exact smallest-unit string and evidence; decimals and formatted "
            "balance may be unknown, with a metadata error. Never assume 18 decimals. "
            "Does not enumerate holdings, read allowances, sign or send transactions."
        ),
        arguments=Erc20BalanceArguments,
        response=Erc20BalanceResponse,
    ),
    "get_erc20_allowance": _ToolContract(
        description=(
            "Read one ERC-20 token/owner/spender allowance on the configured network at a "
            "verified block. A non-empty token allowlist restricts tokens; an empty token list "
            "permits any valid token address. The spender must always be configured. Ask for all "
            "three addresses if missing. Returns an exact "
            "smallest-unit string, "
            "evidence and deterministic findings. Empty findings do not mean safe. "
            "Does not discover approvals, read token balances, sign or send transactions."
        ),
        arguments=Erc20AllowanceArguments,
        response=Erc20AllowanceResponse,
    ),
    "get_erc20_transfer_activity": _ToolContract(
        description=(
            "Read bounded ERC-20 Transfer logs involving one owner and token. A non-empty token "
            "allowlist restricts tokens; an empty token list permits any valid token address. "
            "The caller must provide token, owner, and an explicit block range. The range is "
            "limited to 2,000 blocks and 100 events. Deterministic findings flag zero-address "
            "source or destination event shapes only; they do not prove minting, burning, supply "
            "changes, standards compliance or safety. Empty findings do not mean safe. The tool "
            "does not derive current balance, allowance, price, or finality."
        ),
        arguments=Erc20TransferActivityArguments,
        response=Erc20TransferActivityResponse,
    ),
    "get_native_balance": _ToolContract(
        description=(
            "Read one address's native-asset balance on the configured network at a "
            "verified block. Returns exact amounts and block provenance, not token holdings."
        ),
        arguments=NativeBalanceArguments,
        response=NativeBalanceResponse,
    ),
    "get_transaction_receipt": _ToolContract(
        description=(
            "Read one transaction receipt on the configured network. Distinguishes "
            "pending, mined success/revert and not-found. Does not establish finality or safety."
        ),
        arguments=TransactionReceiptArguments,
        response=TransactionReceiptResponse,
    ),
}


def get_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=name,
            description=contract.description,
            input_schema=contract.arguments.model_json_schema(),
            output_schema=contract.response.model_json_schema(mode="serialization"),
        )
        for name, contract in _CONTRACTS.items()
    ]


class ReadOnlyToolRegistry:
    def __init__(
        self, *, balance_service: BalanceService, transaction_service: TransactionService,
        allowance_service: AllowanceService,
        token_balance_service: TokenBalanceService,
        transfer_activity_service: TransferActivityService,
    ) -> None:
        self._handlers: dict[
            str, Callable[..., Awaitable[
                NativeBalanceResponse | TransactionReceiptResponse
                | Erc20AllowanceResponse | Erc20BalanceResponse
                | Erc20TransferActivityResponse
            ]]
        ] = {
            "get_erc20_balance": token_balance_service.get_token_balance,
            "get_erc20_allowance": allowance_service.get_allowance,
            "get_erc20_transfer_activity": transfer_activity_service.get_activity,
            "get_native_balance": balance_service.get_native_balance,
            "get_transaction_receipt": transaction_service.get_receipt,
        }

    async def execute(self, name: str, arguments: object) -> ToolCallResult:
        contract = _CONTRACTS.get(name)
        if contract is None:
            return ToolCallResult(
                tool_name=name, status="error",
                error=ApiError(
                    code="UNKNOWN_TOOL", message="The requested tool is not registered."
                ),
            )

        try:
            if isinstance(arguments, str):
                parameters = contract.arguments.model_validate_json(arguments)
            else:
                parameters = contract.arguments.model_validate(arguments)
        except ValidationError:
            return ToolCallResult(
                tool_name=name, status="error",
                error=ApiError(
                    code="INVALID_TOOL_ARGUMENTS", message="Tool arguments are invalid."
                ),
            )

        try:
            result = await self._handlers[name](**parameters.model_dump())
            data = contract.response.model_validate(result)
            return ToolCallResult(tool_name=name, status="ok", data=data)
        except QueryError as exc:
            _, error = describe_query_error(exc)
            return ToolCallResult(tool_name=name, status="error", error=error)
        except Exception:
            return ToolCallResult(
                tool_name=name, status="error",
                error=ApiError(
                    code="TOOL_EXECUTION_FAILED", message="The tool could not complete its query."
                ),
            )
