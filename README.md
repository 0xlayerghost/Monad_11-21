# Onchain Analytics Risk Management
所有答案解释都以一个智能合约开发的视角来回答
一个可配置单条 EVM 网络的只读链上数据分析与风控项目。当前默认使用 Base Sepolia；
网络标识、chain ID、原生币、RPC 服务商和 RPC URL 均由环境变量提供。项目后续目标是
链上风险调查 Agent；每个服务进程只连接一个配置网络，避免混用不同链的数据。

## 建议阅读顺序：先最小展示，再完整流程

每次学习或继续开发，先看 [最小展示与最小模型](docs/minimal-demo.md)：
先用离线小例子理解对象和参数校验，再看直接查链与模型调用的最小命令。
其中真实模型 / RPC 命令需要有效配置，模型调用可能收费，不是离线示例。

理解最小闭环后，再看 [网页 AI 调查调用链](docs/web-investigation.md) 与
[项目完整调用链](docs/call-chain.md)。配置和预算查 [LLM 使用说明](docs/llm.md)，
实际开发进度与验收状态查 [第二阶段验证记录](docs/phase-2/verification.md) 和
[第三阶段契约](docs/phase-3/contract.md)。当前继续开发的是第三阶段的授权查询最小切片，
并不代表第二阶段的真实模型验收或第三阶段整体已完成。

## 当前能力

- `GET /v1/networks/{NETWORK_NAME}/tokens/{token_address}/balance`：查询指定 ERC-20
  token + owner 的余额，无需 spender；支持可选区块及精确数值、元数据缺失提示。
  HTTP、AI 工具和网页共用服务；见 [代币余额调用链](docs/phase-3/token-balance.md)。真实查询尚待独立验收。
  已提供 [余额快照采集与离线核对](docs/phase-3/token-balance-snapshot.md)，不会自动完成真实验收。
- `GET /v1/networks/{NETWORK_NAME}/tokens/{token_address}/activity`：在最多 2,000 个区块内查询
  指定 token 与 owner 相关的 `Transfer` 日志，最多返回 100 条；不等于完整历史或当前余额。
  详见 [历史活动调用链](docs/phase-3/transfer-activity.md)。

- `GET /health`：进程存活检查，不访问外部 RPC。
- `GET /v1/networks/{NETWORK_NAME}/tokens/{token_address}/allowance`：查询 ERC-20 授权，
  返回固定区块证据与确定性关注项。非空 token 白名单限制可查 token，空 token 列表允许任意
  合法 token 地址；spender 始终必须在非空白名单中。配置、调用和错误码见
  [授权查询最小展示](docs/phase-3/allowance.md)。
- `GET /v1/networks/{NETWORK_NAME}/status`：读取 RPC 的 chain ID，并核验它是否与
  `EXPECTED_CHAIN_ID` 一致。
- `GET /v1/networks/{NETWORK_NAME}/addresses/{address}/balance`：查询固定区块的
  配置原生币余额，返回精确金额和区块来源信息。
- `GET /v1/networks/{NETWORK_NAME}/transactions/{transaction_hash}/receipt`：查询交易回执，
  区分 pending、已打包成功或 revert，并补充所在区块的时间。
- 统一、可机器读取的错误响应；不会在响应中返回 RPC URL 或凭证。
- 离线单元测试，以及显式启用的当前 RPC 集成测试。
- 四个只读工具的注册表、严格参数校验及本地 CLI（原生币余额、代币余额、回执、指定 ERC-20 授权）。
- 本地最小 LLM loop：可配置模型、有限预算、工具 trace，已完成一次真实调用。
- 本机网页 AI 调查入口：复用同一有限预算 loop，展示模型答案和工具 trace。

第一阶段已实现交易回执与工具层，但尚未完整验收；第二阶段已开始最小 LLM 闭环。
暂不支持无限 ERC-20 历史、地址全量历史、价格估值、风险评分或交易执行。

验证记录见阶段契约；真实 RPC 与可复现公开 fixture 的验收仍需单独执行，
不能仅凭离线测试通过认定第一阶段完成。

