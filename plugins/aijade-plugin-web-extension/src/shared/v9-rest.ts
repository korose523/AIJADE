/**
 * v10 REST 事件上报通道（浏览器安全 / 零 node 依赖）。
 *
 * 专用通道打到服务端 `POST /api/v1/v9/events`（挂载于 `apps/server/src/app.ts`，
 * 实现 `apps/server/src/routes/v9/events.ts`）。信封严格通过
 * `v9EventEnvelopeSchema`（valibot `strictObject`）——任何未知字段一律 400 且不落库。
 *
 * ⚠️ 本文件**不得** import `@proj-aijade/memory-biomimetic`：扩展只负责"实写"信封，
 * 不持有研究内核的因果语义；输入快照 hash 直接复用 `v10-evidence.ts` 的归约结果。
 */

import type { V10EvidenceEvent } from './v10-evidence'

export interface V9EventEnvelope {
  event_id: string
  trace_id: string
  correlation_id: string
  timestamp: number
  producer: string
  origin_device: string
  privacy_level: 0 | 1 | 2 | 3
  evidence_refs: string[]
  causal_context_refs: string[]
  risk_score: number
  idempotency_key: string
  replay_mode: 'live' | 'replay'
  risk_level: 'low' | 'medium' | 'high'
  tick: number
  causality: { inputHash: string }
  topic: string
  payload: Record<string, unknown>
}

export interface BuildV9EnvelopeInput {
  evidence: V10EvidenceEvent
  /** 由调用方注入的每会话单调递增 tick（见 storage.ts 的 `advanceTick`）。 */
  tick: number
}

export interface PostV9EventOptions {
  /** better-auth Bearer token；不传则只靠 `credentials:'include'` 的会话 cookie。 */
  token?: string
  signal?: AbortSignal
  /** 注入自定义 fetch（测试用）；默认取全局 `fetch`。 */
  fetchImpl?: typeof fetch
}

export interface PostV9EventResult {
  status: number
  ok: boolean
  deduped?: boolean
  eventId?: string
  error?: string
  /**
   * 401 的细分原因——UI/日志据此告诉使用者下一步该做什么：
   * - `unauthorized_missing`：本次请求**根本没带**任何 token ⇒ 去设置里填写 Bearer Token；
   * - `unauthorized_rejected`：带了 token 但服务端仍 401 ⇒ token 无效 / 已过期 /
   *   与服务器不匹配，需重新获取或检查设置中的 Bearer Token。
   * 两者下一步动作完全不同，必须可区分。
   */
  reason?: 'unauthorized_missing' | 'unauthorized_rejected'
}

