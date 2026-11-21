export type QueryKind = 'balance' | 'receipt'
export type WorkbenchKind = QueryKind | 'token-balance' | 'allowance' | 'activity' | 'investigation'

export interface UiConfig {
  networkName: string
  expectedChainId: number
  nativeSymbol: string
  nativeDecimals: number
  provider: string
}

interface Evidence {
  network: string
  chainId: number
  provider: string
  observedAt: string
  blockNumber: number | null
  blockHash: string | null
  blockTimestamp: string | null
}

export interface BalanceResult extends Evidence {
  address: string
  asset: string
  decimals: number
  balanceNative: string
  balanceSmallestUnit: string
}

export interface ReceiptResult extends Evidence {
  transactionHash: string
  status: 'pending' | 'mined'
  executionStatus: 'success' | 'reverted' | null
  fromAddress: string | null
  toAddress: string | null
  contractAddress: string | null
  gasUsed: string | null
  effectiveGasPrice: string | null
}

export interface AllowanceFinding {
  findingId: string
  ruleId: string
  ruleVersion: number
  severity: 'attention'
  evidenceIds: string[]
  summary: string
}

export interface AllowanceResult {
  evidence: Omit<Evidence, 'blockNumber' | 'blockHash' | 'blockTimestamp'> & {
    blockNumber: number
    blockHash: string
    blockTimestamp: string
    evidenceId: string
    tokenAddress: string
    ownerAddress: string
    spenderAddress: string
    allowanceSmallestUnit: string
  }
  findings: AllowanceFinding[]
  limitations: string[]
}
export interface TokenBalanceResult {
  evidence: {
    network: string; chainId: number; provider: string; observedAt: string
    blockNumber: number; blockHash: string; blockTimestamp: string; evidenceId: string
    tokenAddress: string; ownerAddress: string; balanceSmallestUnit: string
    decimals: number | null; balanceFormatted: string | null
    metadataError: { code: string; message: string } | null
  }
  limitations: string[]
}
export interface TransferActivityResult {
  network: string
  chainId: number
  provider: string
  tokenAddress: string
  ownerAddress: string
  fromBlock: number
  toBlock: number
  events: Array<{
    transactionHash: string
    blockNumber: number
    logIndex: number
    fromAddress: string
    toAddress: string
    amountSmallestUnit: string
  }>
  evidenceId: string
  findings: AllowanceFinding[]
  observedAt: string
  limitations: string[]
}
export interface InvestigationTraceEvent {
  step: number
  kind: 'model' | 'tool'
  callId: string | null
  toolName: string | null
  result: Record<string, unknown> | null
}

export interface InvestigationResult {
  status: 'completed' | 'stopped' | 'error'
  stopReason: string
  answer: string | null
  answerIsModelGenerated: true
  modelCalls: number
  toolCalls: number
  inputTokens: number
  outputTokens: number
  trace: InvestigationTraceEvent[]
  error: { code: string; message: string; details?: { httpStatus?: number } | null } | null
}

export class ApiError extends Error {
  code: string

  constructor(code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.code = code
  }
}

