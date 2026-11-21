import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

async function freePort() {
  const server = createServer();
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  const port = server.address().port;
  await new Promise((done) => server.close(done));
  return port;
}

async function waitFor(action, message) {
  for (let attempt = 0; attempt < 150; attempt += 1) {
    try {
      const result = await action();
      if (result) return result;
    } catch {}
    await delay(100);
  }
  throw new Error(message);
}

const browserPath = [
  process.env.BROWSER_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium",
].find((path) => path && existsSync(path));
assert.ok(browserPath, "Set BROWSER_PATH to an installed Chromium-based browser.");
const root = fileURLToPath(new URL("../../", import.meta.url));
const python = resolve(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const directory = await mkdtemp(join(tmpdir(), "onchain-ui-"));
const apiPort = await freePort();
const browserPort = await freePort();
const api = spawn(python, ["-c", [
  "import uvicorn",
  "from onchain_risk_api.app import create_app",
  "from tests.helpers import FakeChainProvider, make_test_settings",
  `uvicorn.run(create_app(settings=make_test_settings(), provider=FakeChainProvider()), host='127.0.0.1', port=${apiPort}, log_level='error')`,
].join(";")], { cwd: root, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
let serverLog = "";
api.stdout.on("data", (data) => { serverLog += data; });
api.stderr.on("data", (data) => { serverLog += data; });
let browser;
let socket;
let command;
const errors = [];
let mockResponse;
try {
  await waitFor(async () => (await fetch(`http://127.0.0.1:${apiPort}/health`)).ok, "Test API did not start.");
  browser = spawn(browserPath, [
    "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--disable-background-networking", "--disable-component-update", "--disable-sync",
    `--remote-debugging-port=${browserPort}`, `--user-data-dir=${join(directory, "profile")}`,
    "about:blank",
  ], { windowsHide: true, stdio: "ignore" });
  const target = await waitFor(async () => {
    const targets = await (await fetch(`http://127.0.0.1:${browserPort}/json/list`)).json();
    return targets.find((item) => item.type === "page");
  }, "Headless browser did not start.");
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((done, reject) => {
    socket.addEventListener("open", done, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });
  let sequence = 0;
  const pending = new Map();
  socket.addEventListener("message", (event) => {
    const data = JSON.parse(event.data);
    if (data.method === "Fetch.requestPaused") {
      const requestId = data.params.requestId;
      const operation = mockResponse
        ? command("Fetch.fulfillRequest", {
            requestId, responseCode: mockResponse.status,
            responseHeaders: [{ name: "Content-Type", value: "application/json" }],
            body: Buffer.from(JSON.stringify(mockResponse.body)).toString("base64"),
          })
        : command("Fetch.continueRequest", { requestId });
      operation.catch((error) => errors.push(error.message));
      return;
    }
    if (data.method === "Runtime.exceptionThrown") errors.push(data.params.exceptionDetails.exception?.description || data.params.exceptionDetails.text);
    if (data.method === "Log.entryAdded" && data.params.entry.level === "error") errors.push(data.params.entry.text);
    if (!data.id) return;
    const item = pending.get(data.id);
    if (!item) return;
    clearTimeout(item.timer);
    pending.delete(data.id);
    if (data.error) item.reject(new Error(JSON.stringify(data.error)));
    else item.resolve(data.result);
  });
  command = (method, params = {}) => new Promise((done, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 8000);
    pending.set(id, { resolve: done, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
  async function evaluate(expression) {
    const value = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (value.exceptionDetails) throw new Error(value.exceptionDetails.text);
    return value.result.value;
  }
  async function screenshot(name) {
    const image = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    const path = join(directory, name);
    await writeFile(path, Buffer.from(image.data, "base64"));
    console.log(`Screenshot (fake test data): ${path}`);
  }
  async function setInput(selector, value) {
    await evaluate(`document.querySelector('${selector}').value = ${JSON.stringify(value)}; document.querySelector('${selector}').dispatchEvent(new Event('input', {bubbles:true}));`);
  }
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Log.enable");
  await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
  await command("Page.navigate", { url: `http://127.0.0.1:${apiPort}/` });
  await waitFor(() => evaluate("document.querySelector('#connection')?.classList.contains('ready')"), "Network did not verify.");
  assert.equal(await evaluate("document.querySelector('#network-name').textContent"), "base-sepolia");
  await screenshot("desktop-empty.png");

  const address = "0x" + "11".repeat(20);
  await setInput("#subject", address);
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#result-content')"), "Balance did not render.");
  assert.equal(await evaluate("document.querySelector('#result-value').textContent"), "1.000000000000000001");
  await screenshot("desktop-balance.png");

  await setInput("#subject", "0x123");
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#query-error')"), "Input error did not render.");
  assert.equal(await evaluate("!!document.querySelector('#result-content')"), false);

  await setInput("#subject", address);
  await setInput("#block-number", "-1");
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#query-error')?.textContent.includes('区块号')"), "Invalid block was accepted.");
  await setInput("#block-number", "123");
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#result-content')"), "Historical balance did not render.");

  await evaluate("document.querySelector('#balance-tab').dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}));");
  assert.equal(await evaluate("document.querySelector('#token-balance-tab').getAttribute('aria-selected')"), "true");
  assert.equal(await evaluate("!!document.querySelector('#spender-address')"), false);
  await evaluate("document.querySelector('#token-balance-tab').dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}));");
  assert.equal(await evaluate("document.querySelector('#receipt-tab').getAttribute('aria-selected')"), "true");
  const hash = "0x" + "cd".repeat(32);
  await setInput("#subject", hash);
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#result-content')"), "Receipt did not render.");
  assert.equal(await evaluate("document.querySelector('#result-value').textContent"), "执行成功");

  const minedReceipt = await evaluate("JSON.parse(document.querySelector('.raw-data pre').textContent)");
  await command("Fetch.enable", { patterns: [{ urlPattern: "*/receipt", requestStage: "Request" }] });
  mockResponse = { status: 200, body: { ...minedReceipt, status: "pending", executionStatus: null,
    blockNumber: null, blockHash: null, blockTimestamp: null } };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#result-value')?.textContent === '等待打包'"), "Pending receipt was misrepresented.");

  mockResponse = { status: 503, body: { error: { code: "RPC_UNAVAILABLE", message: "secret" } } };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#query-error')?.textContent.includes('节点')"), "RPC error did not render.");
  assert.equal(await evaluate("!!document.querySelector('#result-content')"), false);
  assert.equal(await evaluate("document.body.textContent.includes('secret')"), false);
  mockResponse = undefined;
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#result-content')"), "Retry did not render.");

  await command("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate("window.scrollTo(0,0)");
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true, "Mobile horizontal overflow");
  await screenshot("mobile.png");
  await evaluate("document.querySelector('#allowance-tab').click()");
  assert.equal(await evaluate("document.querySelector('#allowance-tab').textContent.trim()"), "查授权");
  await setInput("#token-address", address);
  await setInput("#owner-address", address);
  await setInput("#spender-address", address);
  await setInput("#block-number", "123");
  await command("Fetch.enable", { patterns: [{ urlPattern: "*/allowance*", requestStage: "Request" }] });
  const maximumAllowance = ((1n << 256n) - 1n).toString();
  const allowanceResponse = {
    evidence: { evidenceId: "evidence:" + "ab".repeat(32), network: "base-sepolia",
      chainId: 84532, provider: "fake", tokenAddress: address, ownerAddress: address,
      spenderAddress: address, allowanceSmallestUnit: maximumAllowance, blockNumber: 123,
      blockHash: "0x" + "ab".repeat(32), blockTimestamp: "2026-10-30T00:00:00Z",
      observedAt: "2026-10-30T00:00:01Z" },
    findings: [{ findingId: "finding:1", ruleId: "ERC20_MAX_ALLOWANCE", ruleVersion: 1,
      severity: "attention", evidenceIds: ["evidence:" + "ab".repeat(32)], summary: "Maximum allowance" }],
    limitations: ["单个区块的只读快照，不构成安全结论。"],
  };
  mockResponse = { status: 200, body: allowanceResponse };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#allowance-content')"), "Allowance did not render.");
  assert.equal(await evaluate("document.querySelector('#allowance-value').textContent"), maximumAllowance);
  assert.equal(await evaluate("document.querySelector('#allowance-content').textContent.includes('ERC20_MAX_ALLOWANCE')"), true);
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true, "Allowance mobile horizontal overflow");
  await screenshot("mobile-allowance.png");
  mockResponse = { status: 200, body: { ...allowanceResponse, findings: [] } };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#allowance-content')?.textContent.includes('不代表合约或授权安全')"), "Empty findings implied safety.");
  mockResponse = { status: 200, body: { ...allowanceResponse,
    evidence: { ...allowanceResponse.evidence, ownerAddress: "0x" + "22".repeat(20) } } };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#query-error')?.textContent.includes('预期不一致')"), "Mismatched owner was displayed.");
  assert.equal(await evaluate("!!document.querySelector('#allowance-content')"), false);
  mockResponse = { status: 404, body: { error: { code: "TOKEN_NOT_CONFIGURED", message: "secret" } } };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#query-error')?.textContent.includes('白名单')"), "Allowlist failure was not explained.");
  assert.equal(await evaluate("!!document.querySelector('#allowance-content')"), false);
  assert.equal(await evaluate("document.body.textContent.includes('secret')"), false);
  await evaluate("document.querySelector('#balance-tab').click()");
  assert.equal(await evaluate("!!document.querySelector('#allowance-content')"), false);
  await evaluate("document.querySelector('#token-balance-tab').click()");
  await setInput('#token-address', address);
  await setInput('#owner-address', address);
  await command('Fetch.enable', { patterns: [{ urlPattern: '*/tokens/*/balance*', requestStage: 'Request' }] });
  const tokenResponse = { evidence: {
    ...allowanceResponse.evidence, balanceSmallestUnit: '1000001', decimals: 6,
    balanceFormatted: '1.000001', metadataError: null,
  }, limitations: ['Only requested token; not safety.'] };
  mockResponse = { status: 200, body: tokenResponse };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#token-balance-content')"), 'Token balance did not render.');
  assert.equal(await evaluate("document.querySelector('#token-balance-value').textContent"), '1.000001');
  assert.equal(await evaluate("!!document.querySelector('#spender-address')"), false);
  mockResponse = { status: 200, body: { ...tokenResponse, evidence: { ...tokenResponse.evidence,
    decimals: null, balanceFormatted: null, metadataError: { code: 'TOKEN_CALL_FAILED', message: 'Unavailable' } } } };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#token-balance-value')?.textContent === '1000001'"), 'Unknown decimals did not preserve smallest units.');
  assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true, 'Token balance mobile overflow');
  await evaluate("document.querySelector('#activity-tab').click()");
  await setInput('#token-address', address);
  await setInput('#owner-address', address);
  await setInput('#from-block', '100');
  await setInput('#to-block', '200');
  const activityResponse = { network: 'base-sepolia', chainId: 84532, provider: 'fake',
    tokenAddress: address, ownerAddress: address, fromBlock: 100, toBlock: 200,
    events: [{ transactionHash: hash, blockNumber: 123, logIndex: 0,
      fromAddress: address, toAddress: address, amountSmallestUnit: '7' }],
    evidenceId: 'evidence:' + 'cd'.repeat(32), observedAt: '2026-10-30T00:00:01Z',
    findings: [{ findingId: 'finding:' + 'ef'.repeat(32), ruleId: 'ERC20_ZERO_ADDRESS_SOURCE',
      ruleVersion: 1, severity: 'attention', evidenceIds: ['evidence:' + 'cd'.repeat(32)],
      summary: 'Mint-like event evidence only.' }],
    limitations: ['bounded activity only'] };
  mockResponse = { status: 200, body: activityResponse };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("!!document.querySelector('#activity-content')"), 'Transfer activity did not render.');
  assert.equal(await evaluate("document.querySelector('#activity-count').textContent"), '1 条事件');
  assert.equal(await evaluate("document.querySelector('#activity-content').textContent.includes('ERC20_ZERO_ADDRESS_SOURCE')"), true);
  const unexpectedErrors = errors.filter((error) => !error.includes("status of 503") && !error.includes("status of 404"));
  assert.deepEqual(unexpectedErrors, [], "Browser runtime or CSP errors");
  console.log("Browser smoke passed: network, exact balance, input/block validation, keyboard tabs, receipt, pending, RPC errors, retry, allowance evidence/findings/errors, token balance without spender, transfer activity, missing decimals and mobile layout.");
} catch (error) {
  console.error("Browser errors:", errors);
  console.error("Mock server output:", serverLog);
  if (command) {
    const page = await command("Runtime.evaluate", { expression: "document.body.innerText", returnByValue: true }).catch(() => null);
    console.error("Page text:", page?.result?.value);
  }
  throw error;
} finally {
  if (command && socket?.readyState === WebSocket.OPEN) {
    await command("Browser.close").catch(() => {});
    socket.close();
  }
  browser?.kill();
  api.kill();
}
