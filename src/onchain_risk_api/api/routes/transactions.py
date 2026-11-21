from typing import Annotated

from fastapi import APIRouter, Depends

from onchain_risk_api.api.dependencies import get_transaction_service
from onchain_risk_api.domain.models import ErrorResponse, TransactionReceiptResponse
from onchain_risk_api.domain.validation import TransactionHash
from onchain_risk_api.services.transaction import TransactionService

router = APIRouter(prefix="/networks/{network_name}/transactions", tags=["transactions"])


@router.get(
    "/{transaction_hash}/receipt",
    response_model=TransactionReceiptResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Network or transaction not found."},
        422: {"model": ErrorResponse, "description": "Invalid transaction hash."},
        503: {"model": ErrorResponse, "description": "RPC, receipt or snapshot unavailable."},
    },
)
async def get_transaction_receipt(
    network_name: str,
    transaction_hash: TransactionHash,
    service: Annotated[TransactionService, Depends(get_transaction_service)],
) -> TransactionReceiptResponse:
    return await service.get_receipt(transaction_hash, network_name=network_name)
