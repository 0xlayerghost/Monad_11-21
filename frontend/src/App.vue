<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ApiError, assertAllowanceResult, assertResult, assertTokenBalanceResult, createApi, formatTime, friendlyError,
  validateAllowanceQuery, validateInvestigationPrompt, validateQuery, validateTokenBalanceQuery, validateTransferActivityQuery,
  assertTransferActivityResult,
} from './api'
import type {
  AllowanceResult, BalanceResult, InvestigationResult, ReceiptResult, TokenBalanceResult, TransferActivityResult, UiConfig, WorkbenchKind,
} from './api'

const api = createApi()
const config = ref<UiConfig | null>(null)
const networkState = ref<'loading' | 'ready' | 'error'>('loading')
const networkError = ref('')
const tabs: WorkbenchKind[] = ['balance', 'token-balance', 'receipt', 'allowance', 'activity', 'investigation']
const kind = ref<WorkbenchKind>('balance')
const subject = ref('')
const tokenAddress = ref('')
const ownerAddress = ref('')
const spenderAddress = ref('')
const fromBlock = ref('')
const toBlock = ref('')
const blockNumber = ref('')
const loading = ref(false)
const queryError = ref('')
const result = ref<BalanceResult | ReceiptResult | AllowanceResult | TokenBalanceResult | TransferActivityResult | null>(null)
const investigationResult = ref<InvestigationResult | null>(null)
const copyStatus = ref('')
let queryController: AbortController | undefined
let networkController: AbortController | undefined

const balance = computed(() => result.value && 'balanceNative' in result.value ? result.value : null)
const receipt = computed(() => result.value && 'transactionHash' in result.value ? result.value : null)
function isAllowance(value: NonNullable<typeof result.value>): value is AllowanceResult {
  return 'evidence' in value && 'allowanceSmallestUnit' in value.evidence
}
function isActivity(value: NonNullable<typeof result.value>): value is TransferActivityResult {
  return 'events' in value && 'evidenceId' in value
}
function isTokenBalance(value: NonNullable<typeof result.value>): value is TokenBalanceResult {
  return 'evidence' in value && 'balanceSmallestUnit' in value.evidence
}
const allowance = computed(() => result.value && isAllowance(result.value) ? result.value : null)
const tokenBalance = computed(() => result.value && isTokenBalance(result.value) ? result.value : null)
const activity = computed(() => result.value && isActivity(result.value) ? result.value : null)
const receiptStatus = computed(() => receipt.value?.status === 'pending'
  ? '等待打包' : receipt.value?.executionStatus === 'success' ? '执行成功' : '执行回滚')
