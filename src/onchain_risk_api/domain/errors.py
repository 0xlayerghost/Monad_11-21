class QueryError(Exception):
    pass


class ChainMismatchError(QueryError):
    def __init__(self, *, expected_chain_id: int, actual_chain_id: int) -> None:
        self.expected_chain_id = expected_chain_id
        self.actual_chain_id = actual_chain_id
        super().__init__(
            f"Expected chain ID {expected_chain_id}, received {actual_chain_id}."
        )


class NetworkNotConfiguredError(QueryError):
    pass


class RpcUnavailableError(QueryError):
    def __init__(self, *, provider_name: str) -> None:
        self.provider_name = provider_name
        super().__init__(f"RPC provider {provider_name} is unavailable.")


class BlockNotFoundError(QueryError):
    pass


class SnapshotChangedError(QueryError):
    pass


class TransactionNotFoundError(QueryError):
    pass


class ReceiptUnavailableError(QueryError):
    pass


class TokenNotConfiguredError(QueryError):
    pass


class SpenderNotConfiguredError(QueryError):
    pass


class TokenCallFailedError(QueryError):
    pass


class BlockRangeTooLargeError(QueryError):
    pass


class ActivityLimitExceededError(QueryError):
    pass
