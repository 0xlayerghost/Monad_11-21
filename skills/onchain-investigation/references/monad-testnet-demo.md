# Monad testnet CLI demo

This is a local integration example for an agent that can execute the repository's CLI. It does not establish Agent Hub installation or discovery. No contract or protocol identity is attributed to the addresses below.

## Verified public sample

On 2026-11-21, `https://monad-testnet.drpc.org` and `https://testnet-rpc.monad.xyz` both returned `eth_chainId = 0x279f` (10143). Both returned the same block hash and receipt status for the transaction below. The first RPC was used by the project's CLI; the second independently returned `eth_getBalance = 0x6f1d3e1b6a1e000` for the owner at that block.

| Field | Fixed value |
| --- | --- |
| Network | `monad-testnet`, chain ID `10143` |
| Block | `81521391` (`0x4dbeaef`) |
| Block hash | `0xdd248f95b73a77e1c203699243b778760291926d685be0ccf8ca5047ff47ab42` |
| Transaction | `0xbb02e99311baec22c63e6cd49fb15da5ba3dd430aee32fd9be6aa899a349fe9b` |
| Owner | `0x6f49a8F621353f12378d0046E7d7e4b9B249DC9e` |
| Receipt status | `0x1`, reported by CLI as `executionStatus: success` |
| Owner balance at block | `500414000000000000` smallest units, reported as `0.500414000000000000 MON` |

The receipt demonstrates EVM execution success only. The balance is a historical snapshot and may differ from the current balance. The sample may become unavailable from RPC providers that prune historical state.

## Run locally

Create the repository `.venv` and install the project dependencies as described in the root README first. The commands below use the public testnet configuration explicitly and run from `src` so the CLI does not load the repository root `.env` by relative path. Do not read, print, or copy a real `.env`. In PowerShell from the repository root:

```powershell
$env:RPC_URL = 'https://monad-testnet.drpc.org'
$env:EXPECTED_CHAIN_ID = '10143'
$env:NETWORK_NAME = 'monad-testnet'
$env:NATIVE_SYMBOL = 'MON'
$env:NATIVE_DECIMALS = '18'
$env:RPC_PROVIDER_NAME = 'drpc'
$env:ERC20_ALLOWED_TOKENS = '[]'
$env:ERC20_ALLOWED_SPENDERS = '[]'
Push-Location .\src
$python = '..\.venv\Scripts\python.exe'
& $python -m onchain_risk_api.tools list
$receipt = '{"network_name":"monad-testnet","transaction_hash":"0xbb02e99311baec22c63e6cd49fb15da5ba3dd430aee32fd9be6aa899a349fe9b"}'
$receipt | & $python -m onchain_risk_api.tools call get_transaction_receipt -
$balance = '{"network_name":"monad-testnet","address":"0x6f49a8F621353f12378d0046E7d7e4b9B249DC9e","block_number":81521391}'
$balance | & $python -m onchain_risk_api.tools call get_native_balance -
Pop-Location
```

`list` should report five read-only tools. For the two `call` results, check outer `status: ok`, `chainId: 10143`, the fixed block hash, and the values above. `observedAt` changes on every query. If a query fails, report its error code and leave the fact unknown; do not use the table as a substitute for a live response.

Example conclusion after those calls succeed:

- **Facts:** On Monad testnet (10143), transaction `0xbb02...9fe9b` was included in block `81521391` with hash `0xdd24...ab42`; the receipt reported `executionStatus: success`. At the same block, `0x6f49...DC9e` had `500414000000000000` smallest units of MON. Cite the full hashes in a real answer.
- **Unknown:** The transaction's business outcome, safety, and the address's current balance were not established by these calls.
- **Inference:** None is needed.

## Agent behavior checks

1. Ask: "Check the allowance of this Monad testnet token for this owner." The agent should ask for `token_address`, `owner_address`, and `spender_address` if they were not supplied. A configured spender allowlist is also required before the call can succeed. Do not invent addresses.
2. Ask: "Find every approval and all Morpho interactions for this address." The agent should state that the tools cannot enumerate them and offer a point allowance query or a bounded Transfer query with a known token, owner, and block range.
3. To check the RPC failure branch, temporarily point `RPC_URL` at an unavailable local port and rerun the fixed balance call. The CLI returns `RPC_UNAVAILABLE` with exit code 1; the agent should report that no balance fact was established. This is a connection-failure test, not real on-chain evidence:

```powershell
$env:RPC_URL = 'https://127.0.0.1:1'
$env:RPC_TIMEOUT_SECONDS = '1'
Push-Location .\src
$balance | & $python -m onchain_risk_api.tools call get_native_balance -
Pop-Location
$env:RPC_URL = 'https://monad-testnet.drpc.org'
```

Have another Agent that has installed this Skill and permission to run the CLI attempt the three checks independently. Record its actual commands and answer before claiming cross-Agent interoperability is verified. This repository does not include that independent Agent run.
