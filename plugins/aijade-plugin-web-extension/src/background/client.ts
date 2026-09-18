import type { ContextUpdate } from '@proj-aijade/server-sdk'

import type { LlmCall } from '../shared/llm'
import type { ExtensionSettings, ExtensionStatus, PageContextPayload, SelectionPayload, SubtitlePayload, VideoContextPayload } from '../shared/types'
import type { OpinionEvaluationPayload, V10EvidenceEvent } from '../shared/v10-evidence'
import type { V9EventEnvelope } from '../shared/v9-rest'

import { Client, ContextUpdateStrategy } from '@proj-aijade/server-sdk'
import { nanoid } from 'nanoid'

import packageJSON from '../../package.json'

import { DEFAULT_REST_BASE_URL } from '../shared/constants'
import { resolveApiToken, resolveApiTokenFresh } from '../shared/credentials'
import { summarize } from '../shared/llm'
import { reducePageToEvidence, reduceSubtitleToEvidence, summarizePageToEvidence, summarizeSubtitleToEvidence } from '../shared/v10-evidence'
import { buildV9ConstraintEnvelope, buildV9EventEnvelope, postV9Event } from '../shared/v9-rest'
import { advanceTick, getOrCreateInstallId, saveOidcTokens } from './storage'

const PLUGIN_NAME = 'proj-aijade:plugin-web-extension'

/**
 * v10 事件的「会话身份」：扩展级持久化安装 id（见 storage.getOrCreateInstallId）。
 *
 * 真实不变量：本 `sessionId` **同时**用作两处——
 *   1. `advanceTick(sessionId)` 的 tick 会话键（v10 事件确定性排序，跨 SW 重启不回退）；
 *   2. 观察 payload 的 `session_id`（由 v10-evidence 归约器注入，值等于本 id）。
 * 二者为同一身份，故服务端可把「哪个 tick 序列」「哪条观察」归并到同一个扩展安装实例，
 * 这正是 A 路（纯视频输入）"观察归属哪个会话"的落点——不再是硬编码的 'web-extension' 占位串。
 */

export interface ClientState {
  client: Client | null
  connected: boolean
  lastError?: string
  lastPage?: PageContextPayload
  lastVideo?: VideoContextPayload
  lastSubtitle?: SubtitlePayload
  lastVisionFrameAt?: number
  /** 用户选区（报告 P2-4），用于侧栏/状态面板展示与下游消费。 */
  lastSelection?: SelectionPayload
  /**
   * v10 REST 上报通道的可观测遥测（报告 P3-6）。此前上报失败被静默 `console.warn`，
   * "上报成功"无法从任何状态证明；现在累计成功/失败计数与最近失败原因，暴露给状态面板。
   */
  restReport: {
    successes: number
    failures: number
    consecutiveFailures: number
    lastSuccessAt?: number
    lastFailureAt?: number
    lastFailureReason?: string
  }
}

export function createClientState(): ClientState {
  return {
    client: null,
    connected: false,
    restReport: { successes: 0, failures: 0, consecutiveFailures: 0 },
  }
}

/** 退避重试常量（报告 P3-6）：瞬时失败最多重试 2 次（共 3 次尝试），指数退避。 */
const REST_MAX_ATTEMPTS = 3
const REST_BACKOFF_BASE_MS = 400

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * 仅瞬时失败可重试：网络层错误（`status === 0`）与 5xx。
 * 4xx（含 401 鉴权/400 校验）是终态，重试无意义。
 */
function isRetryableV9Post(result: { ok: boolean, status: number }): boolean {
  if (result.ok)
    return false
  if (result.status === 0)
    return true
  if (result.status >= 500 && result.status < 600)
    return true
  return false
}

/**
 * 从设置构建本次上报使用的 LLM 调用（绑定 baseUrl / model / token）。
 * `summarize` 自身即为一个 `LlmCall`，故直接透传。模型默认 `'auto'`，
 * 余额不足时服务端计费闸返回 402（预期失败），由 v10-evidence 的"失败不落库"回退。
 */
