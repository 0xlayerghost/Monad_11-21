from typing import Annotated

from pydantic import AfterValidator, StringConstraints
from web3 import Web3


def normalize_address(address: str) -> str:
    body = address[2:]
    if not (body.islower() or body.isupper() or body.isdigit()):
        if not Web3.is_checksum_address(address):
            raise ValueError("Mixed-case addresses must have a valid EIP-55 checksum.")
    return Web3.to_checksum_address(address)


EvmAddress = Annotated[
    str,
    StringConstraints(pattern=r"^0x[0-9a-fA-F]{40}$"),
    AfterValidator(normalize_address),
]

TransactionHash = Annotated[
    str,
    StringConstraints(pattern=r"^0x[0-9a-fA-F]{64}$"),
    AfterValidator(str.lower),
]