const errorMessages: Record<string, string> = {
  RPC_UNAVAILABLE: '节点暂时没有返回数据。稍后再试，不代表地址或交易不存在。',
  NETWORK_NOT_CONFIGURED: '服务没有配置这个网络。请刷新页面，重新读取配置。',
  CHAIN_ID_MISMATCH: 'RPC 连接的链与配置不一致。请检查服务端 RPC 和 EXPECTED_CHAIN_ID。',
  SNAPSHOT_CHANGED: '读取期间区块发生了变化。这次结果没有采用，请重新查询。',
  BLOCK_NOT_FOUND: '找不到这个区块。检查区块号，或者留空查询最新区块。',
  TRANSACTION_NOT_FOUND: '当前节点没找到这笔交易。请确认哈希和网络，也可能是节点还没有看到它。',
  TOKEN_NOT_CONFIGURED: 'Token 不在后端非空的 ERC20_ALLOWED_TOKENS 白名单中；如需允许任意合法 Token，可配置为 [] 并重启后端。',
  SPENDER_NOT_CONFIGURED: 'Spender 不在后端 ERC20_ALLOWED_SPENDERS 白名单中，请核实地址后配置并重启后端。',
  TOKEN_CALL_FAILED: '代币合约读取失败，请检查合约地址、ERC-20 接口与指定区块；失败不代表余额或授权为零。',
  VALIDATION_ERROR: '输入没有通过后端校验，请检查地址大小写校验和与区块号。',
  RECEIPT_UNAVAILABLE: '交易已打包，但节点暂时没有返回回执。稍后再查一次。',
  INVALID_REQUEST: '输入没有通过校验。请检查地址大小写校验和、哈希和区块号。',
  INVALID_RESPONSE: '返回内容与预期不一致，这次不展示结果。请稍后重试。',
  LLM_NOT_CONFIGURED: '后端还没有配置模型密钥、模型名或接口地址。',
  LLM_AUTH_ERROR: '模型服务拒绝了凭证，请检查后端 LLM_API_KEY。',
  LLM_REQUEST_REJECTED: '模型服务拒绝了请求参数。请检查 LLM_MODEL，以及服务是否支持当前 Responses 工具调用参数。',
  LLM_BILLING_ERROR: '模型账户计费受限。请在服务商控制台检查 API 余额和计费状态。',
  LLM_ENDPOINT_ERROR: '模型接口路径或资源不可用。请检查 LLM_BASE_URL、模型可用性和 /responses 支持。',
  LLM_CONNECTION_ERROR: '无法建立模型连接。请检查网络、DNS、TLS 和代理设置；当前后端不读取系统代理。',
  LLM_TRANSPORT_ERROR: '模型连接传输中断。请检查网络和服务商连接状态。',
  LLM_RATE_LIMITED: '模型服务触发限流，请稍后再试。',
  LLM_TIMEOUT: '模型请求超时，请稍后重试。',
  LLM_UNAVAILABLE: '模型服务返回了未分类的 HTTP 状态，请查看结果中的 httpStatus 并检查服务商状态。',
}

export function friendlyError(error: unknown): string {
  if (error instanceof ApiError) return errorMessages[error.code] || error.message
  if (error instanceof Error) return error.message
  return '这次查询没有完成，请稍后重试。'
}

