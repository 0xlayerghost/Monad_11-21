from fastapi import APIRouter, Request

from onchain_risk_api.domain.models import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.service_version,
    )
