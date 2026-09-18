import type { LlmCall, LlmOutput } from './llm'
import type { PageContextPayload, SubtitlePayload } from './types'

export interface V10EvidenceEvent {
  topic: 'aijade.video.observation.webpage_text' | 'aijade.video.observation.video_transcript'
  payload: Record<string, unknown>
  inputText: string
}

/** 观点评价的约束性证据 payload（C 路，映射到 `aijade.learning.*` 前缀）。 */
export interface OpinionEvaluationPayload {
  topic: 'aijade.learning.constraint.opinion_evaluation'
  payload: {
    /** 指向被评价网页/字幕的规范 content_hash / transcript_hash（非空）。 */
    evaluation_target: string
    claims: { claim_text: string, confidence: number }[]
    uncertainty_notes: string
  }
}

function normalize(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

/**
 * 归约器保持"纯函数、不读全局状态"：会话身份由调用方显式注入，而非在归约器内部 await storage。
 * `sessionId` 来自 storage.getOrCreateInstallId()（扩展级持久化安装 id），写入 payload 的
 * `session_id`——与 client.ts 中 `advanceTick(sessionId)` 的 tick 会话键为**同一身份**（真实不变量）。
 * 契约要求 `session_id` 非空；调用方（client.ts）始终传入，本处仅在提供时写入。
 */
export interface ReduceOptions {
  sessionId?: string
}

export function stableHash(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, '0')}`
}

export function reducePageToEvidence(page: PageContextPayload, opts?: ReduceOptions): V10EvidenceEvent | null {
  // 报告 P2-3：优先用真实正文（bodyText + spans）；缺失时回退到 title + description 的确定性口径。
  const bodyText = typeof page.bodyText === 'string' ? page.bodyText : ''
  const hasBody = bodyText.trim().length > 0
  const text = hasBody ? normalize(bodyText) : normalize([page.title, page.description].filter(Boolean).join('. '))
  if (!text || !page.url)
    return null

  const spans
    = hasBody && Array.isArray(page.spans) && page.spans.length > 0
      ? page.spans
      : [{ start_offset: 0, end_offset: text.length, label: hasBody ? 'body' : 'page-summary' }]

  return {
    topic: 'aijade.video.observation.webpage_text',
    inputText: text,
    payload: {
      source_url: page.url,
      content_hash: stableHash(text),
      spans,
      observation_text: text,
      ...(opts?.sessionId ? { session_id: opts.sessionId } : {}),
    },
  }
}

export function reduceSubtitleToEvidence(subtitle: SubtitlePayload, opts?: ReduceOptions): V10EvidenceEvent | null {
  const text = normalize(subtitle.text)
  if (!text || !subtitle.videoId)
    return null

  const startMs = Math.max(0, subtitle.startMs ?? 0)
  const endMs = Math.max(startMs, subtitle.endMs ?? startMs)
  return {
    topic: 'aijade.video.observation.video_transcript',
    inputText: text,
    payload: {
      video_id: subtitle.videoId,
      transcript_hash: stableHash(text),
      time_spans: [{ start_ms: startMs, end_ms: endMs, text }],
      caption_text: text,
      ...(opts?.sessionId ? { session_id: opts.sessionId } : {}),
    },
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 以下为**新增的异步 LLM 路径**（v10 §15.2 / §15.4 / §15.6）。
// 既有的同步 `reduce*` 保持不变，作为无 LLM / 测试环境的**确定性兜底**。
// 所有 LLM 路径遵循"失败不落库"：返回 `null` ⇒ 不发事件，而非吞错后编造。
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 把 LLM 的摘要输出归约为可写入的 `observation_text`：
 * 取 `summary`（必要时拼上 `key_points`）。
 * 若 `summary` 为空 ⇒ 返回 `null`（视为未产出有效摘要）。
 */
function toObservationTextFromSummary(output: LlmOutput): string | null {
  const summary = typeof output.summary === 'string' ? output.summary.trim() : ''
  if (!summary)
    return null
  const keyPoints = Array.isArray(output.key_points)
    ? output.key_points
        .filter((k): k is string => typeof k === 'string' && k.trim().length > 0)
        .map(k => k.trim())
    : []
  return [summary, ...keyPoints].join(' ')
}

function toValidClaims(output: LlmOutput): { claim_text: string, confidence: number }[] {
  if (!Array.isArray(output.claims))
    return []
  return output.claims
    .filter((c): c is { claim_text: string, confidence: number } =>
      !!c
      && typeof c.claim_text === 'string'
      && c.claim_text.trim().length > 0
      && typeof c.confidence === 'number'
      && c.confidence >= 0
      && c.confidence <= 1)
    .map(c => ({ claim_text: c.claim_text.trim(), confidence: c.confidence }))
}

/**
 * LLM 网页摘要路径：调 LLM 得到 `{ summary, key_points, confidence }`，
 * 以摘要（拼 key_points）作为 `observation_text`。
 *
 * **关键口径**：`content_hash` 必须对被实际写入 `observation_text` 的那段文本计算，
 * 这样 `content_hash` 仍是该次**输入的真快照哈希**（摘要后文本），而非摘要前的原文哈希。
 *
 * 任何失败（LLM 抛错 / 返回不可解析 / summary 为空）⇒ 返回 `null`（不产出事件）。
 */
export async function summarizePageToEvidence(page: PageContextPayload, llm: LlmCall, opts?: ReduceOptions): Promise<V10EvidenceEvent | null> {
  // 报告 P2-3：优先用真实正文作为 LLM 摘要输入（让模型看到页面实际内容），缺失时回退 title + description。
  const rawText = (typeof page.bodyText === 'string' && page.bodyText.trim().length > 0)
    ? page.bodyText
    : [page.title, page.description].filter(Boolean).join('. ')
  const inputText = normalize(rawText)
  if (!inputText || !page.url)
    return null

  let output: LlmOutput | undefined
  try {
    output = await llm(inputText, { kind: 'page' })
  }
  catch (err) {
    // LLM 抛错不致命：记日志，交由调用方回退确定性兜底（不在此处编造归约）。
    console.warn(`[v10-evidence] LLM 摘要失败（page），回退确定性归约: ${err instanceof Error ? err.message : String(err)}`)
    return null
  }
  if (!output)
    return null

  const observationText = toObservationTextFromSummary(output)
  if (!observationText)
    return null

  // 对"实际写入"的 observation_text 计算真快照哈希（防漂移的核心）。
  const contentHash = stableHash(observationText)
  return {
    topic: 'aijade.video.observation.webpage_text',
    inputText,
    payload: {
      source_url: page.url,
      content_hash: contentHash,
      spans: [{ start_offset: 0, end_offset: observationText.length, label: 'llm-summary' }],
      observation_text: observationText,
      ...(opts?.sessionId ? { session_id: opts.sessionId } : {}),
    },
  }
}

/**
 * LLM 字幕摘要路径：与 `summarizePageToEvidence` 同理，产出
 * `aijade.video.observation.video_transcript` 证据。
 * `transcript_hash` 同样对实际写入的 `caption_text` 计算。
 */
export async function summarizeSubtitleToEvidence(subtitle: SubtitlePayload, llm: LlmCall, opts?: ReduceOptions): Promise<V10EvidenceEvent | null> {
  const inputText = normalize(subtitle.text)
  if (!inputText || !subtitle.videoId)
    return null

  let output: LlmOutput | undefined
  try {
    output = await llm(inputText, { kind: 'subtitle' })
  }
  catch (err) {
    console.warn(`[v10-evidence] LLM 摘要失败（subtitle），回退确定性归约: ${err instanceof Error ? err.message : String(err)}`)
    return null
  }
  if (!output)
    return null

  const observationText = toObservationTextFromSummary(output)
  if (!observationText)
    return null

  const transcriptHash = stableHash(observationText)
  const startMs = Math.max(0, subtitle.startMs ?? 0)
  const endMs = Math.max(startMs, subtitle.endMs ?? startMs)
  return {
    topic: 'aijade.video.observation.video_transcript',
    inputText,
    payload: {
      video_id: subtitle.videoId,
      transcript_hash: transcriptHash,
      time_spans: [{ start_ms: startMs, end_ms: endMs, text: observationText }],
      caption_text: observationText,
      ...(opts?.sessionId ? { session_id: opts.sessionId } : {}),
    },
  }
}

/**
 * LLM 观点评价路径：产出 `aijade.learning.constraint.opinion_evaluation` 的 payload（C 路约束性证据）。
 *
 * - `evaluation_target` 引用该页的规范 `content_hash`（确定性真源，非空）。
 * - `claims` 从 LLM 的 `{ claims: [{claim_text, confidence}] }` 取，仅保留 `claim_text` 非空且
 *   `confidence ∈ [0,1]` 的项。
 * - `uncertainty_notes` 必填非空。
 *
 * **失败不落库（v10 §15.6）**：
 * - LLM 抛错 / 返回不可解析 ⇒ 返回 `null`；
 * - `claims` 为空 ⇒ 返回 `null`（未形成任何评价陈述，不编造）；
 * - `uncertainty_notes` 为空 ⇒ 返回 `null`（缺失不确定性边界，不编造）。
 */
export async function evaluatePageOpinion(page: PageContextPayload, llm: LlmCall): Promise<OpinionEvaluationPayload | null> {
  // 报告 P2-3：优先用真实正文作为评价源（评价定位锚 evaluation_target 来自此文本）。
  const rawText = (typeof page.bodyText === 'string' && page.bodyText.trim().length > 0)
    ? page.bodyText
    : [page.title, page.description].filter(Boolean).join('. ')
  const sourceText = normalize(rawText)
  if (!sourceText)
    return null
  // 该页的规范 content_hash，作为评价的定位锚（evaluation_target）。
  const evaluationTarget = stableHash(sourceText)

  let output: LlmOutput | undefined
  try {
    output = await llm(sourceText, { kind: 'opinion' })
  }
  catch (err) {
    console.warn(`[v10-evidence] LLM 观点评价失败（page），不产出事件: ${err instanceof Error ? err.message : String(err)}`)
    return null
  }
  if (!output)
    return null

  const claims = toValidClaims(output)
  // 失败不落库：没有可落库的 claim，就不产出事件。
  if (claims.length === 0)
    return null

  const uncertaintyNotes = typeof output.uncertainty_notes === 'string' ? output.uncertainty_notes.trim() : ''
  // 失败不落库：缺不确定性边界，绝不填一个编造的值。
  if (!uncertaintyNotes)
    return null

  return {
    topic: 'aijade.learning.constraint.opinion_evaluation',
    payload: {
      evaluation_target: evaluationTarget,
      claims,
      uncertainty_notes: uncertaintyNotes,
    },
  }
}