const evidence = computed(() => {
  if (!result.value) return []
  if (tokenBalance.value) return [
    ['Token', tokenBalance.value.evidence.tokenAddress],
    ['Owner', tokenBalance.value.evidence.ownerAddress],
    ['最小单位余额', tokenBalance.value.evidence.balanceSmallestUnit],
    ['Decimals', tokenBalance.value.evidence.decimals ?? '未知'],
    ['可读余额', tokenBalance.value.evidence.balanceFormatted ?? '未知（仅保留最小单位）'],
    ['区块', tokenBalance.value.evidence.blockNumber],
    ['区块哈希', tokenBalance.value.evidence.blockHash],
    ['Evidence ID', tokenBalance.value.evidence.evidenceId],
    ['网络', `${tokenBalance.value.evidence.network} · Chain ID ${tokenBalance.value.evidence.chainId}`],
    ['区块时间', formatTime(tokenBalance.value.evidence.blockTimestamp)],
    ['数据来源', tokenBalance.value.evidence.provider],
    ['查询时间', formatTime(tokenBalance.value.evidence.observedAt)],
  ]
  if (activity.value) return [
    ['Token', activity.value.tokenAddress],
    ['Owner', activity.value.ownerAddress],
    ['Block range', `${activity.value.fromBlock} - ${activity.value.toBlock}`],
    ['Events', activity.value.events.length],
    ['Evidence ID', activity.value.evidenceId],
    ['Network', `${activity.value.network} ? Chain ID ${activity.value.chainId}`],
    ['Observed at', formatTime(activity.value.observedAt)],
    ['Provider', activity.value.provider],
  ]
  if (isAllowance(result.value)) return [
    ['Token', result.value.evidence.tokenAddress],
    ['Owner', result.value.evidence.ownerAddress],
    ['Spender', result.value.evidence.spenderAddress],
    ['授权最小单位', result.value.evidence.allowanceSmallestUnit],
    ['区块', result.value.evidence.blockNumber],
    ['区块哈希', result.value.evidence.blockHash],
    ['Evidence ID', result.value.evidence.evidenceId],
    ['网络', `${result.value.evidence.network} · Chain ID ${result.value.evidence.chainId}`],
    ['区块时间', formatTime(result.value.evidence.blockTimestamp)],
    ['数据来源', result.value.evidence.provider],
    ['查询时间', formatTime(result.value.evidence.observedAt)],
  ]
  if ('evidence' in result.value) return []
  const data = result.value as BalanceResult | ReceiptResult
  const rows = [
    ['网络', `${data.network} · Chain ID ${data.chainId}`],
    ['区块号', data.blockNumber ?? '尚未打包'],
    ['区块哈希', data.blockHash ?? '—'],
    ['区块时间', formatTime(data.blockTimestamp)],
    ['数据来源', data.provider],
    ['查询时间', formatTime(data.observedAt)],
  ]
  if (balance.value) rows.unshift(['地址', balance.value.address], ['最小单位余额', balance.value.balanceSmallestUnit])
  if (receipt.value) rows.unshift(['交易哈希', receipt.value.transactionHash], ['Gas 用量', receipt.value.gasUsed ?? '—'])
  return rows
})

async function connect() {
  networkController?.abort()
  const controller = new AbortController()
  networkController = controller
  networkState.value = 'loading'
  networkError.value = ''
  try {
    const settings = await api.getConfig(controller.signal)
    if (controller.signal.aborted) return
    config.value = settings
    const status = await api.getStatus(settings.networkName, controller.signal)
    if (controller.signal.aborted) return
    if (status.status !== 'ready' || status.network !== settings.networkName
      || status.chainId !== settings.expectedChainId || status.expectedChainId !== settings.expectedChainId) {
      throw new ApiError('CHAIN_ID_MISMATCH', '网络校验没有通过。')
    }
    networkState.value = 'ready'
  } catch (error) {
    if (controller.signal.aborted) return
    networkState.value = 'error'
    networkError.value = friendlyError(error)
  }
}

function switchKind(next: WorkbenchKind) {
  if (kind.value === next) return
  queryController?.abort()
  kind.value = next
  subject.value = ''
  tokenAddress.value = ''
  ownerAddress.value = ''
  spenderAddress.value = ''
  fromBlock.value = ''
  toBlock.value = ''
  blockNumber.value = ''
  queryError.value = ''
  copyStatus.value = ''
  result.value = null
  investigationResult.value = null
  loading.value = false
}

function navigateTabs(event: KeyboardEvent) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const current = tabs.indexOf(kind.value)
  const next = event.key === 'Home' ? tabs[0]! : event.key === 'End' ? tabs[tabs.length - 1]!
    : tabs[(current + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]!
  switchKind(next)
  document.getElementById(`${next}-tab`)?.focus()
}