2026-10-30：已执行网络、余额、回执三项真实 RPC 集成检查，全部通过；
两个只读工具也通过真实 CLI 调用。公开回执样例与复现方法见
[验证记录](docs/phase-1/verification.md)。完整阶段验收仍未完成。

## 环境要求

- Python 3.12 或 3.13
- 当前配置网络对应的 HTTPS JSON-RPC endpoint

Foundry 不是服务运行依赖。后续可以使用 `cast` 对查询结果做独立核验。

## 快速开始

PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑本地 `.env`，填写目标网络对应的 endpoint 和网络参数。不要提交 `.env`，也不要
把 endpoint 或 API key 写入代码、日志和测试 fixture。

`.env.example` 默认配置为 Base Sepolia。切换网络时，需要一起更改 `NETWORK_NAME`、
`EXPECTED_CHAIN_ID`、`NATIVE_SYMBOL`、`NATIVE_DECIMALS`、`RPC_PROVIDER_NAME` 和 `RPC_URL`；
服务会验证 RPC 实际返回的 chain ID，不符时拒绝查询。示例：BSC Mainnet 使用
`bsc` / `56` / `BNB` / `18`，Arbitrum One 使用 `arbitrum-one` / `42161` / `ETH` / `18`。
chain ID 示例不代表自动提供对应网络的 RPC endpoint，`RPC_URL` 必须由你选择的服务商提供。
Base Sepolia 与 Base Mainnet 分别填写 `base-sepolia` / `84532` 和 `base` / `8453`。
重启服务后配置生效；每个进程仅服务一个网络。

启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn onchain_risk_api.main:app --reload
```

打开 `http://127.0.0.1:8000/docs` 查看 OpenAPI 文档。

## AI 调查页面

前端使用 Vue 3 + TypeScript + Vite，不使用组件库。需要 Node.js 22.18+。
源码、依赖和 npm 下载缓存都放在项目的 `frontend/` 下，不需要全局安装。

首次使用，在项目根目录执行：

```powershell
cd frontend
npm ci --cache .npm-cache
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn onchain_risk_api.main:app --reload
```

打开 `http://127.0.0.1:8000/`。已有后端进程时，构建后重启一次。
首页只展示 AI Investigation：输入问题后查看模型答案、工具调用记录和原始 JSON。
答案按 Markdown 排版，原始 HTML 不会作为页面内容执行。网络从后端配置读取；
页面不连接钱包、不签名，也不会把 RPC URL 或模型密钥交给浏览器。
原生币余额、交易回执和 ERC-20 授权的 HTTP API 仍可在 `/docs` 使用。
未构建时首页会提示构建步骤，已有 API 仍可使用。
热更新开发和验证命令见 [前端说明](docs/frontend.md)。

## 常用命令

```powershell
# 离线单元测试
.\.venv\Scripts\python.exe -m pytest -m "not integration"

# 配置 .env 后，运行当前 RPC 网络的真实集成测试
$env:RUN_INTEGRATION_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest -m integration

# 回执集成测试还需设置当前网络上一笔已打包交易的真实哈希
$env:INTEGRATION_TRANSACTION_HASH = "替换为 0x 开头的 64 位十六进制交易哈希"
.\.venv\Scripts\python.exe -m pytest -m integration -k receipt

# 静态检查
.\.venv\Scripts\python.exe -m ruff check .
```

也可以用 `cast` 交叉检查网络：

```powershell
$env:RPC_URL = "你的 JSON-RPC endpoint"
cast chain-id --rpc-url $env:RPC_URL
```

返回的 chain ID 必须与 `.env` 的 `EXPECTED_CHAIN_ID` 一致。

## 原生币余额接口

```powershell
$address = "0x0000000000000000000000000000000000000000"
Invoke-RestMethod "http://127.0.0.1:8000/v1/networks/$env:NETWORK_NAME/addresses/$address/balance"
# 可选：查询一个已存在的区块；历史状态是否可读取取决于 RPC 能力
Invoke-RestMethod "http://127.0.0.1:8000/v1/networks/$env:NETWORK_NAME/addresses/$address/balance?blockNumber=123"
```

