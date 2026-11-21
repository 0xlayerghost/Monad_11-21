---
name: onchain-investigation
description: Query a configured EVM chain through this repository's local CLI or an authorized deployed read-only HTTP API for known addresses, tokens, block ranges, or transaction hashes. Use for bounded, verifiable facts, not full history or transaction execution.
---

# On-chain investigation

Use the local CLI when the repository, its Python dependencies, and CLI execution are available. Use the HTTP route only when a deployment URL, required access permission, and an HTTP-capable tool are provided. This file is an instruction package, not an installed tool or an Agent Hub registration. Follow the target platform's actual installation and permission process before claiming external availability.

## Contract

Run `python -m onchain_risk_api.tools list` from an installed checkout to get the current JSON input and output schemas. `list` does not load local configuration or call RPC. Run one query with `python -m onchain_risk_api.tools call <tool_name> '<JSON object>'`; in PowerShell, pipe JSON to `call <tool_name> -` to preserve quoting. `call` uses the checkout's local single-network configuration, makes a read-only RPC query, and prints `ToolCallResult` JSON. Do not print or inspect `.env` or any credential file. The application may load its configuration normally. Never send a private key, sign, or submit a transaction.

All input objects require `network_name` matching the configured network. Use the schema's snake_case input keys, not the response's camelCase keys. Additional fields and wrong types are rejected.

| Tool | Required fields beyond `network_name` | Optional field | Scope |
| --- | --- | --- | --- |
| `get_native_balance` | `address` | `block_number` | One native-asset balance at a verified block |
| `get_erc20_balance` | `token_address`, `owner_address` | `block_number` | One token's `balanceOf`; token allowlist may restrict it |
| `get_erc20_allowance` | `token_address`, `owner_address`, `spender_address` | `block_number` | One allowance; spender must be configured in `ERC20_ALLOWED_SPENDERS` |
| `get_erc20_transfer_activity` | `token_address`, `owner_address`, `from_block`, `to_block` | none | Only this token's Transfer logs involving owner; at most 2,000 block difference and 100 events |
| `get_transaction_receipt` | `transaction_hash` | none | One receipt observation; pending, mined, and not-found are distinct |

Omitted or null `block_number` selects a verified latest snapshot for balances and allowance. It is not a continuously updating value. Ask for missing identifiers or bounds before calling. For requests outside this contract, explain the limit and offer a supported narrower query. Do not claim to discover all address activity, token holdings, approvals, protocol interactions, contract upgrades, or full history. No prices, swaps, or safety verdicts are available.

## Interpret the result

The outer `status` reports whether the tool query succeeded. For receipt queries, inner `data.status` is `pending` or `mined`; a mined receipt may have `executionStatus` `success` or `reverted`. A successful EVM execution is not proof of economic or contract safety. A nonzero CLI exit code or outer `status: error` means no fact was established. Read `error.code` and `error.message`; `INVALID_TOOL_ARGUMENTS` requires corrected arguments, `BLOCK_RANGE_TOO_LARGE` requires a narrower range, and `RPC_UNAVAILABLE` or `CHAIN_ID_MISMATCH` means the chain fact remains unknown. Do not convert errors, empty findings, or missing data into zero, safe, or "no activity" conclusions.

Present a short answer under **Facts**, **Unknown**, and **Inference** (omit the last section when there is no inference). Cite only fields actually returned. Balances and allowance carry `blockNumber` and `blockHash`; token responses place them under `data.evidence`. Transfer activity carries `fromBlock`, `toBlock`, `evidenceId`, and event `transactionHash`/`blockNumber`/`logIndex`, but not each event's block hash. A pending receipt has a transaction hash and observation time, but no block number or hash. Include `network`, `chainId`, and relevant query scope. An empty bounded Transfer result means no matching logs were returned for that token, owner, and range, not that the address had no activity.

For a verified Monad testnet walkthrough, including a missing-parameter question, an unsupported request, and an RPC failure, read [the demo reference](references/monad-testnet-demo.md). Its sample values were checked on 2026-11-21; rerun queries before presenting live results.

## Deployed read-only API

For remote invocation, read [the HTTP route and access guide](references/remote-http.md) and use [the fixed sample inputs](references/monad-testnet-samples.json). The remote agent uses its own reasoning model; the five GET queries do not require the server's DeepSeek key. The server-side `POST /v1/investigations` does require that key and is not an external Agent interface. Clearing the key and restarting disables server-side AI investigation but does not revoke HTTP access to read-only routes. Treat a withdrawn deployment URL or revoked/expired access token as an access failure, not a negative chain finding.
