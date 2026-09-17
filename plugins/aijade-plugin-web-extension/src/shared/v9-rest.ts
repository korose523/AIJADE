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
}

function uuid(): string {
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

    // 4xx/5xx：把可见的错误信息带出来，不静默吞。
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
