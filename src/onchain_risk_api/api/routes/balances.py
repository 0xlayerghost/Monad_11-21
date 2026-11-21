from typing import Annotated

from fastapi import APIRouter, Depends, Query

from onchain_risk_api.api.dependencies import get_balance_service
from onchain_risk_api.domain.models import ErrorResponse, NativeBalanceResponse
from onchain_risk_api.domain.validation import EvmAddress
from onchain_risk_api.services.balance import BalanceService

router = APIRouter(prefix="/networks/{network_name}/addresses", tags=["balances"])


@router.get(
    "/{address}/balance",
    response_model=NativeBalanceResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Requested block was not found."},
        422: {"model": ErrorResponse, "description": "Invalid address or block number."},
        503: {"model": ErrorResponse, "description": "RPC, network or snapshot unavailable."},
    },
)
async def get_native_balance(
    network_name: str,
    address: EvmAddress,
    service: Annotated[BalanceService, Depends(get_balance_service)],
    block_number: Annotated[int | None, Query(alias="blockNumber", ge=0)] = None,
) -> NativeBalanceResponse:
    return await service.get_native_balance(
        address, network_name=network_name, block_number=block_number
    )