function makeLlm(settings: ExtensionSettings): LlmCall {
  const baseUrl = settings.llmBaseUrl || DEFAULT_REST_BASE_URL
  const model = settings.llmModel || 'auto'
  // 与 v9 REST 通道共用同一凭据真源（见 credentials.ts）。绝不引用 WS 的 `token` 字段。
  const token = resolveApiToken(settings)
  return (text, opts) => summarize(text, { kind: opts.kind, baseUrl, model, token })
}

function createIdentity() {
  return {
    kind: 'plugin' as const,
    plugin: {
      id: PLUGIN_NAME,
      version: typeof packageJSON.version === 'string' ? packageJSON.version : undefined,
    },
    id: nanoid(),
    labels: {
      runtime: 'web-extension',
    },
  }
}

export function toStatus(state: ClientState, settings: ExtensionSettings): ExtensionStatus {
  return {
    connected: state.connected,
    lastError: state.lastError,
    settings,
    lastPage: state.lastPage,
    lastVideo: state.lastVideo,
    lastSubtitle: state.lastSubtitle,
    lastSelection: state.lastSelection,
    lastVisionFrameAt: state.lastVisionFrameAt,
    restReport: { ...state.restReport },
  }
}

export async function ensureClient(state: ClientState, settings: ExtensionSettings) {
  if (!settings.enabled) {
    disconnectClient(state)
    return
  }

  if (state.client) {
    return
  }

  const client = new Client({
    name: PLUGIN_NAME,
    url: settings.wsUrl,
    token: settings.token || undefined,
    identity: createIdentity(),
    possibleEvents: ['context:update', 'spark:notify', 'spark:emit'],
    autoConnect: false,
    autoReconnect: true,
    onError: (error) => {
      state.connected = false
      state.lastError = error instanceof Error ? error.message : String(error)
    },
    onClose: () => {
      state.connected = false
    },
  })

  state.client = client

  try {
    await client.connect()
    state.connected = true
    state.lastError = undefined
  }
  catch (error) {
    state.connected = false
    state.lastError = error instanceof Error ? error.message : String(error)
  }
}

export function disconnectClient(state: ClientState) {
  if (!state.client)
    return

  state.client.close()
  state.client = null
  state.connected = false
}

function sendContextUpdate(state: ClientState, update: Omit<ContextUpdate, 'id' | 'contextId'> & Partial<Pick<ContextUpdate, 'id' | 'contextId'>>) {
  if (!state.client || !state.connected)
    return

  const id = update.id ?? nanoid()
  state.client.send({
    type: 'context:update',
    data: {
      id,
      contextId: update.contextId ?? id,
      ...update,
    },
  })
}

function sendSparkNotify(state: ClientState, data: { headline: string, note?: string, payload?: Record<string, unknown> }) {
  if (!state.client || !state.connected)
    return

  state.client.send({
    type: 'spark:notify',
    data: {
      id: nanoid(),
      eventId: nanoid(),
      kind: 'ping',
      urgency: 'soon',
      headline: data.headline,
      note: data.note,
      payload: data.payload,
      destinations: ['character'],
    },
  })
}

/**
 * 走 v10 REST 事件上报通道上报一次观察事件（独立于 WS 路径）。
 *
 * - 复用调用方已算好的同一个 `v10Evidence`（不重新归约，hash 才一致）。
 * - REST 失败**不得**影响 WS 路径：各自独立 try/catch；本函数内部所有异常都被吞掉并打日志。
 * - `restBaseUrl` 未配置时直接跳过并记录 debug 日志（"零接线也能跑"降级语义）。
 * - tick 由 `advanceTick` 注入并持久化（每会话单调递增，跨 SW 重启不回退）。
 */
/**
 * 解析 REST 上报用的凭据（与 LLM 通道共用同一真源，见 credentials.ts）。
 * 优先异步解析：OIDC access token 过期时主动 refresh；refresh 失败则降级为同步解析
 * （bearer 或新鲜 OIDC）。凭据只解析一次，重试只针对传输层。
 */