export function createApi({
  fetcher = globalThis.fetch.bind(globalThis),
  timeoutMs = 20000,
}: { fetcher?: typeof fetch; timeoutMs?: number } = {}) {
  async function request(
    path: string,
    signal?: AbortSignal,
    init: RequestInit = {},
    requestTimeoutMs = timeoutMs,
  ): Promise<Record<string, unknown>> {
    const controller = new AbortController()
    let timedOut = false
    const abort = () => controller.abort()
    if (signal?.aborted) abort()
    signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, requestTimeoutMs)
    try {
      const headers = new Headers(init.headers)
      headers.set('Accept', 'application/json')
      const response = await fetcher(path, {
        ...init, signal: controller.signal, headers, cache: 'no-store',
      })
      let data: unknown
      try {
        data = await response.json()
      } catch {
        throw new ApiError('INVALID_RESPONSE', '服务返回的内容无法读取，请稍后重试。')
      }
      if (!response.ok) {
        const code = (data as { error?: { code?: unknown } } | null)?.error?.code
        throw new ApiError(typeof code === 'string' ? code : 'REQUEST_FAILED', '查询没有完成。')
      }
      if (!data || typeof data !== 'object' || Array.isArray(data)) {
        throw new ApiError('INVALID_RESPONSE', errorMessages.INVALID_RESPONSE!)
      }
      return data as Record<string, unknown>
    } catch (error) {
      if (timedOut) throw new ApiError('CLIENT_TIMEOUT', '请求超时了，可以再试一次。')
      if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError')
      if (error instanceof ApiError) throw error
      throw new ApiError('CONNECTION_FAILED', '连不上本地服务。请确认 Python 服务仍在运行。')
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
    }
  }

  return {
    async getConfig(signal?: AbortSignal): Promise<UiConfig> {
      const data = await request('/v1/ui/config', signal)
      if (typeof data.networkName !== 'string' || !/^[a-z0-9][a-z0-9-]{0,62}$/.test(data.networkName)
        || !Number.isSafeInteger(data.expectedChainId) || Number(data.expectedChainId) <= 0
        || typeof data.nativeSymbol !== 'string' || !Number.isInteger(data.nativeDecimals)
        || Number(data.nativeDecimals) < 0 || Number(data.nativeDecimals) > 255
        || typeof data.provider !== 'string') {
        throw new ApiError('INVALID_RESPONSE', '服务返回的网络配置不完整。')
      }
      return data as unknown as UiConfig
    },
    getStatus(network: string, signal?: AbortSignal) {
      return request(`/v1/networks/${encodeURIComponent(network)}/status`, signal)
    },
    getBalance(network: string, address: string, blockNumber: number | null, signal?: AbortSignal) {
      const base = `/v1/networks/${encodeURIComponent(network)}/addresses/${encodeURIComponent(address)}/balance`
      return request(blockNumber === null ? base : `${base}?blockNumber=${blockNumber}`, signal)
    },
    getReceipt(network: string, hash: string, signal?: AbortSignal) {
      return request(`/v1/networks/${encodeURIComponent(network)}/transactions/${encodeURIComponent(hash)}/receipt`, signal)
    },
    getAllowance(
      network: string, token: string, owner: string, spender: string,
      blockNumber: number | null, signal?: AbortSignal,
    ) {
      const base = `/v1/networks/${encodeURIComponent(network)}/tokens/${encodeURIComponent(token)}/allowance`
      const params = new URLSearchParams({ owner, spender })
      if (blockNumber !== null) params.set('blockNumber', String(blockNumber))
      return request(`${base}?${params.toString()}`, signal)
    },
    getTokenBalance(network: string, token: string, owner: string, blockNumber: number | null, signal?: AbortSignal) {
      const base = `/v1/networks/${encodeURIComponent(network)}/tokens/${encodeURIComponent(token)}/balance`
      const params = new URLSearchParams({ owner })
      if (blockNumber !== null) params.set('blockNumber', String(blockNumber))
      return request(`${base}?${params.toString()}`, signal)
    },
    getTransferActivity(network: string, token: string, owner: string, fromBlock: number, toBlock: number, signal?: AbortSignal) {
      const base = `/v1/networks/${encodeURIComponent(network)}/tokens/${encodeURIComponent(token)}/activity`
      const params = new URLSearchParams({ owner, fromBlock: String(fromBlock), toBlock: String(toBlock) })
      return request(`${base}?${params.toString()}`, signal)
    },    async investigate(prompt: string, signal?: AbortSignal): Promise<InvestigationResult> {
      const data = await request('/v1/investigations', signal, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      }, 310000)
      assertInvestigationResult(data)
      return data
    },
  }
}

export function validateInvestigationPrompt(prompt: string): string {
  const value = prompt.trim()
  if (!value) throw new Error('请输入要调查的问题。')
  if (value.length > 8000) throw new Error('调查问题最多 8000 个字符。')
  return value
}

