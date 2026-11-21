import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  ApiError, assertAllowanceResult, assertInvestigationResult, createApi, assertResult, formatTime, friendlyError, shorten,
  validateAllowanceQuery, validateInvestigationPrompt, validateQuery,
  assertTokenBalanceResult, validateTokenBalanceQuery, assertTransferActivityResult, validateTransferActivityQuery,
} from "../../frontend/src/api.ts";

const address = "0x" + "11".repeat(20);
const hash = "0x" + "cd".repeat(32);
const config = { networkName: "base-sepolia", expectedChainId: 84532, nativeSymbol: "ETH", nativeDecimals: 18, provider: "node" };
const balance = {
  network: "base-sepolia", chainId: 84532, provider: "node", address,
  balanceNative: "1.000000000000000001", balanceSmallestUnit: "1000000000000000001",
  asset: "ETH", decimals: 18, blockNumber: 123, blockHash: "0x" + "ab".repeat(32),
  observedAt: "2026-10-30T00:00:00Z", blockTimestamp: "2026-10-30T00:00:00Z",
};
const json = (value, status = 200) => new Response(JSON.stringify(value), { status });
const tokenBalance = {
  evidence: { ...balance, evidenceId: 'evidence:' + 'ab'.repeat(32),
    tokenAddress: address, ownerAddress: address, balanceSmallestUnit: '1000001',
    decimals: 6, balanceFormatted: '1.000001', metadataError: null },
  limitations: ['Only the requested token.'],
};

test('token balance requires no spender and preserves exact values and query identity', () => {
  const query = validateTokenBalanceQuery(address, address, '123');
  assert.equal('spender' in query, false);
  assertTokenBalanceResult(tokenBalance, config, query);
  for (const update of [
    { balanceFormatted: '1.000002' }, { decimals: null }, { balanceSmallestUnit: 1000001 },
    { balanceSmallestUnit: (1n << 256n).toString() }, { ownerAddress: '0x' + '22'.repeat(20) },
    { blockNumber: 124 }, { decimals: 256 }, { chainId: 1 },
  ]) assert.throws(() => assertTokenBalanceResult({ ...tokenBalance,
    evidence: { ...tokenBalance.evidence, ...update } }, config, query));
  const missing = { ...tokenBalance, evidence: { ...tokenBalance.evidence,
    decimals: null, balanceFormatted: null, metadataError: { code: 'TOKEN_CALL_FAILED', message: 'Unavailable' } } };
  assertTokenBalanceResult(missing, config, query);
  assert.throws(() => validateTokenBalanceQuery('bad', address, ''));
  assert.throws(() => validateTokenBalanceQuery(address, address, '-1'));
});

test('token balance API sends owner and optional block, not spender', async () => {
  let path;
  const api = createApi({ fetcher: async (url) => { path = String(url); return json(tokenBalance); } });
  await api.getTokenBalance('base-sepolia', address, address, 123);
  const url = new URL(path, 'http://test');
  assert.equal(url.pathname, `/v1/networks/base-sepolia/tokens/${address}/balance`);
  assert.equal(url.searchParams.get('owner'), address);
  assert.equal(url.searchParams.get('blockNumber'), '123');
  assert.equal(url.searchParams.has('spender'), false);
});
const investigation = {
  status: "completed", stopReason: "ANSWER", answer: "done", answerIsModelGenerated: true,
  modelCalls: 2, toolCalls: 1, inputTokens: 100, outputTokens: 20,
  trace: [{ step: 1, kind: "model", callId: null, toolName: null, result: null }], error: null,
};

test("model errors distinguish arguments, billing, endpoint and transport failures", () => {
  for (const [code, text] of [
    ["LLM_REQUEST_REJECTED", "参数"], ["LLM_BILLING_ERROR", "余额"],
    ["LLM_ENDPOINT_ERROR", "路径"], ["LLM_CONNECTION_ERROR", "DNS"],
    ["LLM_TRANSPORT_ERROR", "传输"],
  ]) assert.ok(friendlyError(new ApiError(code, "unavailable")).includes(text));
});