async function resolveRestToken(settings: ExtensionSettings): Promise<string | undefined> {
  const authBaseUrl = settings.restBaseUrl || DEFAULT_REST_BASE_URL
  const fresh = await resolveApiTokenFresh(settings, {
    authBaseUrl,
    onRefreshed: async (t) => { await saveOidcTokens(t) },
  })
  return fresh.ok ? fresh.token : resolveApiToken(settings)
}

/**
 * 通用 REST 上报 + 退避重试 + 可见遥测（报告 P3-6）。
 * 仅对瞬时失败（网络 / 5xx）重试；4xx / 鉴权为终态。
 * 成功/失败计数与最近失败原因写入 `state.restReport`，暴露给状态面板，使"上报成功"可证明。
 */
async function postV9EnvelopeWithRetry(
  state: ClientState,
  baseUrl: string,
  envelope: V9EventEnvelope,
  token: string | undefined,
): Promise<void> {
  let lastResult: { ok: boolean, status: number, error?: string, reason?: string } | null = null
  for (let attempt = 1; attempt <= REST_MAX_ATTEMPTS; attempt++) {
    try {
      const result = await postV9Event(baseUrl, envelope, { token })
      lastResult = result
      if (result.ok) {
        state.restReport.successes += 1
        state.restReport.consecutiveFailures = 0
        state.restReport.lastSuccessAt = Date.now()
        console.debug(`[v9-rest] 已上报 ${envelope.topic} tick=${envelope.tick} deduped=${result.deduped}（累计成功 ${state.restReport.successes}）`)
        return
      }
      // 终态失败（4xx / 鉴权）：不重试，立即退出重试循环。
      if (!isRetryableV9Post(result)) {
        console.warn(`[v9-rest] REST 上报终态失败（status ${result.status}, reason ${result.reason ?? '-'}）: ${result.error ?? ''}`)
        break
      }
      console.warn(`[v9-rest] REST 上报瞬时失败 (attempt ${attempt}/${REST_MAX_ATTEMPTS}, status ${result.status}): ${result.error ?? ''}${attempt < REST_MAX_ATTEMPTS ? ' — 退避重试' : ''}`)
    }
    catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      lastResult = { ok: false, status: 0, error: message }
      console.warn(`[v9-rest] REST 上报异常 (attempt ${attempt}/${REST_MAX_ATTEMPTS}): ${message}${attempt < REST_MAX_ATTEMPTS ? ' — 退避重试' : ''}`)
    }
    if (attempt < REST_MAX_ATTEMPTS)
      await sleep(REST_BACKOFF_BASE_MS * 2 ** (attempt - 1))
  }

  // 全部尝试失败：累计可见失败计数 + 暴露最近一次原因，使"上报成功"可证明。
  state.restReport.failures += 1
  state.restReport.consecutiveFailures += 1
  state.restReport.lastFailureAt = Date.now()
  state.restReport.lastFailureReason = lastResult?.reason ?? lastResult?.error ?? 'unknown'
  console.warn(`[v9-rest] REST 上报最终失败（累计 ${state.restReport.failures} 次，连续 ${state.restReport.consecutiveFailures} 次），topic=${envelope.topic}`)
}

/**
 * 走 v10 REST 事件上报通道上报一次观察事件（独立于 WS 路径）。
 *
 * - 复用调用方已算好的同一个 `v10Evidence`（不重新归约，hash 才一致）。
 * - REST 失败**不得**影响 WS 路径：各自独立 try/catch。
 * - `restBaseUrl` 未配置时直接跳过并记录 debug 日志（"零接线也能跑"降级语义）。
 * - tick 由 `advanceTick` 注入并持久化（每会话单调递增，跨 SW 重启不回退）。
 * - **报告 P3-6**：失败不再被静默吞掉——累计可见的成功/失败计数与最近失败原因
 *   （暴露给状态面板），并对瞬时失败（网络 / 5xx）做指数退避重试；4xx/鉴权为终态，不重试。
 */
