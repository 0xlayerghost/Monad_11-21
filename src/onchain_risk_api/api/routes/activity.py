from typing import Annotated

from fastapi import APIRouter, Depends, Query

from onchain_risk_api.api.dependencies import get_transfer_activity_service
from onchain_risk_api.domain.models import Erc20TransferActivityResponse, ErrorResponse
from onchain_risk_api.domain.validation import EvmAddress
from onchain_risk_api.services.transfer_activity import TransferActivityService

router = APIRouter(prefix="/networks/{network_name}/tokens", tags=["activity"])


@router.get(
    "/{token_address}/activity",
    response_model=Erc20TransferActivityResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_erc20_activity(
    network_name: str, token_address: EvmAddress, owner: EvmAddress,
    service: Annotated[TransferActivityService, Depends(get_transfer_activity_service)],
    from_block: Annotated[int, Query(alias="fromBlock", ge=0)],
    to_block: Annotated[int, Query(alias="toBlock", ge=0)],
) -> Erc20TransferActivityResponse:
    return await service.get_activity(
        token_address, owner, from_block=from_block, to_block=to_block, network_name=network_name,
    )