test("investigation HTTP status diagnostics are optional and validated", () => {
  const result = (details) => ({ ...investigation, status: "error", error: {
    code: "LLM_BILLING_ERROR", message: "Check billing.", details,
  } });
  for (const details of [undefined, null, {}, { httpStatus: 402 }]) {
    assert.doesNotThrow(() => assertInvestigationResult(result(details)));
  }
  for (const details of ["secret", [], { httpStatus: "402" }, { httpStatus: 99 },
    { httpStatus: 600 }, { httpStatus: 402.5 }]) {
    assert.throws(() => assertInvestigationResult(result(details)));
  }
});

test("address, transaction and optional block validation", () => {
  assert.deepEqual(validateQuery("balance", ` ${address} `, ""), { subject: address, blockNumber: null });
  assert.equal(validateQuery("balance", address, "0").blockNumber, 0);
  assert.equal(validateQuery("receipt", hash, "ignored").subject, hash);
  assert.throws(() => validateQuery("balance", hash, ""));
  assert.throws(() => validateQuery("receipt", address, ""));
  for (const height of ["-1", "1.5", "true", "1e3", "9,000", "9007199254740992"]) {
    assert.throws(() => validateQuery("balance", address, height));
  }
});

test("allowance query and evidence validation preserve exact uint256 values", () => {
  assert.deepEqual(validateAllowanceQuery(address, address, address, ""), {
    token: address, owner: address, spender: address, blockNumber: null,
  });
  assert.equal(validateAllowanceQuery(address, address, address, "0").blockNumber, 0);
  for (const value of ["0x1234", ""]) {
    assert.throws(() => validateAllowanceQuery(value, address, address, ""));
    assert.throws(() => validateAllowanceQuery(address, value, address, ""));
    assert.throws(() => validateAllowanceQuery(address, address, value, ""));
  }
  assert.throws(() => validateAllowanceQuery(address, address, address, "1.5"));
  const response = {
    evidence: {
      evidenceId: "evidence:" + "ab".repeat(32), network: config.networkName,
      chainId: config.expectedChainId, provider: "node", tokenAddress: address,
      ownerAddress: address, spenderAddress: address, allowanceSmallestUnit: ((1n << 256n) - 1n).toString(),
      blockNumber: 123, blockHash: "0x" + "ab".repeat(32),
      blockTimestamp: "2026-10-30T00:00:00Z", observedAt: "2026-10-30T00:00:01Z",
    }, findings: [], limitations: ["limited"],
  };
  assert.doesNotThrow(() => assertAllowanceResult(response, config));
  assert.throws(() => assertAllowanceResult({ ...response, evidence: { ...response.evidence, chainId: 1 } }, config));
  const query = validateAllowanceQuery(address, address, address, "123");
  assert.doesNotThrow(() => assertAllowanceResult(response, config, query));
  for (const field of ["tokenAddress", "ownerAddress", "spenderAddress"]) {
    assert.throws(() => assertAllowanceResult({ ...response,
      evidence: { ...response.evidence, [field]: "0x" + "22".repeat(20) },
    }, config, query));
  }
  for (const evidence of [
    { blockNumber: -1 }, { blockNumber: 124 }, { allowanceSmallestUnit: 100 },
    { allowanceSmallestUnit: (1n << 256n).toString() }, { allowanceSmallestUnit: "1e18" },
  ]) assert.throws(() => assertAllowanceResult({ ...response,
    evidence: { ...response.evidence, ...evidence },
  }, config, query));
  const finding = { findingId: "finding:1", ruleId: "ERC20_MAX_ALLOWANCE", ruleVersion: 1,
    severity: "attention", evidenceIds: [response.evidence.evidenceId], summary: "Maximum allowance" };
  assert.doesNotThrow(() => assertAllowanceResult({ ...response, findings: [finding] }, config, query));
  for (const invalid of [{ ruleVersion: 0 }, { evidenceIds: ["other"] }, { evidenceIds: [] }]) {
    assert.throws(() => assertAllowanceResult({ ...response, findings: [{ ...finding, ...invalid }] }, config));
  }
});