export function assertInvestigationResult(
  data: Record<string, unknown>,
): asserts data is Record<string, unknown> & InvestigationResult {
  const invalid = (): never => { throw new ApiError('INVALID_RESPONSE', errorMessages.INVALID_RESPONSE!) }
  if (!['completed', 'stopped', 'error'].includes(String(data.status))
    || typeof data.stopReason !== 'string'
    || (data.answer !== null && typeof data.answer !== 'string')
    || data.answerIsModelGenerated !== true
    || !Number.isSafeInteger(data.modelCalls) || Number(data.modelCalls) < 0
    || !Number.isSafeInteger(data.toolCalls) || Number(data.toolCalls) < 0
    || !Number.isSafeInteger(data.inputTokens) || Number(data.inputTokens) < 0
    || !Number.isSafeInteger(data.outputTokens) || Number(data.outputTokens) < 0) invalid()
  if (!Array.isArray(data.trace)) invalid()
  const trace = data.trace as unknown[]
  for (const event of trace) {
    if (!event || typeof event !== 'object' || Array.isArray(event)) invalid()
    const item = event as Record<string, unknown>
    if (!Number.isSafeInteger(item.step) || Number(item.step) < 1
      || (item.kind !== 'model' && item.kind !== 'tool')
      || (item.callId !== null && typeof item.callId !== 'string')
      || (item.toolName !== null && typeof item.toolName !== 'string')
      || (item.result !== null && (typeof item.result !== 'object' || Array.isArray(item.result)))) invalid()
  }
  if (data.error !== null) {
    if (!data.error || typeof data.error !== 'object' || Array.isArray(data.error)) invalid()
    const error = data.error as Record<string, unknown>
    if (typeof error.code !== 'string' || typeof error.message !== 'string') invalid()
    if (error.details !== undefined && error.details !== null) {
      if (typeof error.details !== 'object' || Array.isArray(error.details)) invalid()
      const status = (error.details as Record<string, unknown>).httpStatus
      if (status !== undefined && (!Number.isInteger(status) || Number(status) < 100 || Number(status) > 599)) invalid()
    }
  }
}

export function validateQuery(kind: QueryKind, subject: string, block: string) {
  const value = subject.trim()
  if (kind !== 'balance' && kind !== 'receipt') throw new Error('未知查询类型。')
  const valid = kind === 'balance' ? /^0x[\da-fA-F]{40}$/.test(value) : /^0x[\da-fA-F]{64}$/.test(value)
  if (!valid) {
    throw new Error(kind === 'balance'
      ? '地址应该是 0x 加 40 位十六进制字符，检查一下是否少复制了几位。'
      : '交易哈希应该是 0x 加 64 位十六进制字符，它比钱包地址更长。')
  }
  const height = block.trim()
  if (kind === 'balance' && height && (!/^\d+$/.test(height) || !Number.isSafeInteger(Number(height)))) {
    throw new Error('区块号应是非负整数，不带小数点或逗号。')
  }
  return { subject: value, blockNumber: kind === 'balance' && height ? Number(height) : null }
}

export function validateAllowanceQuery(token: string, owner: string, spender: string, block: string) {
  const values = [token, owner, spender].map((value) => value.trim())
  if (values.some((value) => !/^0x[\da-fA-F]{40}$/.test(value))) {
    throw new Error('Token、owner 和 spender 都必须是完整的 EVM 地址。')
  }
  const height = block.trim()
  if (height && (!/^\d+$/.test(height) || !Number.isSafeInteger(Number(height)))) {
    throw new Error('区块号应为非负整数，不能包含小数或逗号。')
  }
  return { token: values[0]!, owner: values[1]!, spender: values[2]!, blockNumber: height ? Number(height) : null }
}

export function validateTokenBalanceQuery(token: string, owner: string, block: string) {
  const values = [token, owner].map((value) => value.trim())
  if (values.some((value) => !/^0x[\da-fA-F]{40}$/.test(value))) {
    throw new Error('Token 和 owner 都必须是完整的 EVM 地址。')
  }
  const height = block.trim()
  if (height && (!/^\d+$/.test(height) || !Number.isSafeInteger(Number(height)))) {
    throw new Error('区块号应为非负整数，不能包含小数或逗号。')
  }
  return { token: values[0]!, owner: values[1]!, blockNumber: height ? Number(height) : null }
}

