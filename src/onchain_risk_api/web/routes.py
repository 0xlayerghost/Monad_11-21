from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from onchain_risk_api.domain.models import ApiModel

STATIC_DIRECTORY = Path(__file__).parent / "static"
router = APIRouter()


class UiConfigResponse(ApiModel):
    network_name: str
    expected_chain_id: int
    native_symbol: str
    native_decimals: int
    provider: str


@router.get("/", include_in_schema=False, response_model=None)
async def workbench() -> FileResponse | HTMLResponse:
    headers = {
        "Cache-Control": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        ),
    }
    index = STATIC_DIRECTORY / "index.html"
    if not index.is_file():
        return HTMLResponse(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<title>链上手记</title><h1>前端尚未构建</h1>'
            '<p>进入项目的 frontend 文件夹，运行 npm ci 和 npm run build，'
            '然后重启后端。</p><p><a href="/docs">API 文档仍可使用</a></p></html>',
            status_code=503,
            headers=headers,
        )
    return FileResponse(index, headers=headers)


@router.get("/v1/ui/config", response_model=UiConfigResponse, tags=["workbench"])
async def ui_config(request: Request) -> UiConfigResponse:
    settings = request.app.state.settings
    return UiConfigResponse(
        network_name=settings.network_name,
        expected_chain_id=settings.expected_chain_id,
        native_symbol=settings.native_symbol,
        native_decimals=settings.native_decimals,
        provider=settings.rpc_provider_name,
    )
