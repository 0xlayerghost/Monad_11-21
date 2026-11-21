from onchain_risk_api.domain.errors import (
    ActivityLimitExceededError,
    BlockNotFoundError,
    BlockRangeTooLargeError,
    ChainMismatchError,
    NetworkNotConfiguredError,
    QueryError,
    ReceiptUnavailableError,
    RpcUnavailableError,
    SnapshotChangedError,
    SpenderNotConfiguredError,
    TokenCallFailedError,
    TokenNotConfiguredError,
    TransactionNotFoundError,
)
from onchain_risk_api.domain.models import ApiError


def describe_query_error(exc: QueryError) -> tuple[int, ApiError]:
    if isinstance(exc, ChainMismatchError):
        return 503, ApiError(
            code="CHAIN_ID_MISMATCH",
            message="RPC network does not match the configured network.",
            details={
                "expectedChainId": exc.expected_chain_id,
                "actualChainId": exc.actual_chain_id,
            },
        )
    if isinstance(exc, RpcUnavailableError):
        return 503, ApiError(
            code="RPC_UNAVAILABLE",
            message="The configured RPC provider is temporarily unavailable.",
            details={"provider": exc.provider_name},
        )
    errors = (
        (
            BlockRangeTooLargeError, 422, "BLOCK_RANGE_TOO_LARGE",
            "The requested block range exceeds the configured activity limit.",
        ),
        (
            ActivityLimitExceededError, 422, "ACTIVITY_LIMIT_EXCEEDED",
            "The requested activity exceeds the configured result limit.",
        ),
        (
            TokenNotConfiguredError, 404, "TOKEN_NOT_CONFIGURED",
            "The requested token is not configured for ERC-20 queries.",
        ),
        (
            SpenderNotConfiguredError, 404, "SPENDER_NOT_CONFIGURED",
            "The requested spender is not configured for allowance queries.",
        ),
        (
            TokenCallFailedError, 422, "TOKEN_CALL_FAILED",
            "The token call reverted or did not return a decodable result.",
        ),
        (
            NetworkNotConfiguredError, 404, "NETWORK_NOT_CONFIGURED",
            "The requested network is not configured on this service.",
        ),
        (BlockNotFoundError, 404, "BLOCK_NOT_FOUND", "The requested block was not found."),
        (
            SnapshotChangedError, 503, "SNAPSHOT_CHANGED",
            "The selected block changed during the query. Retry the request.",
        ),
        (
            TransactionNotFoundError, 404, "TRANSACTION_NOT_FOUND",
            "The configured RPC provider did not find the transaction.",
        ),
        (
            ReceiptUnavailableError, 503, "RECEIPT_UNAVAILABLE",
            "The transaction is mined but its receipt is not currently available.",
        ),
    )
    for error_type, status_code, code, message in errors:
        if isinstance(exc, error_type):
            return status_code, ApiError(code=code, message=message)
    return 503, ApiError(code="QUERY_UNAVAILABLE", message="The query is currently unavailable.")
