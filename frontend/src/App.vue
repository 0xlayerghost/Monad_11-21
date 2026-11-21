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
const renderedAnswer = computed(() => result.value?.answer ? renderInvestigationAnswer(result.value.answer) : '')
let queryController: AbortController | undefined
let networkController: AbortController | undefined

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
    }
  }
}

function cancel() {
  queryController?.abort()
  queryController = undefined
  loading.value = false
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
})
</script>

<template>
  <div class="page">
    <header class="header">
      <a class="brand" href="/" aria-label="链上调查首页"><span class="brand-mark" aria-hidden="true">M</span><span>链上调查</span></a>
      <div id="connection" class="connection" :class="networkState" role="status">
        <span class="status-dot" aria-hidden="true"></span>
        <span id="network-name">{{ config?.networkName ?? '连接服务' }}</span>
        <span class="connection-label">{{ networkState === 'ready' ? '已连接' : networkState === 'error' ? '未连接' : '校验中' }}</span>
        <button v-if="networkState === 'error'" class="text-button" type="button" @click="connect">重试</button>
      </div>
    </header>

    <main>
      <div class="section-heading">
        <div>
          <p class="eyebrow">AI INVESTIGATION <span class="divider">/</span> READ ONLY</p>
          <h1>开始调查</h1>
        </div>
        <button v-if="result || queryError" class="text-button new-button" type="button" @click="newInvestigation">新调查</button>
      </div>

      <p v-if="networkError" class="notice error" role="alert">{{ networkError }}</p>

      <form id="query-form" class="investigation-form" @submit.prevent="submit">
        <label class="visually-hidden" for="subject">调查问题</label>
        <textarea id="subject" v-model="prompt" rows="5" maxlength="8000"
          placeholder="输入要调查的地址、交易或链上问题…" :aria-invalid="Boolean(queryError && !result)"
          autocomplete="off" spellcheck="false" @keydown="submitOnShortcut"></textarea>
        <div class="form-actions">
          <span class="character-count">{{ prompt.length }} / 8000</span>
          <div class="action-buttons">
            <button v-if="loading" class="secondary-button" type="button" @click="cancel">取消</button>
            <button class="primary-button" type="submit" :disabled="networkState !== 'ready' || loading">
              {{ loading ? '调查中' : '开始调查' }}
            </button>
          </div>
        </div>
        <p v-if="queryError && !result" id="query-error" class="notice error" role="alert">{{ queryError }}</p>
      </form>

      <section class="results" aria-label="调查结果" aria-live="polite" :aria-busy="loading">
        <div v-if="loading" class="pending-state"><span class="loading-dot" aria-hidden="true"></span>正在调查</div>
        <div v-else-if="result" id="investigation-content">
          <div class="result-heading">
            <div>
              <p class="eyebrow">调查结果</p>
              <h2>{{ result.status === 'completed' ? '调查完成' : result.status === 'stopped' ? '调查已停止' : '调查失败' }}</h2>
            </div>
            <button class="text-button" type="button" @click="copyResult">复制 JSON</button>
          </div>

          <div v-if="result.answer" class="agent-answer" v-html="renderedAnswer"></div>
          <p v-if="queryError" class="notice error" role="alert">{{ queryError }}</p>
          <p v-if="result.error" class="error-code">{{ result.error.code }}<span v-if="result.error.details?.httpStatus"> · HTTP {{ result.error.details.httpStatus }}</span></p>

          <div class="run-stats" aria-label="调查调用统计">
            <span>模型 {{ result.modelCalls }} 次</span>
            <span>工具 {{ result.toolCalls }} 次</span>
            <span>输入 {{ result.inputTokens }} tokens</span>
            <span>输出 {{ result.outputTokens }} tokens</span>
          </div>
          <p v-if="copyStatus" class="copy-status" role="status">{{ copyStatus }}</p>

          <details class="trace-data">
            <summary>调用过程 <span>{{ result.trace.length }} 步</span></summary>
            <ol>
              <li v-for="(event, index) in result.trace" :key="`${event.step}-${event.kind}-${index}`">
                <strong>第 {{ event.step }} 轮 · {{ event.kind === 'model' ? '模型请求' : `工具调用：${event.toolName}` }}</strong>
                <span v-if="event.callId" class="trace-id">{{ event.callId }}</span>
                <pre v-if="event.result">{{ JSON.stringify(event.result, null, 2) }}</pre>
              </li>
            </ol>
          </details>
          <details class="raw-data"><summary>原始 JSON</summary><pre>{{ JSON.stringify(result, null, 2) }}</pre></details>
        </div>
        <div v-else class="empty-state">尚无调查结果</div>
      </section>
    </main>

    <footer><span>只读调查 · 不连接钱包或签名</span><a href="/docs" target="_blank" rel="noreferrer">API 文档</a></footer>
  </div>
</template>
