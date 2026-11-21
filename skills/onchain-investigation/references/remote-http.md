# Remote read-only HTTP access

The FastAPI service has five read-only GET routes. A remote Agent can use them after a deployment URL and permission to make HTTP requests are supplied. It uses its own LLM to interpret responses; the server's DeepSeek `LLM_API_KEY` is not needed for these queries. The current repository does not implement public API authentication or rate limiting. Put an authentication and rate-limit layer in front of the read-only routes before exposing them to other users. Do not expose the unauthenticated, model-billed `POST /v1/investigations` route.

## Route contract

Replace `{baseUrl}` with the actual deployment origin. Use HTTPS remotely. The service is configured for one network per process; first check `GET {baseUrl}/v1/networks/monad-testnet/status` and require `chainId: 10143` before interpreting results.

| Fact | GET path after `{baseUrl}` | Required query parameters | Optional |
| --- | --- | --- | --- |
| Native balance | `/v1/networks/{network}/addresses/{address}/balance` | none | `blockNumber` |
| ERC-20 balance | `/v1/networks/{network}/tokens/{token}/balance` | `owner` | `blockNumber` |
| ERC-20 allowance | `/v1/networks/{network}/tokens/{token}/allowance` | `owner`, `spender` | `blockNumber` |
| Bounded Transfer logs | `/v1/networks/{network}/tokens/{token}/activity` | `owner`, `fromBlock`, `toBlock` | none |
| Transaction receipt | `/v1/networks/{network}/transactions/{transactionHash}/receipt` | none | none |

The token and spender allowlists configured by the service still apply. Transfer queries require a known token and owner, span at most 2,000 blocks, and return at most 100 events. The exact live response, not the example file, is the evidence. Follow the result interpretation rules in the parent Skill. HTTP errors use `{ "error": { "code": "...", "message": "..." } }`; a non-2xx response is not an on-chain zero or absence.

## Default public test inputs

[monad-testnet-samples.json](monad-testnet-samples.json) contains a chain status query, a known mined transaction hash, and a historical native balance at the same block. They were cross-checked on 2026-11-21 using two public Monad testnet RPC endpoints. `historicalReference` is only a comparison target; rerun the GET and cite the actual returned fields. Do not attribute a protocol identity or safety conclusion to the sample address or transaction. An RPC that has pruned the historical block may fail.

PowerShell smoke check after deployment and access setup:

```powershell
$baseUrl = 'https://YOUR_DEPLOYED_HOST'
$sample = Get-Content .\skills\onchain-investigation\references\monad-testnet-samples.json -Raw | ConvertFrom-Json
$headers = @{}
if ($env:MONAD_READONLY_API_TOKEN) { $headers.Authorization = "Bearer $env:MONAD_READONLY_API_TOKEN" }
$status = Invoke-RestMethod -Uri ($baseUrl + $sample.queries[0].path) -Headers $headers -TimeoutSec 30
if ($status.chainId -ne $sample.chainId) { throw 'Unexpected chain ID' }
$receipt = Invoke-RestMethod -Uri ($baseUrl + $sample.queries[1].path) -Headers $headers -TimeoutSec 30
$balance = Invoke-RestMethod -Uri ($baseUrl + $sample.queries[2].path) -Headers $headers -TimeoutSec 30
$receipt | Select-Object network,chainId,transactionHash,status,executionStatus,blockNumber,blockHash
$balance | Select-Object network,chainId,address,balanceSmallestUnit,blockNumber,blockHash
```

If the deployed gateway requires a bearer token, set `MONAD_READONLY_API_TOKEN` in the caller's environment using the gateway's secure configuration. Never place a token in this Skill, a query string, or a demo recording. The sample command above covers the route shape; it is not proof that public authentication has been implemented.

## Temporary access and failure handling

The DeepSeek key is a separate server-side credential. Clearing it and restarting the service disables server-side AI investigation but does **not** expire these read-only GET endpoints. Revoking the key at DeepSeek while leaving the old value configured instead causes model request errors. To make the remote Agent API temporary, the deployment operator must separately revoke or expire gateway credentials, or remove the public route. Do not claim a fixed expiration date until that mechanism exists and is configured.

An Agent should stop using a withdrawn URL or an expired/revoked credential and request a new authorized endpoint. A gateway `401`/`403`, a missing deployment, an HTTP timeout, or a service `503` means the lookup was not completed. For a `404`, inspect the structured `error.code` before distinguishing a chain-level not-found from a removed route. Never fall back to an unauthenticated URL or label an access failure as "no transaction" or "zero balance". Verify the deployed path end to end with a separate Agent before claiming remote interoperability.