export function assertTokenBalanceResult(
  data: Record<string, unknown>, config: UiConfig,
  query?: ReturnType<typeof validateTokenBalanceQuery>,
): asserts data is Record<string, unknown> & TokenBalanceResult {
  const invalid = (): never => { throw new ApiError('INVALID_RESPONSE', errorMessages.INVALID_RESPONSE!) }
  if (!data.evidence || typeof data.evidence !== 'object' || Array.isArray(data.evidence)
    || !Array.isArray(data.limitations)) invalid()
  const evidence = data.evidence as Record<string, unknown>
  if (evidence.network !== config.networkName || evidence.chainId !== config.expectedChainId
    || typeof evidence.provider !== 'string' || typeof evidence.observedAt !== 'string'
    || typeof evidence.evidenceId !== 'string' || !/^evidence:[\da-f]{64}$/.test(evidence.evidenceId as string)
    || typeof evidence.tokenAddress !== 'string' || !/^0x[\da-fA-F]{40}$/.test(evidence.tokenAddress as string)
    || typeof evidence.ownerAddress !== 'string' || !/^0x[\da-fA-F]{40}$/.test(evidence.ownerAddress as string)
    || typeof evidence.balanceSmallestUnit !== 'string' || !/^\d+$/.test(evidence.balanceSmallestUnit)
    || evidence.balanceSmallestUnit.length > 78 || BigInt(evidence.balanceSmallestUnit) > (1n << 256n) - 1n
    || !Number.isSafeInteger(evidence.blockNumber) || Number(evidence.blockNumber) < 0
    || typeof evidence.blockHash !== 'string' || !/^0x[\da-fA-F]{64}$/.test(evidence.blockHash as string)
    || typeof evidence.blockTimestamp !== 'string') invalid()
  if (evidence.decimals !== null && (!Number.isInteger(evidence.decimals) || Number(evidence.decimals) < 0 || Number(evidence.decimals) > 255)) invalid()
  if (evidence.balanceFormatted !== null && (typeof evidence.balanceFormatted !== 'string' || !/^\d+(\.\d+)?$/.test(evidence.balanceFormatted))) invalid()
  if (evidence.metadataError !== null && (typeof evidence.metadataError !== 'object' || !evidence.metadataError)) invalid()
  if (evidence.decimals === null) {
    const error = evidence.metadataError as Record<string, unknown> | null
    if (evidence.balanceFormatted !== null || !error || Array.isArray(error)
      || typeof error.code !== 'string' || typeof error.message !== 'string') invalid()
  } else {
    if (evidence.metadataError !== null) invalid()
    const decimals = Number(evidence.decimals)
    const amount = BigInt(String(evidence.balanceSmallestUnit))
    const divisor = 10n ** BigInt(decimals)
    const expected = decimals ? `${amount / divisor}.${String(amount % divisor).padStart(decimals, '0')}` : String(amount)
    if (evidence.balanceFormatted !== expected) invalid()
  }
  if (query && (String(evidence.tokenAddress).toLowerCase() !== query.token.toLowerCase()
    || String(evidence.ownerAddress).toLowerCase() !== query.owner.toLowerCase()
    || (query.blockNumber !== null && evidence.blockNumber !== query.blockNumber))) invalid()
  if ((data.limitations as unknown[]).some((item) => typeof item !== 'string')) invalid()
}

