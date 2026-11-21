from typing import Annotated

from fastapi import APIRouter, Depends, Query

from onchain_risk_api.api.dependencies import get_allowance_service
from onchain_risk_api.domain.models import Erc20AllowanceResponse, ErrorResponse
from onchain_risk_api.domain.validation import EvmAddress
from onchain_risk_api.services.allowance import AllowanceService

router = APIRouter(prefix="/networks/{network_name}/tokens", tags=["allowances"])


@router.get(
    "/{token_address}/allowance",
    response_model=Erc20AllowanceResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Network, token, spender or block not found."},
        422: {"model": ErrorResponse, "description": "Invalid input or token call failure."},
        503: {"model": ErrorResponse, "description": "RPC, chain or snapshot unavailable."},
    },
)
async def get_erc20_allowance(
    network_name: str,
    token_address: EvmAddress,
    owner: EvmAddress,
    spender: EvmAddress,
    service: Annotated[AllowanceService, Depends(get_allowance_service)],
    block_number: Annotated[int | None, Query(alias="blockNumber", ge=0)] = None,
) -> Erc20AllowanceResponse:
    return await service.get_allowance(
        token_address,
        owner,
        spender,
        network_name=network_name,
        block_number=block_number,
    )
