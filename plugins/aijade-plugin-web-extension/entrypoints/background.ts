import type {
  BackgroundToContentMessage,
  ContentToBackgroundMessage,
  ExtensionSettings,
} from '../src/shared/types'

import { defineInvokeHandler } from '@moeru/eventa'

import {
  createClientState,
  ensureClient,
  handlePageContext,
  handleSubtitle,
  handleVideoContext,
  toStatus,
} from '../src/background/client'
import { loadSettings, saveSettings } from '../src/background/storage'
import { DEFAULT_REST_BASE_URL, DEFAULT_SETTINGS, STORAGE_KEY } from '../src/shared/constants'
import {
  backgroundStatusChanged,
  popupClearError,
  popupGetStatus,
  popupRequestVisionFrame,
  popupToggleEnabled,
  popupUpdateSettings,
} from '../src/shared/eventa'
import { createRuntimeEventaContext } from '../src/shared/eventa-runtime'
import { sidepanelRequestEvidence } from '../src/shared/eventa-sidepanel'
import { summarize } from '../src/shared/llm'
import { detectSiteFromUrl } from '../src/shared/sites'
import { evaluatePageOpinion, reducePageToEvidence, reduceSubtitleToEvidence } from '../src/shared/v10-evidence'

const state = createClientState()

let settings: ExtensionSettings = { ...DEFAULT_SETTINGS }
let lastVideoNotifyKey = ''
let lastStatusSentAt = 0
let connectionKey = ''
let eventaContext: ReturnType<typeof createRuntimeEventaContext>['context'] | undefined

async function refreshClient() {
  const nextKey = `${settings.enabled}:${settings.wsUrl}:${settings.token}`
  if (nextKey !== connectionKey) {
    connectionKey = nextKey
    if (state.client)
      state.client.close()
    state.client = null
    state.connected = false
  }
  await ensureClient(state, settings)
}

function buildNotifyKey(payload: { url: string, title?: string, videoId?: string }) {
  return [payload.videoId, payload.title, payload.url].filter(Boolean).join('|')
}

function shouldNotifyVideo(payload: { url: string, title?: string, videoId?: string }) {
  const key = buildNotifyKey(payload)
  if (!key || key === lastVideoNotifyKey)
    return false
  lastVideoNotifyKey = key
  return true
}

/**
 * 侧边栏视图用 LLM 调用：与 `src/background/client.ts` 的 `makeLlm` 同口径
 * （绑定 baseUrl / model / token），但**不复用** client.ts 的内部函数
 * （避免改动 client.ts 文件所有权）。仅用于按需计算观点评价。
 */
function makeSidePanelLlm(settings: ExtensionSettings) {
  const baseUrl = settings.llmBaseUrl || DEFAULT_REST_BASE_URL
  const model = settings.llmModel || 'auto'
  const token = settings.bearerToken || undefined
  return (text: string, opts: { kind: 'page' | 'subtitle' | 'opinion' }) => summarize(text, { kind: opts.kind, baseUrl, model, token })
}

function emitStatus() {
  const now = Date.now()
  if (now - lastStatusSentAt < 300)
    return

  lastStatusSentAt = now
  eventaContext?.emit(backgroundStatusChanged, toStatus(state, settings))
}

async function updateSettings(partial: Partial<ExtensionSettings>) {
  settings = await saveSettings(partial)
  await refreshClient()
  emitStatus()
}

async function init() {
  settings = await loadSettings()
  await refreshClient()
  emitStatus()
}

function handleContentMessage(message: ContentToBackgroundMessage) {
  switch (message.type) {
    case 'content:page': {
      const payload = {
        ...message.payload,
        site: message.payload.site === 'unknown' ? detectSiteFromUrl(message.payload.url) : message.payload.site,
      }
      handlePageContext(state, settings, payload)
      emitStatus()
      break
    }
    case 'content:video': {
      const payload = {
        ...message.payload,
        site: message.payload.site === 'unknown' ? detectSiteFromUrl(message.payload.url) : message.payload.site,
      }
      handleVideoContext(state, settings, payload, { notify: shouldNotifyVideo(payload) })
      emitStatus()
      break
    }
    case 'content:subtitle': {
      const payload = {
        ...message.payload,
        site: message.payload.site === 'unknown' ? detectSiteFromUrl(message.payload.url) : message.payload.site,
      }
      handleSubtitle(state, settings, payload)
      emitStatus()
      break
    }
    case 'content:vision:frame': {
      state.lastVisionFrameAt = Date.now()
      emitStatus()
      break
    }
  }
}

export default defineBackground(() => {
  const { context } = createRuntimeEventaContext()
  eventaContext = context

  defineInvokeHandler(context, popupGetStatus, () => toStatus(state, settings))
  defineInvokeHandler(context, popupUpdateSettings, async (partial) => {
    await updateSettings(partial)
    return toStatus(state, settings)
  })

  defineInvokeHandler(context, popupToggleEnabled, async (enabled) => {
    await updateSettings({ enabled })
    return toStatus(state, settings)
  })

  defineInvokeHandler(context, popupRequestVisionFrame, async () => {
    const message: BackgroundToContentMessage = { type: 'background:request-vision-frame' }
    const tabs = await browser.tabs.query({ active: true, currentWindow: true })
    const tab = tabs[0]
    if (tab?.id != null) {
      await browser.tabs.sendMessage(tab.id, message).catch(() => {})
    }

    return toStatus(state, settings)
  })

  defineInvokeHandler(context, popupClearError, () => {
    state.lastError = undefined
    emitStatus()
    return toStatus(state, settings)
  })

  // 侧边栏 Companion：请求当前标签页的归约结果（确定性归约 + 可选 LLM 观点评价）。
  // 复用既有 eventa 约定，不新造通信层；侧边栏只展示，不直接调 LLM。
  defineInvokeHandler(context, sidepanelRequestEvidence, async (req) => {
    const status = toStatus(state, settings)
    const pageEvidence = state.lastPage ? reducePageToEvidence(state.lastPage) : null
    const subtitleEvidence = state.lastSubtitle ? reduceSubtitleToEvidence(state.lastSubtitle) : null
    let opinion: import('../src/shared/v10-evidence').OpinionEvaluationPayload | null = null
    if (req?.includeOpinion && state.lastPage) {
      try {
        opinion = await evaluatePageOpinion(state.lastPage, makeSidePanelLlm(settings))
      }
      catch {
        opinion = null
      }
    }
    return { status, pageEvidence, subtitleEvidence, opinion }
  })

  void init()

  browser.runtime.onMessage.addListener((message: unknown) => {
    if (!message || typeof message !== 'object')
      return
    if ('__eventa' in message)
      return
    if ('type' in message && typeof message.type === 'string' && message.type.startsWith('content:')) {
      handleContentMessage(message as ContentToBackgroundMessage)
    }
  })

  browser.storage.onChanged.addListener((changes) => {
    if (changes[STORAGE_KEY]) {
      const next = changes[STORAGE_KEY].newValue as ExtensionSettings | undefined
      settings = { ...DEFAULT_SETTINGS, ...next }
      void refreshClient()
      emitStatus()
    }
  })
})