export function assertAllowanceResult(
  data: Record<string, unknown>, config: UiConfig,
  query?: ReturnType<typeof validateAllowanceQuery>,
): asserts data is Record<string, unknown> & AllowanceResult {
  const invalid = (): never => { throw new ApiError('INVALID_RESPONSE', errorMessages.INVALID_RESPONSE!) }
  if (!data.evidence || typeof data.evidence !== 'object' || Array.isArray(data.evidence)
    || !Array.isArray(data.findings) || !Array.isArray(data.limitations)) invalid()
  const evidence = data.evidence as Record<string, unknown>
  const findings = data.findings as unknown[]
  const limitations = data.limitations as unknown[]
  if (evidence.network !== config.networkName || evidence.chainId !== config.expectedChainId
    || typeof evidence.provider !== 'string' || typeof evidence.observedAt !== 'string'
    || typeof evidence.evidenceId !== 'string' || !/^evidence:[\da-f]{64}$/.test(evidence.evidenceId as string)
    || typeof evidence.tokenAddress !== 'string' || !/^0x[\da-fA-F]{40}$/.test(evidence.tokenAddress as string)
    || typeof evidence.ownerAddress !== 'string' || !/^0x[\da-fA-F]{40}$/.test(evidence.ownerAddress as string)
    || typeof evidence.spenderAddress !== 'string' || !/^0x[\da-fA-F]{40}$/.test(evidence.spenderAddress as string)
    || typeof evidence.allowanceSmallestUnit !== 'string' || !/^\d+$/.test(evidence.allowanceSmallestUnit)
    || evidence.allowanceSmallestUnit.length > 78
    || BigInt(evidence.allowanceSmallestUnit) > (1n << 256n) - 1n
    || !Number.isSafeInteger(evidence.blockNumber) || Number(evidence.blockNumber) < 0
    || typeof evidence.blockHash !== 'string'
    || !/^0x[\da-fA-F]{64}$/.test(evidence.blockHash as string)
    || typeof evidence.blockTimestamp !== 'string') invalid()
  if (query && (String(evidence.tokenAddress).toLowerCase() !== query.token.toLowerCase()
    || String(evidence.ownerAddress).toLowerCase() !== query.owner.toLowerCase()
    || String(evidence.spenderAddress).toLowerCase() !== query.spender.toLowerCase()
    || (query.blockNumber !== null && evidence.blockNumber !== query.blockNumber))) invalid()
  for (const finding of findings) {
    if (!finding || typeof finding !== 'object' || Array.isArray(finding)) invalid()
    const item = finding as Record<string, unknown>
    if (typeof item.findingId !== 'string' || typeof item.ruleId !== 'string'
      || !Number.isSafeInteger(item.ruleVersion) || Number(item.ruleVersion) < 1
      || item.severity !== 'attention' || !Array.isArray(item.evidenceIds)
      || typeof item.summary !== 'string') invalid()
    const evidenceIds = item.evidenceIds as unknown[]
    if (!evidenceIds.length || evidenceIds.some((value) => value !== evidence.evidenceId)) invalid()
  }
  if (limitations.some((item) => typeof item !== 'string')) invalid()
}
export function validateTransferActivityQuery(token: string, owner: string, fromBlock: string, toBlock: string) {
  const values = [token, owner].map((value) => value.trim())
  if (values.some((value) => !/^0x[\da-fA-F]{40}$/.test(value))) {
    throw new Error('Token 和 owner 都必须是完整的 EVM 地址。')
  }
  const heights = [fromBlock.trim(), toBlock.trim()]
  if (heights.some((value) => !/^\d+$/.test(value) || !Number.isSafeInteger(Number(value)))) {
    throw new Error('区块范围必须是非负整数，不能包含小数或逗号。')
  }
  const from = Number(heights[0])
  const to = Number(heights[1])
  if (to < from || to - from > 2000) throw new Error('区块范围必须正序且不超过 2000 个区块。')
  return { token: values[0]!, owner: values[1]!, fromBlock: from, toBlock: to }
}

