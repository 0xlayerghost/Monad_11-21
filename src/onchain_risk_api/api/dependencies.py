from collections.abc import AsyncIterator

import httpx
from fastapi import Request
from pydantic import ValidationError

from onchain_risk_api.llm.config import LlmSettings
from onchain_risk_api.llm.http import model_client_options
from onchain_risk_api.llm.provider import OpenAIResponsesProvider
from onchain_risk_api.llm.runner import InvestigationRunner
from onchain_risk_api.services.allowance import AllowanceService
from onchain_risk_api.services.balance import BalanceService
from onchain_risk_api.services.network import NetworkService
from onchain_risk_api.services.token_balance import TokenBalanceService
from onchain_risk_api.services.transaction import TransactionService
from onchain_risk_api.services.transfer_activity import TransferActivityService


def get_token_balance_service(request: Request) -> TokenBalanceService:
    return request.app.state.token_balance_service


def get_transfer_activity_service(request: Request) -> TransferActivityService:
    return request.app.state.transfer_activity_service


def get_allowance_service(request: Request) -> AllowanceService:
    return request.app.state.allowance_service


def get_network_service(request: Request) -> NetworkService:
    return request.app.state.network_service


def get_balance_service(request: Request) -> BalanceService:
    return request.app.state.balance_service


def get_transaction_service(request: Request) -> TransactionService:
    return request.app.state.transaction_service


async def get_investigation_runner(
    request: Request,
) -> AsyncIterator[InvestigationRunner | None]:
    if hasattr(request.app.state, "investigation_runner"):
        yield request.app.state.investigation_runner
        return
    try:
        settings = LlmSettings()  # type: ignore[call-arg]
    except ValidationError:
        yield None
        return
    async with httpx.AsyncClient(**model_client_options(settings)) as client:
        yield InvestigationRunner(
            settings=settings,
            provider=OpenAIResponsesProvider(settings=settings, client=client),
            tools=request.app.state.tool_registry,
            network_name=request.app.state.settings.network_name,
            chain_id=request.app.state.settings.expected_chain_id,
        )
