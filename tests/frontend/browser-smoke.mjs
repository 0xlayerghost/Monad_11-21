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
const python = process.env.PYTHON_PATH || resolve(root, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
const directory = await mkdtemp(join(tmpdir(), "onchain-ui-"));
const apiPort = await freePort();
const browserPort = await freePort();
const api = spawn(python, ["-c", [
  "import uvicorn",
  "from onchain_risk_api.app import create_app",
  "from tests.helpers import FakeChainProvider, make_test_settings",
  `uvicorn.run(create_app(settings=make_test_settings(), provider=FakeChainProvider()), host='127.0.0.1', port=${apiPort}, log_level='error')`,
].join(";")], {
  cwd: root, env: { ...process.env, PYTHONPATH: resolve(root, "src") },
  windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
});
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
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Log.enable");
  await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  await command("Page.navigate", { url: `http://127.0.0.1:${apiPort}/` });
  await waitFor(() => evaluate("document.querySelector('#connection')?.classList.contains('ready')"), "Network did not verify.");
  assert.equal(await evaluate("document.querySelector('#network-name').textContent"), "base-sepolia");
  assert.equal(await evaluate("document.querySelectorAll('main textarea').length"), 1);
  assert.equal(await evaluate("document.querySelectorAll('[role=tab]').length"), 0);
  await screenshot("desktop-empty.png");

  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#query-error')?.textContent.includes('请输入')"), "Blank prompt was accepted.");

  await command("Fetch.enable", { patterns: [{ urlPattern: "*/v1/investigations", requestStage: "Request" }] });
  const completed = {
    status: "completed", stopReason: "COMPLETED", answer: "**地址余额已核对**，仍需结合更多证据。\n\n- 区块 `123`",
    answerIsModelGenerated: true, modelCalls: 2, toolCalls: 1,
    inputTokens: 120, outputTokens: 48,
    trace: [{ step: 1, kind: "tool", callId: "call-1", toolName: "get_native_balance", result: { status: "ok" } }],
    error: null,
  };
  mockResponse = { status: 200, body: completed };
  await evaluate("document.querySelector('#subject').value = '调查这个地址'; document.querySelector('#subject').dispatchEvent(new Event('input', {bubbles:true})); document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#investigation-content')?.textContent.includes('地址余额已核对')"), "Investigation answer did not render.");
  assert.equal(await evaluate("document.querySelector('.agent-answer strong')?.textContent"), "地址余额已核对");
  assert.equal(await evaluate("document.querySelector('.agent-answer li code')?.textContent"), "123");
  assert.equal(await evaluate("document.querySelector('.trace-data summary').textContent.includes('1 步')"), true);
  assert.equal(await evaluate("document.querySelector('.trace-data').open"), false);
  await screenshot("desktop-result.png");

  await command("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate("window.scrollTo(0, 0)");
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true, "Mobile horizontal overflow");
  await screenshot("mobile-result.png");

  mockResponse = { status: 200, body: {
    ...completed, status: "error", stopReason: "LLM_CONNECTION_ERROR", answer: null,
    modelCalls: 1, toolCalls: 0, inputTokens: 0, outputTokens: 0, trace: [],
    error: { code: "LLM_CONNECTION_ERROR", message: "private transport detail" },
  } };
  await evaluate("document.querySelector('#query-form').requestSubmit()");
  await waitFor(() => evaluate("document.querySelector('#investigation-content')?.textContent.includes('LLM_CONNECTION_ERROR')"), "Model failure did not render.");
  assert.equal(await evaluate("document.body.textContent.includes('private transport detail')"), false);
  assert.equal(await evaluate("document.documentElement.scrollWidth <= window.innerWidth"), true, "Error mobile horizontal overflow");
  await evaluate("document.querySelector('.new-button').click()");
  assert.equal(await evaluate("document.querySelector('#subject').value"), "");
  assert.equal(await evaluate("!!document.querySelector('#investigation-content')"), false);
  assert.deepEqual(errors, [], "Browser runtime or CSP errors");
  console.log("Browser smoke passed: network, prompt validation, investigation, trace, model error, reset and mobile layout.");
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
