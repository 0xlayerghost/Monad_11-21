import json


def token_balance_identity(
    *, chain_id: int, block_number: int, block_hash: str,
    token_address: str, owner_address: str, balance_smallest_unit: str,
    decimals: int | None,
) -> str:
    return json.dumps([
        "erc20-balance", "v1", chain_id, block_number, block_hash.lower(),
        token_address.lower(), owner_address.lower(), balance_smallest_unit, decimals,
    ], separators=(",", ":"))