test("allowance failures explain allowlists and never turn failures into zero", () => {
  for (const code of ["TOKEN_NOT_CONFIGURED", "SPENDER_NOT_CONFIGURED"]) {
    assert.match(friendlyError(new ApiError(code, "hidden")), /白名单/);
  }
  assert.match(friendlyError(new ApiError("TOKEN_NOT_CONFIGURED", "hidden")), /配置为 \[\]/);
  assert.match(friendlyError(new ApiError("TOKEN_CALL_FAILED", "hidden")), /不代表余额或授权为零/);
});
test("exact balances are validated without floating-point conversion", () => {
  assert.doesNotThrow(() => assertResult(balance, "balance", config, address));
  assert.equal(balance.balanceNative, "1.000000000000000001");
  for (const update of [
    { chainId: 1 }, { address: "0x" + "22".repeat(20) }, { network: "other" },
    { balanceNative: 1 }, { balanceSmallestUnit: 1e18 }, { blockHash: "bad" }, { asset: "BNB" },
  ]) assert.throws(() => assertResult({ ...balance, ...update }, "balance", config, address));
});

test("real captured receipt schema passes browser validation", async () => {
  const sample = JSON.parse(await readFile(new URL("../fixtures/base_sepolia_receipt.json", import.meta.url), "utf8"));
  assertResult(sample.data, "receipt", config, sample.data.transactionHash);
});

test("pending does not become an invented mined status", () => {
  const pending = { network: config.networkName, chainId: config.expectedChainId,
    provider: "node", observedAt: "2026-10-30T00:00:00Z", status: "pending", transactionHash: hash };
  assert.doesNotThrow(() => assertResult(pending, "receipt", config, hash));
  assert.throws(() => assertResult({ ...pending, blockNumber: 12 }, "receipt", config, hash));
});

test("API uses same-origin endpoints and the existing blockNumber alias", async () => {
  const paths = [];
  const api = createApi({ fetcher: async (path) => { paths.push(path); return json(balance); } });
  await api.getBalance("base-sepolia", address, null);
  await api.getBalance("base-sepolia", address, 123);
  await api.getReceipt("base-sepolia", hash);
  assert.equal(paths[0], `/v1/networks/base-sepolia/addresses/${address}/balance`);
  assert.equal(paths[1], `${paths[0]}?blockNumber=123`);
  assert.equal(paths[2], `/v1/networks/base-sepolia/transactions/${hash}/receipt`);
});

test("allowance queries use encoded token parties and optional block", async () => {
  const paths = [];
  const api = createApi({ fetcher: async (path) => { paths.push(path); return json({}); } });
  await api.getAllowance("base-sepolia", address, address, hash.slice(0, 42), null);
  await api.getAllowance("base-sepolia", address, address, hash.slice(0, 42), 123);
  assert.match(paths[0], /^\/v1\/networks\/base-sepolia\/tokens\/.+\/allowance\?/);
  assert.match(paths[0], /owner=/);
  assert.match(paths[0], /spender=/);
  assert.ok(!paths[0].includes("blockNumber"));
  assert.match(paths[1], /blockNumber=123/);
});
test("transfer activity validates bounded events and uses explicit block ranges", async () => {
  const activity = {
    network: "base-sepolia", chainId: 84532, provider: "node", tokenAddress: address,
    ownerAddress: address, fromBlock: 100, toBlock: 200,
    events: [{ transactionHash: hash, blockNumber: 123, logIndex: 0,
      fromAddress: address, toAddress: address, amountSmallestUnit: "1000000000000000001" }],
    evidenceId: "evidence:" + "cd".repeat(32), observedAt: "2026-10-30T00:00:00Z",
    findings: [{ findingId: "finding:" + "ef".repeat(32), ruleId: "ERC20_ZERO_ADDRESS_SOURCE",
      ruleVersion: 1, severity: "attention", evidenceIds: ["evidence:" + "cd".repeat(32)],
      summary: "Mint-like event evidence only." }],
    limitations: ["bounded"],
  };
  const query = validateTransferActivityQuery(address, address, "100", "200");
  assertTransferActivityResult(activity, config, query);
  assert.throws(() => validateTransferActivityQuery(address, address, "200", "100"));
  assert.throws(() => validateTransferActivityQuery(address, address, "1", "2002"));
  assert.throws(() => assertTransferActivityResult({ ...activity,
    events: [{ ...activity.events[0], blockNumber: 99 }] }, config, query));
  assert.throws(() => assertTransferActivityResult({ ...activity,
    findings: [{ ...activity.findings[0], evidenceIds: ["evidence:" + "ab".repeat(32)] }] }, config, query));
  const paths = [];
  const api = createApi({ fetcher: async (path) => { paths.push(path); return json(activity); } });
  await api.getTransferActivity("base-sepolia", address, address, 100, 200);
  assert.match(paths[0], /^\/v1\/networks\/base-sepolia\/tokens\/.+\/activity\?/);
  assert.match(paths[0], /fromBlock=100/);
  assert.match(paths[0], /toBlock=200/);
});
test("investigations use a same-origin POST without exposing model credentials", async () => {
  const calls = [];
  const api = createApi({ fetcher: async (path, init) => { calls.push([path, init]); return json(investigation); } });
  assert.deepEqual(await api.investigate("Inspect this address"), investigation);
  assert.equal(calls[0][0], "/v1/investigations");
  assert.equal(calls[0][1].method, "POST");
  assert.equal(calls[0][1].body, JSON.stringify({ prompt: "Inspect this address" }));
  assert.ok(!calls[0][1].body.includes("apiKey"));
});

