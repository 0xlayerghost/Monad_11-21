from typing import Annotated

from fastapi import APIRouter, Depends, Query

from onchain_risk_api.api.dependencies import get_token_balance_service
from onchain_risk_api.domain.models import Erc20BalanceResponse, ErrorResponse
from onchain_risk_api.domain.validation import EvmAddress
from onchain_risk_api.services.token_balance import TokenBalanceService

router = APIRouter(prefix="/networks/{network_name}/tokens", tags=["token-balances"])


@router.get(
    "/{token_address}/balance",
    response_model=Erc20BalanceResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Network, token or block not found."},
        422: {"model": ErrorResponse, "description": "Invalid input or token call failure."},
        503: {"model": ErrorResponse, "description": "RPC, chain or snapshot unavailable."},
    },
)
async def get_erc20_balance(
    network_name: str, token_address: EvmAddress, owner: EvmAddress,
    service: Annotated[TokenBalanceService, Depends(get_token_balance_service)],
    block_number: Annotated[int | None, Query(alias="blockNumber", ge=0)] = None,
) -> Erc20BalanceResponse:
    return await service.get_token_balance(
        token_address, owner, network_name=network_name, block_number=block_number,
    )