async function submit() {
  queryController?.abort()
  result.value = null
  investigationResult.value = null
  copyStatus.value = ''
  queryError.value = ''
  if (!config.value || networkState.value !== 'ready') return
  const controller = new AbortController()
  queryController = controller
  try {
    loading.value = true
    if (kind.value === 'activity') {
      const query = validateTransferActivityQuery(tokenAddress.value, ownerAddress.value, fromBlock.value, toBlock.value)
      const data = await api.getTransferActivity(config.value.networkName, query.token, query.owner, query.fromBlock, query.toBlock, controller.signal)
      if (controller.signal.aborted) return
      assertTransferActivityResult(data, config.value, query)
      result.value = data
      return
    }
    if (kind.value === 'token-balance') {
      const query = validateTokenBalanceQuery(tokenAddress.value, ownerAddress.value, blockNumber.value)
      const data = await api.getTokenBalance(config.value.networkName, query.token, query.owner, query.blockNumber, controller.signal)
      if (controller.signal.aborted) return
      assertTokenBalanceResult(data, config.value, query)
      result.value = data
      return
    }
    if (kind.value === 'allowance') {
      const query = validateAllowanceQuery(tokenAddress.value, ownerAddress.value, spenderAddress.value, blockNumber.value)
      const data = await api.getAllowance(config.value.networkName, query.token, query.owner, query.spender, query.blockNumber, controller.signal)
      if (controller.signal.aborted) return
      assertAllowanceResult(data, config.value, query)
      result.value = data
      return
    }
    if (kind.value === 'investigation') {
      const prompt = validateInvestigationPrompt(subject.value)
      const data = await api.investigate(prompt, controller.signal)
      if (controller.signal.aborted) return
      investigationResult.value = data
      if (data.status !== 'completed') {
        const code = data.error?.code ?? data.stopReason
        queryError.value = friendlyError(new ApiError(code, data.error?.message ?? '调查没有完成。'))
      }
      return
    }
    const query = validateQuery(kind.value, subject.value, blockNumber.value)
    const data = kind.value === 'balance'
      ? await api.getBalance(config.value.networkName, query.subject, query.blockNumber, controller.signal)
      : await api.getReceipt(config.value.networkName, query.subject, controller.signal)
    if (controller.signal.aborted) return
    assertResult(data, kind.value, config.value, query.subject)
    result.value = data
  } catch (error) {
    if (!controller.signal.aborted) queryError.value = friendlyError(error)
  } finally {
    if (queryController === controller) loading.value = false
  }
}

async function copyResult() {
  const data = investigationResult.value ?? result.value
  if (!data) return
  try {
    await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
    copyStatus.value = '已复制'
  } catch {
    copyStatus.value = '复制失败，可以展开 JSON 手动复制。'
  }
}

onMounted(connect)
onBeforeUnmount(() => {
  queryController?.abort()
  networkController?.abort()
})
</script>