输入要求 `0x` 加 40 位十六进制地址，接受全小写 / 全大写地址；混合大小写必须
通过 EIP-55 校验，响应统一为 checksum 地址。`blockNumber` 是可选的非负整数，
省略时先选取 `latest` 区块，再按该区块号查询余额；不会直接读取浮动的 `latest` 余额。

响应字段：`network`、`chainId`、`provider`、`address`、`asset`、`decimals`、
`balanceSmallestUnit`、`balanceNative`、`blockNumber`、`blockHash`、`blockTimestamp`、`observedAt`。
金额均序列化为字符串：最小单位保持整数精度，原生币显示位数取决于
`NATIVE_DECIMALS`，不经过浮点运算。

| HTTP | 错误码 | 含义 |
| --- | --- | --- |
| 422 | `VALIDATION_ERROR` | 地址、checksum 或区块号非法；不调用 RPC |
| 404 | `BLOCK_NOT_FOUND` | 初次选择的区块不存在；不等于余额为零 |
| 404 | `NETWORK_NOT_CONFIGURED` | 请求的网络名与当前进程配置不符 |
| 503 | `CHAIN_ID_MISMATCH` | RPC 所属网络不符；不继续读取余额 |
| 503 | `RPC_UNAVAILABLE` | RPC 超时、传输错误、无历史状态或无效响应等 |
| 503 | `SNAPSHOT_CHANGED` | 余额读取后复核发现所选区块已变化或消失；可重试 |

快照采用“选区块 → 按区块号读余额 → 复核同高度 hash”的有界检查。
这不是原子快照或最终性承诺，不能排除多节点不一致或极短时间内的来回重组。
本切片不自动重试，并关闭 web3.py 的传输层自动重试；配置的 timeout 作用于每次 RPC，
不是整个 HTTP 请求的总预算。限流与超时暂统一映射为 `RPC_UNAVAILABLE`，分类型错误
与可复现真实链快照留待后续切片。设计取舍见 [ADR-0003](docs/decisions/0003-native-balance-snapshot.md)。

## 交易回执接口

启动后打开 `/docs`，展开交易回执 GET 接口，填写 `.env` 中的网络名称，
以及该网络上一笔交易的哈希。也可以在 PowerShell 执行：

```powershell
$network = "base-sepolia"
$tx = "替换为该网络上的真实交易哈希"
Invoke-RestMethod "http://127.0.0.1:8000/v1/networks/$network/transactions/$tx/receipt"
```

| 结果 | HTTP | 语义 |
| --- | --- | --- |
| `status=mined`，`executionStatus=success` | 200 | 已打包，EVM 执行成功，不代表业务正确或安全 |
| `status=mined`，`executionStatus=reverted` | 200 | 已打包但 EVM revert；查询本身成功 |
| `status=pending` | 200 | 节点知道该交易，但尚未关联区块；回执字段为 null |
| `TRANSACTION_NOT_FOUND` | 404 | 当前节点未找到交易，不证明其他节点也不知道 |
| `RECEIPT_UNAVAILABLE` | 503 | 节点返回已打包交易，但暂时不能提供回执 |
| `SNAPSHOT_CHANGED` | 503 | 回执中的区块 hash 与所查询区块不符，或区块已消失 |
| `VALIDATION_ERROR` | 422 | 交易哈希不是 `0x` 加 64 位十六进制，RPC 不会被调用 |
| `RPC_UNAVAILABLE` / `CHAIN_ID_MISMATCH` | 503 | RPC 失败、响应非法或连接的链不符 |

已打包结果包含 `blockNumber`、`blockHash`、`blockTimestamp`、`observedAt`、
`transactionIndex`、`fromAddress`、`toAddress`、`contractAddress`、`gasUsed` 和
`effectiveGasPrice`。Gas 数值使用字符串；缺失的有效 gas 价格保持 null。
合约创建交易的 `toAddress` 可以为 null。区块时间来自额外的区块查询，不是回执自带。