test("investigation prompts and responses are validated", () => {
  assert.equal(validateInvestigationPrompt("  inspect  "), "inspect");
  assert.throws(() => validateInvestigationPrompt("   "));
  assert.throws(() => validateInvestigationPrompt("x".repeat(8001)));
  assert.doesNotThrow(() => assertInvestigationResult(investigation));
  assert.throws(() => assertInvestigationResult({ ...investigation, trace: [{ kind: "tool" }] }));
});

test("frontend receives network from the server rather than hardcoding Base", async () => {
  const configured = { ...config, networkName: "arbitrum-sepolia", expectedChainId: 421614 };
  const api = createApi({ fetcher: async () => json(configured) });
  assert.deepEqual(await api.getConfig(), configured);
  const badApi = createApi({ fetcher: async () => json({}) });
  await assert.rejects(badApi.getConfig(), { code: "INVALID_RESPONSE" });
});

test("HTTP errors preserve codes but never echo the response body", async () => {
  const api = createApi({ fetcher: async () => json({ error: { code: "RPC_UNAVAILABLE", message: "secret RPC URL" } }, 503) });
  await assert.rejects(api.getStatus("base-sepolia"), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.code, "RPC_UNAVAILABLE");
    assert.ok(!error.message.includes("secret"));
    return true;
  });
});

test("invalid HTTP JSON and unavailable service are distinguishable", async () => {
  const api = createApi({ fetcher: async () => new Response("<html>bad gateway</html>") });
  await assert.rejects(api.getConfig(), { code: "INVALID_RESPONSE" });
  const offline = createApi({ fetcher: async () => { throw new TypeError("Failed to fetch"); } });
  await assert.rejects(offline.getConfig(), { code: "CONNECTION_FAILED" });
});

test("timeouts and user cancellation stop in-flight work", async () => {
  const fetcher = async (path, { signal }) => new Promise((resolve, reject) => {
    if (signal.aborted) return reject(new DOMException("aborted", "AbortError"));
    signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
  });
  const api = createApi({ fetcher, timeoutMs: 10 });
  await assert.rejects(api.getConfig(), { code: "CLIENT_TIMEOUT" });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(api.getStatus("base-sepolia", controller.signal), { name: "AbortError" });
});

test("formatting handles unknown dates and preserves full values elsewhere", () => {
  assert.equal(formatTime("not a date"), "时间未知");
  assert.equal(shorten(address), `${address.slice(0, 10)}…${address.slice(-8)}`);
  assert.equal(shorten("short"), "short");
});