export function uuid(): string {
  const c = globalThis.crypto
  // `crypto.randomUUID` 需要安全上下文（https / localhost / 扩展 SW 均满足）。
  // 回退：纯浏览器可用的 v4 近似，仅用于 event_id/trace_id/correlation_id，
  // 这些字段只要求"全局不撞"，冲突概率可忽略；**不**依赖任何 node API。
  if (c && typeof c.randomUUID === 'function')
    return c.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    const v = ch === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

function inputHashOf(evidence: V10EvidenceEvent): string {
  // 真链接：直接复用归约结果里的输入快照 hash，不另造哈希。
  if (evidence.topic === 'aijade.video.observation.video_transcript')
    return typeof evidence.payload.transcript_hash === 'string' ? evidence.payload.transcript_hash : ''
  return typeof evidence.payload.content_hash === 'string' ? evidence.payload.content_hash : ''
}

export function buildV9EventEnvelope(input: BuildV9EnvelopeInput): V9EventEnvelope {
  const { evidence, tick } = input
  const traceId = uuid()
  const inputHash = inputHashOf(evidence)
  // 幂等键口径：`topic#输入快照hash#tick`。
  // 同一观察（topic+hash）在**同一 tick** 下必得同键 → 服务端据此去重（200=命中）。
  // tick 由调用方每会话单调递增注入，故不同 tick 视为"同一观察的不同序列项"，互不覆盖去重。
  const idempotencyKey = `${evidence.topic}#${inputHash}#${tick}`
  return {
    event_id: uuid(),
    trace_id: traceId,
    correlation_id: uuid(),
    timestamp: Date.now(),
    producer: 'aijade-web-extension',
    origin_device: 'browser',
    privacy_level: 1,
    evidence_refs: [],
    causal_context_refs: [traceId],
    risk_score: 0,
    idempotency_key: idempotencyKey,
    replay_mode: 'live',
    risk_level: 'low',
    tick,
    causality: { inputHash },
    topic: evidence.topic,
    payload: evidence.payload,
  }
}

/**
 * C 路约束性事件（如 `aijade.learning.constraint.opinion_evaluation`）的"可上报事件"形状。
 * 与 `V10EvidenceEvent` 的区别：它不带 `inputText`、payload 也不必含 `content_hash`——
 * 输入快照 hash 直接由 `evaluation_target`（被评价对象的规范 hash）提供。
 */
export interface V9ConstraintEvent {
  topic: string
  payload: Record<string, unknown>
  /** 输入快照 hash（causality.inputHash）。缺省从 payload 的 content_hash / transcript_hash / evaluation_target 取。 */
  inputHash?: string
}

function inputHashOfConstraint(event: V9ConstraintEvent): string {
  if (typeof event.inputHash === 'string' && event.inputHash.length > 0)
    return event.inputHash
  const candidate = (event.payload as Record<string, unknown> | undefined)?.content_hash
    ?? (event.payload as Record<string, unknown> | undefined)?.transcript_hash
    ?? (event.payload as Record<string, unknown> | undefined)?.evaluation_target
  return typeof candidate === 'string' ? candidate : ''
}

/**
 * 与 `buildV9EventEnvelope` 同构，但面向 C 路约束性事件（报告 P2-2）。
 * 输入快照 hash 优先用 `event.inputHash`，否则回退到 payload 中的定位锚。
 */
export function buildV9ConstraintEnvelope(input: { event: V9ConstraintEvent, tick: number }): V9EventEnvelope {
  const { event, tick } = input
  const traceId = uuid()
  const inputHash = inputHashOfConstraint(event)
  const idempotencyKey = `${event.topic}#${inputHash}#${tick}`
  return {
    event_id: uuid(),
    trace_id: traceId,
    correlation_id: uuid(),
    timestamp: Date.now(),
    producer: 'aijade-web-extension',
    origin_device: 'browser',
    privacy_level: 1,
    evidence_refs: [],
    causal_context_refs: [traceId],
    risk_score: 0,
    idempotency_key: idempotencyKey,
    replay_mode: 'live',
    risk_level: 'low',
    tick,
    causality: { inputHash },
    topic: event.topic,
    payload: event.payload,
  }
}

export async function postV9Event(
  baseUrl: string,
  envelope: V9EventEnvelope,
  opts: PostV9EventOptions = {},
): Promise<PostV9EventResult> {
  const fetchImpl = opts.fetchImpl ?? globalThis.fetch
  const base = baseUrl.replace(/\/+$/, '')
  const url = `${base}/api/v1/v9/events`
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  // REST 端点要 better-auth 会话（cookie，靠 `credentials:'include'`）或 Bearer token。
  // 两者都没有 → 服务端 `authGuard` 返回 401（预期失败，不是 bug）。
  if (opts.token)
    headers.authorization = `Bearer ${opts.token}`

  try {
    const res = await fetchImpl(url, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: JSON.stringify(envelope),
      signal: opts.signal,
    })

    const data = (await res.json().catch(() => null)) as Record<string, unknown> | null

    if (res.status === 201)
      return { status: 201, ok: true, deduped: false, eventId: typeof data?.eventId === 'string' ? data.eventId : undefined }

    if (res.status === 200)
      return { status: 200, ok: true, deduped: true, eventId: typeof data?.eventId === 'string' ? data.eventId : undefined }

    // 401 鉴权失败：区分「没配凭据」与「凭据被拒」，使用者下一步动作不同。
    if (res.status === 401) {
      const reason = opts.token ? 'unauthorized_rejected' : 'unauthorized_missing'
      const hint = opts.token
        ? '凭据无效或已过期（请检查设置中的 Bearer Token）'
        : '未配置凭据（请在设置中填写 Bearer Token）'
      const error = extractError(data, res.status)
      console.warn(`[v9-rest] POST ${url} → 401 (${hint}): ${error}`)
      return { status: 401, ok: false, reason, error }
    }

    // 其它 4xx/5xx：把可见的错误信息带出来，不静默吞。
    const error = extractError(data, res.status)
    console.warn(`[v9-rest] POST ${url} → ${res.status}: ${error}`)
    return { status: res.status, ok: false, error }
  }
  catch (err) {
    // 网络失败：变成可见返回值 + 日志（与 client.ts 的 fire-and-forget 风格一致但可观测）。
    const message = err instanceof Error ? err.message : String(err)
    console.warn(`[v9-rest] POST ${url} network failure: ${message}`)
    return { status: 0, ok: false, error: message }
  }
}

function extractError(data: Record<string, unknown> | null, status: number): string {
  if (data) {
    const candidate = data.error ?? data.message ?? data.details
    if (typeof candidate === 'string' && candidate.length > 0)
      return candidate
    if (Array.isArray(data.issues) && data.issues.length > 0)
      return JSON.stringify(data.issues)
  }
  return `HTTP ${status}`
}

/**
 * 上报 C 路约束性事件（报告 P2-2）：构建信封后复用 `postV9Event` 的同一传输通道。
 * 此前 `opinion_evaluation` topic 已在服务端注册、侧边栏也生产该事件，但**从不 POST**——
 * 本函数把它真正发出去。tick 由调用方注入（与观察通道同一会话身份）。
 */
export async function postV10ConstraintEvent(
  baseUrl: string,
  event: V9ConstraintEvent,
  tick: number,
  opts: PostV9EventOptions = {},
): Promise<PostV9EventResult> {
  const envelope = buildV9ConstraintEnvelope({ event, tick })
  return postV9Event(baseUrl, envelope, opts)
}