async function reportV9Observation(state: ClientState, evidence: V10EvidenceEvent | null, settings: ExtensionSettings, sessionId: string) {
  if (!evidence)
    return

  if (!settings.restBaseUrl) {
    console.debug('[v9-rest] restBaseUrl 未配置，跳过 REST 上报')
    return
  }

  // 与 payload 里的 `session_id` 同一身份（见文件顶部不变量注释）。advanceTick 语义不变：先读 → +1 → 写回。
  const tick = await advanceTick(sessionId)
  const envelope = buildV9EventEnvelope({ evidence, tick })
  const token = await resolveRestToken(settings)
  await postV9EnvelopeWithRetry(state, settings.restBaseUrl, envelope, token)
}

/**
 * 报告 C 路约束性事件（报告 P2-2）：把侧边栏的观点评价（`opinion_evaluation`）真正 POST 出去。
 * 此前该 topic 已在服务端注册、侧边栏也生产该事件，但**从不 POST**——本函数让它真正发出去。
 * 复用与观察通道同一套凭据解析、退避重试与遥测。
 */
export async function reportV9Constraint(state: ClientState, opinion: OpinionEvaluationPayload, settings: ExtensionSettings, sessionId: string) {
  if (!settings.restBaseUrl) {
    console.debug('[v9-rest] restBaseUrl 未配置，跳过约束事件上报')
    return
  }

  const tick = await advanceTick(sessionId)
  const envelope = buildV9ConstraintEnvelope({
    event: { topic: opinion.topic, payload: opinion.payload, inputHash: opinion.payload.evaluation_target },
    tick,
  })
  const token = await resolveRestToken(settings)
  await postV9EnvelopeWithRetry(state, settings.restBaseUrl, envelope, token)
}

export async function handlePageContext(state: ClientState, settings: ExtensionSettings, payload: PageContextPayload) {
  state.lastPage = payload

  if (!settings.enabled || !settings.sendPageContext)
    return

  // 归约一次，WS 与 REST 复用同一结果（保证 hash 一致）。
  // 优先尝试 LLM 摘要路径；失败（网络/鉴权/计费/解析）则回退确定性 reduce* 兜底。
  const sessionId = await getOrCreateInstallId()
  let v10Evidence = reducePageToEvidence(payload, { sessionId })
  try {
    const llmEvidence = await summarizePageToEvidence(payload, makeLlm(settings), { sessionId })
    if (llmEvidence) {
      v10Evidence = llmEvidence
      console.debug('[v10-evidence] 使用 LLM 摘要路径（page）')
    }
    else {
      console.debug('[v10-evidence] LLM 摘要未产出，回退确定性归约（page）')
    }
  }
  catch (err) {
    // LLM 路径异常不得影响既有 WS 上报：记日志，继续用确定性兜底。
    console.warn(`[v10-evidence] LLM 摘要路径异常，回退确定性归约（page）: ${err instanceof Error ? err.message : String(err)}`)
  }

  sendContextUpdate(state, {
    strategy: ContextUpdateStrategy.ReplaceSelf,
    lane: 'web:page',
    text: `User is browsing: ${payload.title} (${payload.url}).`,
    metadata: {
      source: 'web-extension',
      v10Evidence,
      site: payload.site,
      url: payload.url,
      title: payload.title,
      description: payload.description,
      language: payload.language,
    },
  })
  // REST 通道：独立于 WS，各自 try/catch。
  await reportV9Observation(state, v10Evidence, settings, sessionId)
}