<template>
  <div class="page">
    <header class="header">
      <a class="brand" href="/" aria-label="链上手记首页"><span class="brand-mark" aria-hidden="true">↗</span>链上手记</a>
      <div id="connection" class="connection" :class="networkState" role="status">
        <span class="status-dot" aria-hidden="true"></span>
        <span id="network-name">{{ config?.networkName ?? '连接服务' }}</span>
        <span class="connection-label">{{ networkState === 'ready' ? '已连接' : networkState === 'error' ? '未连接' : '校验中' }}</span>
        <button v-if="networkState === 'error'" class="text-button" type="button" @click="connect">重试</button>
      </div>
    </header>

    <main>
      <section class="intro" aria-labelledby="page-title">
        <p class="eyebrow">一个简单的链上查询工具</p>
        <h1 id="page-title">先查一笔。</h1>
        <p>贴个地址、查笔交易，或者让只读 Agent 带着链上证据回答。</p>
      </section>

      <p v-if="networkError" class="notice error" role="alert">{{ networkError }}</p>

      <section class="query-card" aria-label="链上查询">
        <div class="tabs" role="tablist" aria-label="查询类型" @keydown="navigateTabs">
          <button v-for="tab in tabs" :id="`${tab}-tab`" :key="tab"
            type="button" role="tab" :aria-selected="kind === tab" aria-controls="query-panel"
            :tabindex="kind === tab ? 0 : -1" :class="{ active: kind === tab }" @click="switchKind(tab)">
            {{ tab === 'balance' ? 'Native balance' : tab === 'token-balance' ? 'Token balance' : tab === 'receipt' ? 'Transaction' : tab === 'allowance' ? 'Allowance' : tab === 'activity' ? 'Transfer activity' : 'AI investigation' }}
          </button>
        </div>

        <div id="query-panel" role="tabpanel" :aria-labelledby="`${kind}-tab`">
          <form id="query-form" aria-describedby="query-hint" @submit.prevent="submit">
            <template v-if="kind === 'activity'">
              <label for="token-address">Token ????</label>
              <input id="token-address" v-model="tokenAddress" type="text" autocomplete="off" spellcheck="false" />
              <label for="owner-address">Owner ??</label>
              <input id="owner-address" v-model="ownerAddress" type="text" autocomplete="off" spellcheck="false" />
              <div class="input-row">
                <div class="field-group"><label for="from-block">From block</label><input id="from-block" v-model="fromBlock" type="text" inputmode="numeric" /></div>
                <div class="field-group"><label for="to-block">To block</label><input id="to-block" v-model="toBlock" type="text" inputmode="numeric" /></div>
                <button class="primary-button" type="submit" :disabled="networkState !== 'ready' || loading">{{ loading ? '????' : '????' }}<span v-if="!loading" aria-hidden="true">?</span></button>
              </div>
            </template>
            <template v-else-if="kind === 'allowance' || kind === 'token-balance'">
              <label for="token-address">Token 合约地址</label>
              <input id="token-address" v-model="tokenAddress" type="text" autocomplete="off" spellcheck="false" />
              <label for="owner-address">Owner 地址</label>
              <input id="owner-address" v-model="ownerAddress" type="text" autocomplete="off" spellcheck="false" />
              <template v-if="kind === 'allowance'">
                <label for="spender-address">Spender 地址</label>
                <input id="spender-address" v-model="spenderAddress" type="text" autocomplete="off" spellcheck="false" />
              </template>
              <div class="input-row">
                <button class="primary-button" type="submit" :disabled="networkState !== 'ready' || loading">
                  {{ loading ? '查询中…' : kind === 'allowance' ? '查询授权' : '查询代币余额' }}<span v-if="!loading" aria-hidden="true">↗</span>
                </button>
              </div>
            </template>
            <template v-else>
              <label for="subject">{{ kind === 'balance' ? '钱包地址' : kind === 'receipt' ? '交易哈希' : '调查问题' }}</label>
              <div class="input-row" :class="{ 'investigation-row': kind === 'investigation' }">
                <textarea v-if="kind === 'investigation'" id="subject" v-model="subject" rows="5" maxlength="8000"></textarea>
                <input id="subject" v-else v-model="subject" type="text" autocomplete="off" spellcheck="false" />
                <button class="primary-button" type="submit" :disabled="networkState !== 'ready' || loading">
                  {{ loading ? (kind === 'investigation' ? '调查中…' : '查询中…') : (kind === 'investigation' ? '开始调查' : '查询') }}<span v-if="!loading" aria-hidden="true">↗</span>
                </button>
              </div>
            </template>
            <p id="query-hint" class="hint">{{ kind === 'balance' ? 'Native asset only.' : kind === 'token-balance' ? 'Reads balanceOf(owner); no spender is required.' : kind === 'receipt' ? 'Check the selected network.' : kind === 'allowance' ? 'Read-only allowance query; no approve transaction is sent.' : kind === 'activity' ? 'Reads bounded Transfer events; does not derive current balance or safety.' : 'Ask the read-only model about supported chain facts.' }}</p>
            <details v-if="kind === 'balance' || kind === 'token-balance' || kind === 'allowance'" class="block-option">
              <summary>指定区块 <span>可选</span></summary>
              <label for="block-number" class="visually-hidden">区块号</label>
              <input id="block-number" v-model="blockNumber" type="text" inputmode="numeric" placeholder="留空读取最新区块" autocomplete="off" />
            </details>
            <p v-if="queryError" id="query-error" class="notice error" role="alert">{{ queryError }}</p>
          </form>
        </div>
      </section>

      <section class="results" aria-label="查询结果" aria-live="polite" :aria-busy="loading">
        <div v-if="loading" class="empty-state"><span class="loading-dot" aria-hidden="true"></span>{{ kind === 'investigation' ? '模型正在选择只读工具并整理证据。' : '正在向节点确认，稍等一下。' }}</div>
        <div v-else-if="investigationResult" id="investigation-content">
          <div class="result-heading">
            <div>
              <p class="eyebrow">AI 只读调查</p>
              <h2>{{ investigationResult.status === 'completed' ? '调查完成' : investigationResult.status === 'stopped' ? '达到执行边界' : '调查失败' }}</h2>
            </div>
            <button type="button" class="text-button" @click="copyResult">复制 JSON</button>
          </div>
          <div v-if="investigationResult.answer" class="agent-answer">{{ investigationResult.answer }}</div>
          <p v-else class="notice error">{{ queryError ?? investigationResult.error?.message ?? `停止原因：${investigationResult.stopReason}` }}</p>
          <p v-if="investigationResult.error" class="hint">
            错误代码：{{ investigationResult.error.code }}
            <span v-if="investigationResult.error.details?.httpStatus"> · HTTP {{ investigationResult.error.details.httpStatus }}</span>
          </p>
          <div class="run-stats" aria-label="调查调用统计">
            <span>模型 {{ investigationResult.modelCalls }} 次</span>
            <span>工具 {{ investigationResult.toolCalls }} 次</span>
            <span>输入 {{ investigationResult.inputTokens }} tokens</span>
            <span>输出 {{ investigationResult.outputTokens }} tokens</span>
          </div>
          <p v-if="copyStatus" class="hint" role="status">{{ copyStatus }}</p>
          <details class="trace-data" open>
            <summary>查看调用过程（{{ investigationResult.trace.length }} 步）</summary>
            <ol>
              <li v-for="(event, index) in investigationResult.trace" :key="`${event.step}-${event.kind}-${index}`">
                <strong>第 {{ event.step }} 轮 · {{ event.kind === 'model' ? '模型请求' : `工具调用：${event.toolName}` }}</strong>
                <span v-if="event.callId">调用 ID：{{ event.callId }}</span>
                <pre v-if="event.result">{{ JSON.stringify(event.result, null, 2) }}</pre>
              </li>
            </ol>
          </details>
          <details class="raw-data"><summary>查看完整原始 JSON</summary><pre>{{ JSON.stringify(investigationResult, null, 2) }}</pre></details>
        </div>
        <div v-else-if="activity" id="activity-content">
          <div class="result-heading">
            <div><p class="eyebrow">ERC-20 Transfer 活动</p><h2 id="activity-count">{{ activity.events.length }} 条事件</h2></div>
            <button type="button" class="text-button" @click="copyResult">复制 JSON</button>
          </div>
          <p v-if="copyStatus" class="hint" role="status">{{ copyStatus }}</p>
          <dl class="evidence"><div v-for="[label, value] in evidence" :key="String(label)"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <h3>Transfer 事件</h3>
          <div v-if="!activity.events.length" class="hint">该区块范围内未返回与此 Owner 相关的 Transfer 事件。</div>
          <ol v-else class="event-list"><li v-for="event in activity.events" :key="`${event.transactionHash}-${event.logIndex}`"><code>{{ event.transactionHash }}</code><span>区块 {{ event.blockNumber }} · 日志 {{ event.logIndex }} · 最小单位 {{ event.amountSmallestUnit }}</span><span>{{ event.fromAddress }} → {{ event.toAddress }}</span></li></ol>
          <h3>规则关注项</h3>
          <div v-for="finding in activity.findings" :key="finding.findingId" class="notice">
            <p>{{ finding.summary }}</p>
            <p class="hint">规则：{{ finding.ruleId }} · 级别：{{ finding.severity }}</p>
            <p class="hint">关联证据：{{ finding.evidenceIds.join('、') }}</p>
          </div>
          <p v-if="!activity.findings.length" class="hint">未命中当前两条零地址事件规则，不代表 Token 或活动安全。</p>
          <h3>说明与限制</h3>
          <ul><li v-for="limitation in activity.limitations" :key="limitation">{{ limitation }}</li></ul>
          <details class="raw-data"><summary>查看原始 JSON</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
        </div>
        <div v-else-if="tokenBalance" id="token-balance-content">
          <div class="result-heading">
            <div><p class="eyebrow">ERC-20 代币余额</p><h2 id="token-balance-value">{{ tokenBalance.evidence.balanceFormatted ?? tokenBalance.evidence.balanceSmallestUnit }}</h2></div>
            <button type="button" class="text-button" @click="copyResult">复制 JSON</button>
          </div>
          <p v-if="tokenBalance.evidence.metadataError" class="notice">Decimals 元数据读取失败，仅展示最小单位余额。</p>
          <p v-if="copyStatus" class="hint" role="status">{{ copyStatus }}</p>
          <dl class="evidence"><div v-for="[label, value] in evidence" :key="String(label)"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <h3>说明与限制</h3>
          <ul><li v-for="limitation in tokenBalance.limitations" :key="limitation">{{ limitation }}</li></ul>
          <details class="raw-data"><summary>查看原始 JSON</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
        </div>
        <div v-else-if="allowance" id="allowance-content">
          <div class="result-heading">
            <div>
              <p class="eyebrow">ERC-20 授权（最小单位）</p>
              <h2 id="allowance-value">{{ allowance.evidence.allowanceSmallestUnit }}</h2>
            </div>
            <button type="button" class="text-button" @click="copyResult">复制 JSON</button>
          </div>
          <p v-if="copyStatus" class="hint" role="status">{{ copyStatus }}</p>
          <dl class="evidence"><div v-for="[label, value] in evidence" :key="String(label)"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <h3>规则关注项</h3>
          <div v-for="finding in allowance.findings" :key="finding.findingId" class="notice">
            <p>{{ finding.summary }}</p>
            <p class="hint">规则：{{ finding.ruleId }} · 级别：{{ finding.severity }}</p>
            <p class="hint">关联证据：{{ finding.evidenceIds.join('、') }}</p>
          </div>
          <p v-if="!allowance.findings.length" class="hint">本次未命中最大授权规则，不代表合约或授权安全。</p>
          <h3>说明与限制</h3>
          <ul><li v-for="limitation in allowance.limitations" :key="limitation">{{ limitation }}</li></ul>
          <details class="raw-data"><summary>查看原始 JSON</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
        </div>
        <div v-else-if="result" id="result-content">
          <div class="result-heading">
            <div>
              <p class="eyebrow">{{ balance ? '原生币余额' : '交易状态' }}</p>
              <h2 :class="{ reverted: receipt?.executionStatus === 'reverted' }"><span id="result-value">{{ balance?.balanceNative ?? receiptStatus }}</span><small v-if="balance">{{ balance.asset }}</small></h2>
            </div>
            <button type="button" class="text-button" @click="copyResult">复制 JSON</button>
          </div>
          <p v-if="receipt?.status === 'pending'" class="hint">节点已看到这笔交易，但还没有回执。过一会儿可以再查一次。</p>
          <p v-else-if="receipt?.executionStatus === 'reverted'" class="hint">交易已打包，但执行回滚；这不代表没有消耗 Gas。</p>
          <p v-if="copyStatus" class="hint" role="status">{{ copyStatus }}</p>
          <dl class="evidence"><div v-for="[label, value] in evidence" :key="String(label)"><dt>{{ label }}</dt><dd>{{ value }}</dd></div></dl>
          <details class="raw-data"><summary>查看原始 JSON</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
        </div>
        <div v-else class="empty-state"><span aria-hidden="true">⌁</span><p>{{ queryError ? '改好输入，再试一次。' : '结果会出现在这里。' }}</p></div>
      </section>
    </main>

    <footer><span>只读查询，不连接钱包，不签名；模型答案需结合 trace 中的证据判断。</span><a href="/docs" target="_blank" rel="noreferrer">API 文档 ↗</a></footer>
  </div>
</template>
