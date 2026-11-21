from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from onchain_risk_api import __version__
from onchain_risk_api.api.errors import register_exception_handlers
from onchain_risk_api.api.routes import (
    activity,
    allowances,
    balances,
    health,
    investigations,
    networks,
    token_balances,
    transactions,
)
from onchain_risk_api.core.config import Settings
from onchain_risk_api.providers.base import ChainProvider
from onchain_risk_api.providers.web3_rpc import Web3RpcProvider
from onchain_risk_api.services.allowance import AllowanceService
from onchain_risk_api.services.balance import BalanceService
from onchain_risk_api.services.network import NetworkService
from onchain_risk_api.services.token_balance import TokenBalanceService
from onchain_risk_api.services.transaction import TransactionService
from onchain_risk_api.services.transfer_activity import TransferActivityService
from onchain_risk_api.tools.registry import ReadOnlyToolRegistry
from onchain_risk_api.web.routes import STATIC_DIRECTORY
from onchain_risk_api.web.routes import router as web_router


def create_app(
    settings: Settings | None = None,
    provider: ChainProvider | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()  # type: ignore[call-arg]
    resolved_provider = provider or Web3RpcProvider(
        rpc_url=str(resolved_settings.rpc_url),
        timeout_seconds=resolved_settings.rpc_timeout_seconds,
        provider_name=resolved_settings.rpc_provider_name,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await resolved_provider.close()

    app = FastAPI(
        title="Onchain Risk API",
        version=__version__,
        description=(
            "Read-only configured EVM chain data with explicit provenance and failure states."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.network_service = NetworkService(
        settings=resolved_settings,
        provider=resolved_provider,
    )
    app.state.balance_service = BalanceService(
        settings=resolved_settings,
        provider=resolved_provider,
    )
    app.state.transaction_service = TransactionService(
        settings=resolved_settings,
        provider=resolved_provider,
    )
    app.state.allowance_service = AllowanceService(
        settings=resolved_settings,
        provider=resolved_provider,
    )
    app.state.token_balance_service = TokenBalanceService(
        settings=resolved_settings, provider=resolved_provider,
    )
    app.state.transfer_activity_service = TransferActivityService(
        settings=resolved_settings, provider=resolved_provider,
    )
    app.state.tool_registry = ReadOnlyToolRegistry(
        token_balance_service=app.state.token_balance_service,
        allowance_service=app.state.allowance_service,
        balance_service=app.state.balance_service,
        transaction_service=app.state.transaction_service,
        transfer_activity_service=app.state.transfer_activity_service,
    )
    app.include_router(health.router)
    app.include_router(networks.router, prefix="/v1")
    app.include_router(balances.router, prefix="/v1")
    app.include_router(allowances.router, prefix="/v1")
    app.include_router(token_balances.router, prefix="/v1")
    app.include_router(activity.router, prefix="/v1")
    app.include_router(transactions.router, prefix="/v1")
    app.include_router(investigations.router, prefix="/v1")
    app.include_router(web_router)
    assets_directory = STATIC_DIRECTORY / "assets"
    if assets_directory.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_directory), name="web-assets")
    register_exception_handlers(app)
    return app
