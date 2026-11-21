# Vercel 部署

本项目使用 Vercel FastAPI preset。`app.py` 加载现有后端，构建命令先安装并构建
Vue 前端，生成到后端的 `web/static/`。前端与 API 使用同一域名。

`vercel.json` 默认配置 Monad Testnet（chain ID 10143，原生币 MON）和公开 RPC。
构建需要 Node.js 22.18+、Python 3.12。`.vercelignore` 排除本地凭证和开发环境。

## 首次上线

1. 在 Vercel 导入本 GitHub 仓库，Root Directory 保持仓库根目录。
2. 使用 FastAPI preset，沿用 `vercel.json` 中的构建命令。
3. 在 Settings → Deployment Protection 中允许 Production 公网访问。
4. 验证 `/`、`/health`、`/v1/ui/config` 和 `/v1/networks/monad-testnet/status`。

连接 GitHub 的 `main` 分支后，推送或合并更新可触发自动部署。单次 CLI 部署
不等于已建立 GitHub 自动部署；需在 Vercel 确认 Git 连接与 Production Branch。
比赛演示前先验证新版本，必要时回滚到最近可运行的部署。

## AI 调查配置

模型密钥仅在 Vercel 的 Environment Variables 中设置，不写进仓库或浏览器。
至少需要 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`，修改后重新部署。
当前适配器调用 `<LLM_BASE_URL>/responses`，必须使用支持 Responses API 以及
本项目工具调用格式的模型服务。不能仅凭“兼容 OpenAI”就认定可用；
`.env.example` 中的模型配置需要单独验证。

未配置模型时，网页及只读链上 API 可运行，AI 调查返回 `LLM_NOT_CONFIGURED`。
当前单次调查预算由 `LLM_RUN_TIMEOUT_SECONDS` 等变量控制；单次预算不等于
跨请求限流或账户总额度。启用付费模型前，在模型供应商设置账户费用上限，
并为公开调查接口配置限流。生产网站应允许评审直接访问。

## 与链上部署的区别

此部署托管网页和只读分析 API，不会创建钱包、发送交易或部署智能合约。
Monad 数据访问需通过线上 network status 和真实查询验证；如果比赛要求
部署合约，还需单独完成合约部署和验证。
