import type { OidcTokenSet } from '../src/shared/oidc'
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
  handleSelection,
  handleSubtitle,
  handleVideoContext,
  reportV9Constraint,
  toStatus,
} from '../src/background/client'
import { getOrCreateInstallId, loadOidcTokens, loadSettings, saveOidcLoginState, saveOidcTokens, saveSettings } from '../src/background/storage'
import { DEFAULT_REST_BASE_URL, DEFAULT_SETTINGS, STORAGE_KEY } from '../src/shared/constants'
import { getActiveOidcTokens, setActiveOidcTokens } from '../src/shared/credentials'
import {
  backgroundStatusChanged,
  popupClearError,
  popupGetOidcStatus,
  popupGetStatus,
  popupLogoutOidc,
  popupRequestVisionFrame,
  popupStartOidcLogin,
  popupToggleEnabled,
  popupUpdateSettings,
} from '../src/shared/eventa'
import { createRuntimeEventaContext } from '../src/shared/eventa-runtime'
import { sidepanelRequestEvidence } from '../src/shared/eventa-sidepanel'
import { summarize } from '../src/shared/llm'
import { buildExtensionRedirectUri, fetchOidcTokens } from '../src/shared/oidc'
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
  // 重新加热持久化的 OIDC 令牌，使同步 `resolveApiToken` 立即可用。
  const storedTokens = await loadOidcTokens()
  if (storedTokens)
    setActiveOidcTokens(storedTokens)
  await refreshClient()
  emitStatus()
}

/**
 * 包装 `chrome.identity.launchWebAuthFlow`：用户取消/出错时回调得到 undefined（或
 * `chrome.runtime.lastError`），统一解析为 `undefined` 给上层归类为 `cancelled`。
 */
function launchWebAuthFlow(url: string, _interactive: boolean): Promise<string | undefined> {
  return new Promise((resolve) => {
    browser.identity.launchWebAuthFlow({ url, interactive: true }, (responseUrl?: string) => {
      if (browser.runtime.lastError || !responseUrl) {
        resolve(undefined)
        return
      }
      resolve(responseUrl)
    })
  })
}

/** 跑完整 OIDC PKCE 流程并把令牌落盘。返回可判别结果供 popup 展示。 */
async function startOidcLogin() {
  const extensionId = browser.runtime.id
  const redirectUri = buildExtensionRedirectUri(extensionId)
  const authBaseUrl = settings.restBaseUrl || DEFAULT_REST_BASE_URL

  const result = await fetchOidcTokens({
    authBaseUrl,
    redirectUri,
    launchWebAuthFlow: (url, interactive) => launchWebAuthFlow(url, interactive),
  })

  if (result.ok) {
    const tokens: OidcTokenSet = {
      accessToken: result.accessToken,
      refreshToken: result.refreshToken,
      expiresAt: result.expiresAt,
    }
    setActiveOidcTokens(tokens)
    await saveOidcTokens(tokens)
    await saveOidcLoginState('logged_in')
  }
  return result
}

/** 登出：清空内存持热 + 持久化令牌 + 登录态。 */
async function logoutOidc() {
  setActiveOidcTokens(null)
  await saveOidcTokens(null)
  await saveOidcLoginState('logged_out')
  return { ok: true as const }
}

/** 读取 OIDC 登录态：结合内存持热与持久化，判断"是否仍有效登录"。 */
async function getOidcStatus() {
  const tokens = getActiveOidcTokens() ?? await loadOidcTokens()
  const now = Date.now()
  const loggedIn = tokens != null && tokens.expiresAt - 30_000 > now
  return {
    loggedIn,
    accessTokenPresent: !!tokens?.accessToken,
    expiresAt: tokens?.expiresAt ?? null,
  }
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
    case 'content:selection': {
      handleSelection(state, settings, message.payload)
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

  // OIDC 登录：跑 PKCE 流程并把令牌落盘（popup 触发）。返回可判别结果。
  defineInvokeHandler(context, popupStartOidcLogin, async () => {
    return await startOidcLogin()
  })

  // 登出：清除 OIDC 令牌与登录态。
  defineInvokeHandler(context, popupLogoutOidc, async () => {
    return await logoutOidc()
  })

  // 读取登录态（popup 挂载时调用）。
  defineInvokeHandler(context, popupGetOidcStatus, async () => {
    return await getOidcStatus()
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
    // 报告 P2-2：把侧边栏的观点评价（`opinion_evaluation`）真正 POST 到 REST 通道
    // ——此前该 topic 已在服务端注册、侧边栏也生产该事件、却从不 POST。火不待（fire-and-forget）：
    // REST 失败不得影响侧边栏响应（与 reportV9Observation 同口径的"零接线也能跑"降级语义）。
    if (opinion) {
      const sessionId = await getOrCreateInstallId()
      void reportV9Constraint(state, opinion, settings, sessionId).catch(() => {})
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
