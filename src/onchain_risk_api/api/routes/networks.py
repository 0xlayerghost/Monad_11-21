from typing import Annotated

from fastapi import APIRouter, Depends

from onchain_risk_api.api.dependencies import get_network_service
from onchain_risk_api.domain.models import NetworkStatusResponse
from onchain_risk_api.services.network import NetworkService

router = APIRouter(prefix="/networks", tags=["networks"])


@router.get("/{network_name}/status", response_model=NetworkStatusResponse)
async def get_configured_network_status(
    network_name: str,
    service: Annotated[NetworkService, Depends(get_network_service)],
) -> NetworkStatusResponse:
    return await service.get_status(network_name=network_name)
