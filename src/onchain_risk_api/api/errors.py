from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from onchain_risk_api.domain.errors import QueryError
from onchain_risk_api.domain.failures import describe_query_error
from onchain_risk_api.domain.models import ApiError, ErrorResponse


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, int | str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(error=ApiError(code=code, message=message, details=details))
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(QueryError)
    async def handle_query_error(_: Request, exc: QueryError) -> JSONResponse:
        status_code, error = describe_query_error(exc)
        return _error_response(
            status_code=status_code,
            code=error.code,
            message=error.message,
            details=error.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request parameters are invalid.",
        )