本接口只观察一次，不自动等待打包、重试或承诺最终性。`gasUsed` 是 gas 数量，
不是 ETH 数量；也不把它与 gas 价格的乘积宣称为所有网络的完整费用，L2 可能另有收费。
设计与限制见 [ADR-0004](docs/decisions/0004-transaction-receipt-states.md)。

## LLM 工具层准备

授权真实样例可用独立的 [快照采集与核对命令](docs/phase-3/snapshot-capture.md) 保存候选，
再与固定区块的独立来源核对；不调用模型，不自动认证来源或将模拟数据变成真实 fixture。

目前注册 `get_native_balance`、`get_transaction_receipt` 和 `get_erc20_allowance` 三个只读工具，
复用现有服务，拒绝未知工具和额外参数；不允许模型传入 RPC URL 或私钥。
授权工具仅查询白名单内的明确三方地址并返回最大授权关注项；历史、更多规则和检索仍未完成。
授权工具已完成离线回归，真实模型与授权 RPC 联调仍待验收，见 [调用说明](docs/phase-3/agent-allowance.md)。

不启动服务器、不访问 RPC，也可以查看工具 Schema：

```powershell
.\.venv\Scripts\python.exe -m onchain_risk_api.tools list
```

命令行执行方式、工具边界与后续 loop 的关系见 [只读工具说明](docs/tools.md)。
实际查询会读取 `.env`；模型 Provider、多轮调用与 trace 的使用方式见下方 LLM 说明。

## 项目结构

第一次阅读代码建议先看 [项目调用链（Solidity 视角）](docs/call-chain.md)，
其中说明启动过程、余额与回执查询、参数传递、错误处理及各层职责。

```text
src/onchain_risk_api/
  api/          HTTP 路由与错误映射
  core/         配置
  domain/       API/领域模型与错误
  providers/    可配置 JSON-RPC/web3.py 适配器
  services/     网络身份等业务语义
  tools/        只读工具契约、注册表、单次执行 CLI
  llm/          可配置模型适配器、有限预算循环、本地 CLI
  web/          公开网络配置与构建后静态页面
frontend/       Vue 源码、独立 npm 依赖与锁文件
tests/
  unit/         不访问真实 RPC
  integration/  显式启用的真实 RPC 验证
docs/
  decisions/    架构决策记录
  phase-1/      阶段契约、问题登记与面试复盘
```

第一阶段范围与限制见 [阶段契约](docs/phase-1/contract.md)，当前网络决策见
[ADR-0002](docs/decisions/0002-base-sepolia-testnet.md)；原始 BSC 决策保留在
[ADR-0001](docs/decisions/0001-bsc-blockpi-read-only-api.md) 作为历史记录。

## 本地 LLM 最小闭环

已增加 `python -m onchain_risk_api.llm`：模型提出调用，程序校验后执行已注册的三个只读工具，
再把结果交回模型。配置、PowerShell 命令、预算与安全边界见 [LLM 使用说明](docs/llm.md)。

模型协议与循环已完成一次真实模型、真实 RPC 调用，但尚未完成批量评测；
不等于第二阶段全部完成。网页通过本机 `POST /v1/investigations` 复用该循环，
详细过程见 [网页 AI 调查调用链](docs/web-investigation.md)。该接口没有公网部署所需的
认证、限流和费用配额，开发时应保持监听 `127.0.0.1`。架构决策见
[ADR-0008](docs/decisions/0008-local-web-investigation-endpoint.md)。

CLI 现支持用 `--scenario-id S01 --save-evidence <新文件路径>` 为单次调查留档，
保存去敏结果与待审字段；不自动批量调用或判定通过。用法见
[证据留档](docs/llm.md#保存单次调查证据)，当前离线验证阻碍见
[第二阶段验证记录](docs/phase-2/verification.md)。20 个真实场景验收仍未完成。

已有留档可用 `python -m onchain_risk_api.llm.review artifacts/llm-evidence` 离线汇总，
区分场景覆盖、执行结果、人工标记和损坏文件；不读取密钥、不调用 API、不自动判定通过。
字段、限制与退出码见 [离线汇总验收进度](docs/llm.md#离线汇总验收进度)。
