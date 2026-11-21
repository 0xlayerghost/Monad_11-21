from datetime import UTC, datetime
from typing import Literal

from web3 import AsyncWeb3, Web3
from web3.exceptions import (
    BadFunctionCallOutput,
    BlockNotFound,
    ContractLogicError,
    TransactionNotFound,
)
from web3.providers.rpc import AsyncHTTPProvider

from onchain_risk_api.domain.errors import (
    BlockNotFoundError,
    RpcUnavailableError,
    TokenCallFailedError,
)
from onchain_risk_api.domain.models import (
    BlockSnapshot,
    Erc20TransferEvent,
    TransactionReceiptSnapshot,
    TransactionSnapshot,
)

ERC20_ALLOWANCE_ABI = [
    {
        "type": "function",
        "name": "allowance",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]
TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()


class Web3RpcProvider:
    def __init__(
        self, *, rpc_url: str, timeout_seconds: float, provider_name: str = "custom"
    ) -> None:
        self._provider_name = provider_name
        self._web3 = AsyncWeb3(
            AsyncHTTPProvider(
                rpc_url,
                request_kwargs={"timeout": timeout_seconds},
                exception_retry_configuration=None,
            )
        )

    async def get_chain_id(self) -> int:
        try:
            return await self._web3.eth.chain_id
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def get_block(self, block_identifier: int | Literal["latest"]) -> BlockSnapshot:
        try:
            block = await self._web3.eth.get_block(block_identifier)
            snapshot = BlockSnapshot(
                number=block["number"],
                block_hash=Web3.to_hex(block["hash"]),
                timestamp=datetime.fromtimestamp(block["timestamp"], UTC),
            )
            if isinstance(block_identifier, int) and snapshot.number != block_identifier:
                raise ValueError("RPC returned a different block number.")
            return snapshot
        except BlockNotFound as exc:
            raise BlockNotFoundError() from exc
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def get_balance(self, address: str, *, block_number: int) -> int:
        try:
            balance = await self._web3.eth.get_balance(
                Web3.to_checksum_address(address), block_identifier=block_number
            )
            if type(balance) is not int or not 0 <= balance < 2**256:
                raise ValueError("RPC returned an invalid native balance.")
            return balance
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def get_erc20_allowance(
        self,
        token_address: str,
        owner_address: str,
        spender_address: str,
        *,
        block_number: int,
    ) -> int:
        try:
            contract = self._web3.eth.contract(
                address=Web3.to_checksum_address(token_address), abi=ERC20_ALLOWANCE_ABI
            )
            allowance = await contract.functions.allowance(
                Web3.to_checksum_address(owner_address),
                Web3.to_checksum_address(spender_address),
            ).call(block_identifier=block_number)
            if type(allowance) is not int or not 0 <= allowance < 2**256:
                raise ValueError("RPC returned an invalid allowance.")
            return allowance
        except (BadFunctionCallOutput, ContractLogicError) as exc:
            raise TokenCallFailedError() from exc
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def _read_token_uint(
        self, token_address: str, function_name: str, arguments: list[str],
        *, block_number: int, bits: int,
    ) -> int:
        abi = [{
            "type": "function", "name": function_name, "stateMutability": "view",
            "inputs": [{"name": "owner", "type": "address"}] if arguments else [],
            "outputs": [{"name": "", "type": f"uint{bits}"}],
        }]
        try:
            contract = self._web3.eth.contract(
                address=Web3.to_checksum_address(token_address), abi=abi,
            )
            function = getattr(contract.functions, function_name)
            value = await function(*arguments).call(block_identifier=block_number)
            if type(value) is not int or not 0 <= value < 2**bits:
                raise ValueError("Invalid token integer result.")
            return value
        except (BadFunctionCallOutput, ContractLogicError) as exc:
            raise TokenCallFailedError() from exc
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def get_erc20_balance(
        self, token_address: str, owner_address: str, *, block_number: int,
    ) -> int:
        return await self._read_token_uint(
            token_address, "balanceOf", [Web3.to_checksum_address(owner_address)],
            block_number=block_number, bits=256,
        )

    async def get_erc20_decimals(self, token_address: str, *, block_number: int) -> int:
        return await self._read_token_uint(
            token_address, "decimals", [], block_number=block_number, bits=8,
        )

    async def get_erc20_transfer_logs(
        self, token_address: str, owner_address: str, *, from_block: int, to_block: int,
    ) -> list[Erc20TransferEvent]:
        try:
            address = Web3.to_checksum_address(token_address)
            owner_topic = "0x" + owner_address[2:].lower().rjust(64, "0")
            logs = []
            for indexed_position in (1, 2):
                logs.extend(await self._web3.eth.get_logs({
                    "address": address, "fromBlock": from_block, "toBlock": to_block,
                    "topics": [TRANSFER_TOPIC, owner_topic] if indexed_position == 1
                    else [TRANSFER_TOPIC, None, owner_topic],
                }))
            events = []
            for log in logs:
                topics = log["topics"]
                if len(topics) != 3 or len(log["data"]) != 66:
                    raise ValueError("Malformed Transfer log.")
                from_address = Web3.to_checksum_address("0x" + Web3.to_hex(topics[1])[-40:])
                to_address = Web3.to_checksum_address("0x" + Web3.to_hex(topics[2])[-40:])
                data = log["data"]
                amount = int(data, 16) if isinstance(data, str) else int.from_bytes(data, "big")
                events.append(Erc20TransferEvent(
                    transaction_hash=Web3.to_hex(log["transactionHash"]),
                    block_number=log["blockNumber"], log_index=log["logIndex"],
                    from_address=from_address, to_address=to_address,
                    amount_smallest_unit=str(amount),
                ))
            unique = {(event.transaction_hash, event.log_index): event for event in events}
            return sorted(unique.values(), key=lambda event: (event.block_number, event.log_index))
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def get_transaction(self, transaction_hash: str) -> TransactionSnapshot | None:
        try:
            transaction = await self._web3.eth.get_transaction(transaction_hash)
            if transaction is None:
                return None
            snapshot = TransactionSnapshot(
                transaction_hash=Web3.to_hex(transaction["hash"]),
                block_number=transaction["blockNumber"],
                block_hash=(
                    Web3.to_hex(transaction["blockHash"])
                    if transaction["blockHash"] is not None
                    else None
                ),
            )
            if snapshot.transaction_hash != transaction_hash.lower():
                raise ValueError("RPC returned a different transaction hash.")
            return snapshot
        except TransactionNotFound:
            return None
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def get_transaction_receipt(
        self, transaction_hash: str
    ) -> TransactionReceiptSnapshot | None:
        try:
            receipt = await self._web3.eth.get_transaction_receipt(transaction_hash)
            if receipt is None:
                return None
            snapshot = TransactionReceiptSnapshot(
                transaction_hash=Web3.to_hex(receipt["transactionHash"]),
                block_number=receipt["blockNumber"],
                block_hash=Web3.to_hex(receipt["blockHash"]),
                transaction_index=receipt["transactionIndex"],
                status=receipt["status"],
                from_address=receipt["from"],
                to_address=receipt["to"],
                contract_address=receipt["contractAddress"],
                gas_used=receipt["gasUsed"],
                effective_gas_price=receipt.get("effectiveGasPrice"),
            )
            if snapshot.transaction_hash != transaction_hash.lower():
                raise ValueError("RPC returned a receipt for a different transaction.")
            return snapshot
        except TransactionNotFound:
            return None
        except Exception as exc:
            raise RpcUnavailableError(provider_name=self._provider_name) from exc

    async def close(self) -> None:
        await self._web3.provider.disconnect()
