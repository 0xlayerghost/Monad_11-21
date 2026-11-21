from typing import Annotated

from fastapi import APIRouter, Depends

from onchain_risk_api.api.dependencies import get_investigation_runner
from onchain_risk_api.domain.models import ApiError
from onchain_risk_api.llm.models import AgentResult, InvestigationRequest
from onchain_risk_api.llm.runner import InvestigationRunner

router = APIRouter(prefix="/investigations", tags=["investigations"])


@router.post("", response_model=AgentResult)
async def create_investigation(
    body: InvestigationRequest,
    runner: Annotated[InvestigationRunner | None, Depends(get_investigation_runner)],
) -> AgentResult:
    if runner is None:
        return AgentResult(
            status="error",
            stop_reason="LLM_NOT_CONFIGURED",
            error=ApiError(
                code="LLM_NOT_CONFIGURED",
                message="Configure the server-side LLM settings before running investigations.",
            ),
        )
    return await runner.run(body.prompt)