export function assertTransferActivityResult(
  data: Record<string, unknown>, config: UiConfig,
  query?: ReturnType<typeof validateTransferActivityQuery>,
): asserts data is Record<string, unknown> & TransferActivityResult {
  const invalid = (): never => { throw new ApiError('INVALID_RESPONSE', errorMessages.INVALID_RESPONSE!) }
  if (data.network !== config.networkName || data.chainId !== config.expectedChainId
    || typeof data.provider !== 'string' || typeof data.observedAt !== 'string'
    || typeof data.tokenAddress !== 'string' || !/^0x[\da-fA-F]{40}$/.test(data.tokenAddress as string)
    || typeof data.ownerAddress !== 'string' || !/^0x[\da-fA-F]{40}$/.test(data.ownerAddress as string)
    || !Number.isSafeInteger(data.fromBlock) || Number(data.fromBlock) < 0
    || !Number.isSafeInteger(data.toBlock) || Number(data.toBlock) < Number(data.fromBlock)
    || Number(data.toBlock) - Number(data.fromBlock) > 2000
    || typeof data.evidenceId !== 'string' || !/^evidence:[\da-f]{64}$/.test(data.evidenceId as string)
    || !Array.isArray(data.events) || !Array.isArray(data.findings)
    || !Array.isArray(data.limitations)) invalid()
  if (query && (String(data.tokenAddress).toLowerCase() !== query.token.toLowerCase()
    || String(data.ownerAddress).toLowerCase() !== query.owner.toLowerCase()
    || data.fromBlock !== query.fromBlock || data.toBlock !== query.toBlock)) invalid()
  for (const event of data.events as unknown[]) {
    if (!event || typeof event !== 'object' || Array.isArray(event)) invalid()
    const item = event as Record<string, unknown>
    if (typeof item.transactionHash !== 'string' || !/^0x[\da-fA-F]{64}$/.test(item.transactionHash)
      || !Number.isSafeInteger(item.blockNumber) || Number(item.blockNumber) < Number(data.fromBlock)
      || Number(item.blockNumber) > Number(data.toBlock) || !Number.isSafeInteger(item.logIndex)
      || Number(item.logIndex) < 0 || typeof item.fromAddress !== 'string'
      || !/^0x[\da-fA-F]{40}$/.test(item.fromAddress) || typeof item.toAddress !== 'string'
      || !/^0x[\da-fA-F]{40}$/.test(item.toAddress) || typeof item.amountSmallestUnit !== 'string'
      || !/^\d+$/.test(item.amountSmallestUnit) || item.amountSmallestUnit.length > 78
      || BigInt(item.amountSmallestUnit) > (1n << 256n) - 1n) invalid()
  }
  for (const finding of data.findings as unknown[]) {
    if (!finding || typeof finding !== 'object' || Array.isArray(finding)) invalid()
    const item = finding as Record<string, unknown>
    if (typeof item.findingId !== 'string' || !/^finding:[\da-f]{64}$/.test(item.findingId)
      || typeof item.ruleId !== 'string' || !Number.isSafeInteger(item.ruleVersion)
      || Number(item.ruleVersion) < 1 || item.severity !== 'attention'
      || !Array.isArray(item.evidenceIds) || typeof item.summary !== 'string') invalid()
    const evidenceIds = item.evidenceIds as unknown[]
    if (!evidenceIds.length || evidenceIds.some((value) => value !== data.evidenceId)) invalid()
  }
  if ((data.events as unknown[]).length > 100 || (data.limitations as unknown[]).some((item) => typeof item !== 'string')) invalid()
}
export function assertResult(
  data: Record<string, unknown>, kind: QueryKind, config: UiConfig, subject: string,
): asserts data is Record<string, unknown> & (BalanceResult | ReceiptResult) {
  const invalid = (): never => { throw new ApiError('INVALID_RESPONSE', errorMessages.INVALID_RESPONSE!) }
  if (data.network !== config.networkName || data.chainId !== config.expectedChainId
    || typeof data.provider !== 'string' || typeof data.observedAt !== 'string') invalid()
  if (kind === 'balance') {
    if (typeof data.address !== 'string' || data.address.toLowerCase() !== subject.toLowerCase()
      || typeof data.balanceNative !== 'string' || !/^\d+(\.\d+)?$/.test(data.balanceNative)
      || typeof data.balanceSmallestUnit !== 'string' || !/^\d+$/.test(data.balanceSmallestUnit)
      || data.asset !== config.nativeSymbol || data.decimals !== config.nativeDecimals) invalid()
  } else {
    if (typeof data.transactionHash !== 'string' || data.transactionHash.toLowerCase() !== subject.toLowerCase()
      || (data.status !== 'pending' && data.status !== 'mined')) invalid()
    if (data.status === 'pending') {
      if (data.executionStatus != null || data.blockNumber != null || data.blockHash != null) invalid()
      return
    }
    if (data.executionStatus !== 'success' && data.executionStatus !== 'reverted') invalid()
  }
  if (!Number.isSafeInteger(data.blockNumber) || Number(data.blockNumber) < 0
    || typeof data.blockHash !== 'string' || !/^0x[\da-fA-F]{64}$/.test(data.blockHash)
    || typeof data.blockTimestamp !== 'string') invalid()
}

export function formatTime(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未知' : date.toLocaleString('zh-CN', { hour12: false })
}

export function shorten(value: string): string {
  return value.length > 23 ? `${value.slice(0, 10)}…${value.slice(-8)}` : value
}