export function handleVideoContext(
  state: ClientState,
  settings: ExtensionSettings,
  payload: VideoContextPayload,
  options?: { notify?: boolean },
) {
  state.lastVideo = payload

  // 注：video（观看中）这条 sendContextUpdate 路径**没有**对应的 v10 观察 evidence
  // 形状——服务端 `AIJADE_TOPICS` 里 `aijade.video.*` 只定义了
  // `observation.webpage_text` 与 `observation.video_transcript` 两个 topic，
  // 分别由 page / subtitle 归约产出。故本路径不走 REST 上报，避免捏造无契约的 payload。

  if (!settings.enabled || !settings.sendVideoContext)
    return

  const headline = payload.title
    ? `User is watching: ${payload.title}`
    : 'User is watching a video'

  if (settings.sendSparkNotify && options?.notify !== false && payload.title) {
    sendSparkNotify(state, {
      headline,
      note: payload.channel ? `Channel: ${payload.channel}` : undefined,
      payload: {
        site: payload.site,
        url: payload.url,
        title: payload.title,
        channel: payload.channel,
        videoId: payload.videoId,
        durationSec: payload.durationSec,
        currentTimeSec: payload.currentTimeSec,
        isPlaying: payload.isPlaying,
        isLive: payload.isLive,
      },
    })
  }

  sendContextUpdate(state, {
    strategy: ContextUpdateStrategy.ReplaceSelf,
    lane: 'web:video',
    text: [
      headline,
      payload.channel ? `Channel: ${payload.channel}.` : undefined,
      payload.currentTimeSec != null
        ? `Progress: ${Math.floor(payload.currentTimeSec)}s${payload.durationSec ? ` / ${Math.floor(payload.durationSec)}s` : ''}.`
        : undefined,
      payload.url ? `URL: ${payload.url}.` : undefined,
    ].filter(Boolean).join(' '),
    metadata: {
      source: 'web-extension',
      site: payload.site,
      url: payload.url,
      title: payload.title,
      channel: payload.channel,
      videoId: payload.videoId,
      durationSec: payload.durationSec,
      currentTimeSec: payload.currentTimeSec,
      isPlaying: payload.isPlaying,
      playbackRate: payload.playbackRate,
      isLive: payload.isLive,
      playerSize: payload.playerSize,
    },
  })
}

export function handleSelection(state: ClientState, settings: ExtensionSettings, payload: SelectionPayload) {
  state.lastSelection = payload

  if (!settings.enabled || !settings.sendPageContext)
    return

  sendContextUpdate(state, {
    strategy: ContextUpdateStrategy.ReplaceSelf,
    lane: 'web:selection',
    text: `User selected: ${payload.selected_text.slice(0, 200)}`,
    metadata: {
      source: 'web-extension',
      site: payload.site,
      url: payload.url,
      selectedText: payload.selected_text,
      startOffset: payload.start_offset,
      endOffset: payload.end_offset,
    },
  })
}

export async function handleSubtitle(state: ClientState, settings: ExtensionSettings, payload: SubtitlePayload) {
  state.lastSubtitle = payload

  if (!settings.enabled || !settings.sendSubtitles)
    return

  // 归约一次，WS 与 REST 复用同一结果（保证 hash 一致）。
  // 优先尝试 LLM 摘要路径；失败则回退确定性 reduce* 兜底（与 page 路径一致）。
  const sessionId = await getOrCreateInstallId()
  let v10Evidence = reduceSubtitleToEvidence(payload, { sessionId })
  try {
    const llmEvidence = await summarizeSubtitleToEvidence(payload, makeLlm(settings), { sessionId })
    if (llmEvidence) {
      v10Evidence = llmEvidence
      console.debug('[v10-evidence] 使用 LLM 摘要路径（subtitle）')
    }
    else {
      console.debug('[v10-evidence] LLM 摘要未产出，回退确定性归约（subtitle）')
    }
  }
  catch (err) {
    console.warn(`[v10-evidence] LLM 摘要路径异常，回退确定性归约（subtitle）: ${err instanceof Error ? err.message : String(err)}`)
  }

  sendContextUpdate(state, {
    strategy: ContextUpdateStrategy.ReplaceSelf,
    lane: 'web:subtitle',
    text: `Subtitle: ${payload.text}`,
    metadata: {
      source: 'web-extension',
      v10Evidence,
      site: payload.site,
      url: payload.url,
      title: payload.title,
      videoId: payload.videoId,
      language: payload.language,
      startMs: payload.startMs,
      endMs: payload.endMs,
      isAuto: payload.isAuto,
    },
  })
  // REST 通道：独立于 WS，各自 try/catch。
  await reportV9Observation(state, v10Evidence, settings, sessionId)
}
