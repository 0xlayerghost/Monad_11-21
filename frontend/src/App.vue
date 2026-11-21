<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, createApi, friendlyError, validateInvestigationPrompt } from './api'
import type { InvestigationResult, UiConfig } from './api'
import { renderInvestigationAnswer } from './markdown'

const api = createApi()
const config = ref<UiConfig | null>(null)
const networkState = ref<'loading' | 'ready' | 'error'>('loading')
const networkError = ref('')
const prompt = ref('')
const loading = ref(false)
const queryError = ref('')
const result = ref<InvestigationResult | null>(null)
const copyStatus = ref('')
const elapsedSeconds = ref(0)
const renderedAnswer = computed(() => result.value?.answer ? renderInvestigationAnswer(result.value.answer) : '')
let queryController: AbortController | undefined
let networkController: AbortController | undefined
let elapsedTimer: ReturnType<typeof setInterval> | undefined

const samplePrompts = [
  {
    label: '核对示例交易',
    value: '查询 Monad 测试网交易 0xbb02e99311baec22c63e6cd49fb15da5ba3dd430aee32fd9be6aa899a349fe9b 的回执，引用区块号、区块 hash 和执行状态，并区分事实与未知。',
  },
  {
    label: '查询示例余额',
    value: '查询 Monad 测试网地址 0x6f49a8F621353f12378d0046E7d7e4b9B249DC9e 在区块 81521391 的 MON 余额，引用区块来源。',
  },
]

const toolLabels: Record<string, string> = {
  get_native_balance: '原生币余额',
  get_erc20_balance: '代币余额',
  get_erc20_allowance: '授权额度',
  get_erc20_transfer_activity: 'Transfer 活动',
  get_transaction_receipt: '交易回执',
}

function evidenceFor(event: InvestigationResult['trace'][number]): Array<{ label: string; value: string }> {
  const result = event.result
  if (!result || result.status !== 'ok' || !result.data || typeof result.data !== 'object' || Array.isArray(result.data)) return []
  const data = result.data as Record<string, unknown>
  const source = data.evidence && typeof data.evidence === 'object' && !Array.isArray(data.evidence)
    ? data.evidence as Record<string, unknown> : data
  const fields = [
    ['chainId', 'Chain ID'], ['blockNumber', '区块'], ['blockHash', '区块 hash'],
    ['transactionHash', '交易 hash'], ['provider', '数据源'], ['observedAt', '查询时间'],
  ] as const
  return fields.flatMap(([key, label]) => {
    const value = source[key]
    return typeof value === 'string' || typeof value === 'number' ? [{ label, value: String(value) }] : []
  })
}

function stopElapsedTimer() {
  if (elapsedTimer) clearInterval(elapsedTimer)
  elapsedTimer = undefined
}

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

async function submit() {
  if (loading.value || networkState.value !== 'ready') return
  queryError.value = ''
  copyStatus.value = ''
  let question: string
  try {
    question = validateInvestigationPrompt(prompt.value)
  } catch (error) {
    queryError.value = friendlyError(error)
    return
  }
  result.value = null
  const controller = new AbortController()
  queryController = controller
  loading.value = true
  elapsedSeconds.value = 0
  stopElapsedTimer()
  elapsedTimer = setInterval(() => { elapsedSeconds.value += 1 }, 1000)
  try {
    const data = await api.investigate(question, controller.signal)
    if (controller.signal.aborted) return
    result.value = data.error ? {
      ...data,
      error: {
        ...data.error,
        message: friendlyError(new ApiError(data.error.code, '模型调查未完成。')),
      },
    } : data
    if (data.status !== 'completed') {
      const code = data.error?.code ?? data.stopReason
      queryError.value = friendlyError(new ApiError(code, '调查没有完成。'))
    }
  } catch (error) {
    if (!controller.signal.aborted) queryError.value = friendlyError(error)
  } finally {
    if (queryController === controller) {
      loading.value = false
      queryController = undefined
      stopElapsedTimer()
    }
  }
}

