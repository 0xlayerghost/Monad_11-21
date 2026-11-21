def allowance_identity(
    *, chain_id: int, block_number: int, block_hash: str,
    token_address: str, owner_address: str, spender_address: str,
    allowance_smallest_unit: str,
) -> str:
    return ":".join([
        "erc20-allowance", "v1", str(chain_id), str(block_number), block_hash.lower(),
        token_address.lower(), owner_address.lower(), spender_address.lower(),
        allowance_smallest_unit,
    ])