function cancel() {
  queryController?.abort()
  queryController = undefined
  loading.value = false
  stopElapsedTimer()
}

function newInvestigation() {
  cancel()
  prompt.value = ''
  queryError.value = ''
  result.value = null
  copyStatus.value = ''
  document.getElementById('subject')?.focus()
}

function submitOnShortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    void submit()
  }
}

function useSample(value: string) {
  prompt.value = value
  queryError.value = ''
  document.getElementById('subject')?.focus()
}

async function copyResult() {
  if (!result.value) return
  try {
    await navigator.clipboard.writeText(JSON.stringify(result.value, null, 2))
    copyStatus.value = '已复制 JSON'
  } catch {
    copyStatus.value = '复制失败，请展开原始 JSON。'
  }
}

onMounted(connect)
onBeforeUnmount(() => {
  cancel()
  networkController?.abort()
  stopElapsedTimer()
})
</script>

<template>
  <div class="page">
    <header class="header">
      <a class="brand" href="/" aria-label="Monad 链证首页"><span class="brand-mark" aria-hidden="true">M</span><span>Monad <span class="brand-cn">链证</span></span></a>
      <div class="header-right">
        <div id="connection" class="connection" :class="networkState" role="status">
          <span class="status-dot" aria-hidden="true"></span>
          <span id="network-name">{{ config?.networkName ?? '连接服务' }}</span>
          <span class="connection-label">{{ networkState === 'ready' ? `已连接 · ${config?.expectedChainId}` : networkState === 'error' ? '未连接' : '校验中' }}</span>
          <button v-if="networkState === 'error'" class="text-button" type="button" @click="connect">重试</button>
        </div>
        <a class="header-link" href="/docs" target="_blank" rel="noreferrer">API 文档 ↗</a>
      </div>
    </header>

    <main>
      <div class="section-heading" :class="{ compact: result }">
        <div>
          <p class="eyebrow"><span class="eyebrow-line"></span> ONCHAIN INVESTIGATION <span class="divider">/</span> READ ONLY</p>
          <h1 v-if="!result">让结论回到区块<span class="heading-period">.</span></h1>
          <h1 v-else>调查委托</h1>
        </div>
      </div>

      <p v-if="networkError" class="notice error" role="alert">{{ networkError }}</p>

      <form id="query-form" class="investigation-form" @submit.prevent="submit">
        <div class="form-heading"><label for="subject">调查问题</label><span>READ ONLY <span class="form-indicator" aria-hidden="true"></span></span></div>
        <textarea id="subject" v-model="prompt" rows="5" maxlength="8000"
          placeholder="输入地址、代币或交易哈希，以及你要核对的问题…" :aria-invalid="Boolean(queryError && !result)"
          autocomplete="off" spellcheck="false" @keydown="submitOnShortcut"></textarea>
        <div v-if="!result && config?.networkName === 'monad-testnet'" class="sample-prompts" aria-label="示例查询">
          <button v-for="sample in samplePrompts" :key="sample.label" type="button" @click="useSample(sample.value)">{{ sample.label }} <span aria-hidden="true">↗</span></button>
        </div>
        <div class="form-actions">
          <div class="form-meta"><span class="character-count">{{ prompt.length }} / 8000</span></div>
          <div class="action-buttons">
            <button v-if="loading" class="secondary-button" type="button" @click="cancel">取消</button>
            <button class="primary-button" type="submit" :disabled="networkState !== 'ready' || loading">
              {{ loading ? '调查中' : '开始调查' }} <span v-if="!loading" aria-hidden="true">↗</span>
            </button>
          </div>
        </div>
        <p v-if="queryError && !result" id="query-error" class="notice error" role="alert">{{ queryError }}</p>
      </form>

      <section class="results" aria-label="调查结果" aria-live="polite" :aria-busy="loading">
        <div v-if="loading" class="pending-state">
          <div class="pending-top"><span><span class="loading-dot" aria-hidden="true"></span> 正在调查</span><time>{{ String(Math.floor(elapsedSeconds / 60)).padStart(2, '0') }}:{{ String(elapsedSeconds % 60).padStart(2, '0') }}</time></div>
          <p>正在等待模型与链上工具返回结果。</p>
          <div class="pending-line" aria-hidden="true"></div>
        </div>
        <div v-else-if="result" id="investigation-content">
          <div class="result-heading">
            <div>
              <p class="eyebrow">INVESTIGATION REPORT <span class="divider">/</span> 调查结果</p>
              <h2 :class="`result-${result.status}`"><span class="result-dot" aria-hidden="true"></span>{{ result.status === 'completed' ? '调查完成' : result.status === 'stopped' ? '调查已停止' : '调查失败' }}</h2>
            </div>
            <div class="result-actions"><button class="text-button" type="button" @click="copyResult">复制 JSON</button><button class="text-button new-button" type="button" @click="newInvestigation">新调查</button></div>
          </div>

          <div v-if="result.answer" class="answer-panel">
            <div class="answer-label"><span>调查结论</span><span>模型生成</span></div>
            <div class="agent-answer" v-html="renderedAnswer"></div>
            <p class="answer-caveat">请以下方工具返回的链上字段核对结论。</p>
          </div>
          <p v-if="queryError" class="notice error" role="alert">{{ queryError }}</p>
          <p v-if="result.error" class="error-code">{{ result.error.code }}<span v-if="result.error.details?.httpStatus"> · HTTP {{ result.error.details.httpStatus }}</span></p>

          <div class="run-stats" aria-label="调查调用统计">
            <div><span>模型调用</span><strong>{{ result.modelCalls }}</strong></div>
            <div><span>工具调用</span><strong>{{ result.toolCalls }}</strong></div>
            <div><span>输入 tokens</span><strong>{{ result.inputTokens.toLocaleString() }}</strong></div>
            <div><span>输出 tokens</span><strong>{{ result.outputTokens.toLocaleString() }}</strong></div>
          </div>
          <p v-if="copyStatus" class="copy-status" role="status">{{ copyStatus }}</p>

          <details class="trace-data">
            <summary>调用过程 <span>{{ result.trace.length }} 步</span></summary>
            <ol>
              <li v-for="(event, index) in result.trace" :key="`${event.step}-${event.kind}-${index}`">
                <span class="trace-node" aria-hidden="true">{{ index + 1 }}</span>
                <div class="trace-main">
                  <div class="trace-heading"><strong>第 {{ event.step }} 轮 · {{ event.kind === 'model' ? '模型请求' : toolLabels[event.toolName ?? ''] ?? event.toolName ?? '工具调用' }}</strong><span class="trace-kind">{{ event.kind === 'model' ? 'MODEL' : 'TOOL' }}</span></div>
                  <span v-if="event.kind === 'tool' && event.toolName" class="trace-tool">{{ event.toolName }}</span>
                  <span v-if="event.callId" class="trace-id">{{ event.callId }}</span>
                  <dl v-if="evidenceFor(event).length" class="evidence-list"><div v-for="item in evidenceFor(event)" :key="item.label"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl>
                  <details v-if="event.result" class="tool-raw"><summary>工具原始结果</summary><pre>{{ JSON.stringify(event.result, null, 2) }}</pre></details>
                </div>
              </li>
            </ol>
          </details>
          <details class="raw-data"><summary>原始 JSON</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
        </div>
      </section>
    </main>

    <footer><span>MONAD 链证 <span class="footer-divider">/</span> 只读调查</span><div><a href="/docs" target="_blank" rel="noreferrer">API 文档</a><a href="https://github.com/0xlayerghost/Monad_11-21" target="_blank" rel="noreferrer">GitHub</a></div></footer>
  </div>
</template>
