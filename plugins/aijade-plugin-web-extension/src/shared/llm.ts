/**
 * 浏览器安全的 LLM 客户端（零 node 依赖）。
 *
 * 对接服务端 `POST /api/v1/openai/chat/completions`（OpenAI Chat Completions 兼容）。
 * 详见 `apps/server/src/app.ts:377` 与 `apps/server/src/routes/openai/v1/operations/chat-completions/index.ts`。
 *
 * 关键契约（已核实，照此对接，勿臆测）：
 * - 请求体原样透传；`body.model` 缺省走服务端 `DEFAULT_CHAT_MODEL`，可用 `'auto'`；支持 `stream`。
 * - 响应在非流式时为上游原生 OpenAI 格式：`{ choices: [{ message: { content: string } }] }`。
 * - 鉴权：`authGuard` 需要 better-auth 会话（cookie，靠 `credentials:'include'`）或 Bearer token；
 *   未登录返回 **401**。这是**预期失败，不是 bug**。
 * - `configGuard` 的 `FLUX_PER_REQUEST` 默认 5 ⇒ 门默认通过；缺该键返回 **503**（预期失败）。
 * - 计费闸 `billing.authorizeChat`：余额不足会拒绝，可能返回 **402**（预期失败）。
 *
 * 设计原则：失败必须可判别 —— 不把失败吞成静默 `undefined`。调用方据此决定回退/不落库。
 */

import { DEFAULT_REST_BASE_URL } from './constants'

export type LlmKind = 'page' | 'subtitle' | 'opinion'

export interface LlmMessage {
  role: 'system' | 'user' | 'assistant'
  content: string
}

export interface ChatCompletionOptions {
  model?: string
  token?: string
  messages: LlmMessage[]
}

export type ChatErrorKind
  = | 'unauthorized' // 401：未登录（无会话 cookie / Bearer）
    | 'payment_required' // 402：计费闸拒绝（余额不足）
    | 'unavailable' // 429/5xx：限流或服务暂不可用（含 503 配置闸缺键）
    | 'malformed' // 其它 4xx / 响应无法解析
    | 'network' // fetch 抛错（网络层）

/**
 * 401 的细分原因——UI/日志据此告诉使用者下一步该做什么：
 * - `missing`：本次调用**根本没带**任何 token ⇒ 去设置里填写 Bearer Token；
 * - `rejected`：带了 token 但服务端仍 401 ⇒ token 无效 / 已过期 / 与服务器不匹配，
 *   需重新获取或检查设置中的 Bearer Token。
 * 两者下一步动作完全不同，必须可区分。
 */
export type UnauthorizedReason
  = | 'missing'
    | 'rejected'

export type ChatCompletionResult
  = | { ok: true, content: string }
    | { ok: false, status: number, kind: ChatErrorKind, message: string, reason?: UnauthorizedReason }

export interface LlmCallOptions {
  kind: LlmKind
  baseUrl?: string
  model?: string
  token?: string
}

/** v10-evidence 使用的 LLM 抽象：把一段文本 + 语义类型交给模型，返回解析后的 JSON 对象或 undefined。 */
export type LlmCall = (text: string, opts: LlmCallOptions) => Promise<LlmOutput | undefined>

/**
 * 模型可能产出的结构化输出。page/subtitle 走摘要形状，opinion 走评价形状；
 * 这里合并为一个可判别的对象（缺失字段由调用方按语义校验）。
 */
export interface LlmOutput {
  summary?: string
  key_points?: string[]
  confidence?: number
  claims?: { claim_text: string, confidence: number }[]
  uncertainty_notes?: string
}

function kindFromStatus(status: number): ChatErrorKind {
  if (status === 401)
    return 'unauthorized'
  if (status === 402)
    return 'payment_required'
  if (status === 429)
    return 'unavailable'
  if (status >= 500 && status < 600)
    return 'unavailable'
  return 'malformed'
}

function extractContent(data: unknown): string | undefined {
  if (!data || typeof data !== 'object')
    return undefined
  const choices = (data as { choices?: unknown }).choices
  if (!Array.isArray(choices) || choices.length === 0)
    return undefined
  const message = (choices[0] as { message?: unknown }).message
  if (!message || typeof message !== 'object')
    return undefined
  const content = (message as { content?: unknown }).content
  return typeof content === 'string' ? content : undefined
}

async function readErrorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json().catch(() => null)
    if (data && typeof data === 'object') {
      const candidate = (data as Record<string, unknown>).error
        ?? (data as Record<string, unknown>).message
      if (typeof candidate === 'string' && candidate.length > 0)
        return candidate
    }
  }
  catch {
    // 忽略解析失败，回退到状态行。
  }
  return `HTTP ${res.status}`
}

/**
 * 调用 OpenAI 兼容的 chat/completions 端点。
 * 永远返回可判别的结构化结果；网络层异常被归约为 `kind:'network'`，而非抛出。
 */
export async function chatCompletion(baseUrl: string, opts: ChatCompletionOptions): Promise<ChatCompletionResult> {
  const base = baseUrl.replace(/\/+$/, '')
  const url = `${base}/api/v1/openai/chat/completions`
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  if (opts.token)
    headers.authorization = `Bearer ${opts.token}`

  const body = {
    model: opts.model ?? 'auto',
    messages: opts.messages,
    stream: false,
  }

  try {
    const res = await fetch(url, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: JSON.stringify(body),
    })

    if (res.ok) {
      const data = await res.json().catch(() => null)
      const content = extractContent(data)
      if (typeof content === 'string' && content.length > 0)
        return { ok: true, content }
      // 401/503/402 之外，200 但缺 content 也算响应格式损坏。
      return { ok: false, status: res.status, kind: 'malformed', message: '响应缺少可解析的 message.content 字段' }
    }

    // 非 2xx：带出可识别的错误信息。
    // 注意：402（计费拒绝）/ 503（配置闸缺键）是**预期失败**，不是 bug；
    // 401（未登录）同样预期，调用方据此静默回退到确定性兜底。
    // 401 进一步区分「没配凭据」与「凭据被拒」，见 `UnauthorizedReason`。
    const message = await readErrorMessage(res)
    const kind = kindFromStatus(res.status)
    if (kind === 'unauthorized') {
      const reason: UnauthorizedReason = opts.token ? 'rejected' : 'missing'
      return { ok: false, status: res.status, kind, message, reason }
    }
    return { ok: false, status: res.status, kind, message }
  }
  catch (err) {
    const message = err instanceof Error ? err.message : String(err)
    return { ok: false, status: 0, kind: 'network', message }
  }
}

/**
 * 把 LLM 输出里的 JSON 对象稳健解析出来：
 * - 允许被 ```json 围栏包裹；
 * - 允许前后有解释性文字；
 * - 允许对象嵌套在文字中（取首个 `{...}` 到最后一个 `}`）。
 * 解析失败返回 `undefined`，**绝不**编造。
 */
export function extractJsonObject(text: string): unknown | undefined {
  if (typeof text !== 'string' || text.length === 0)
    return undefined

  // 1. 直接就是 JSON。
  try {
    return JSON.parse(text)
  }
  catch {
    // 继续尝试更宽松的提取。
  }

  // 2. ```json ... ``` 或 ``` ... ``` 围栏。
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fence) {
    try {
      return JSON.parse(fence[1].trim())
    }
    catch {
      // 继续。
    }
  }

  // 3. 取首个 `{` 到最后一个 `}` 的子串（容忍前后解释文字）。
  const start = text.indexOf('{')
  const end = text.lastIndexOf('}')
  if (start !== -1 && end !== -1 && end > start) {
    try {
      return JSON.parse(text.slice(start, end + 1))
    }
    catch {
      // 放弃。
    }
  }

  return undefined
}

function buildPrompt(text: string, kind: LlmKind): string {
  const trimmed = text.slice(0, 12000)
  if (kind === 'opinion') {
    return [
      '你是一个严谨的网页内容评价助手。请基于下面的网页内容，给出你的观点与评价。',
      '要求：',
      '1. 只输出一个 JSON 对象，不要输出任何 JSON 之外的内容（不要加解释、不要加 markdown 围栏）。',
      '2. JSON 形状：{"claims":[{"claim_text":string,"confidence":number}],"uncertainty_notes":string}',
      '   - claims：对内容的评价陈述列表，非空；每项的 confidence 为 0~1 的可信度。',
      '   - uncertainty_notes：非空字符串，明确你判断中的不确定性边界与信息缺口。',
      '3. 不得编造原文不存在的事实；如信息不足，就在 uncertainty_notes 中说明。',
      '',
      '网页内容：',
      trimmed,
    ].join('\n')
  }

  const role = kind === 'subtitle' ? '视频字幕' : '网页'
  return [
    `你是一个${role}摘要助手。请基于下面的${role}内容，生成结构化摘要。`,
    '要求：',
    '1. 只输出一个 JSON 对象，不要输出任何 JSON 之外的内容（不要加解释、不要加 markdown 围栏）。',
    '2. JSON 形状：{"summary":string,"key_points":string[],"confidence":number}',
    '   - summary：对内容的简洁摘要。',
    '   - key_points：要点列表（字符串数组）。',
    '   - confidence：你对摘要准确性的自信程度，0~1 之间的数字。',
    '3. 不得编造原文不存在的信息。',
    '',
    `${role}内容：`,
    trimmed,
  ].join('\n')
}

/**
 * 默认 `LlmCall` 实现：提示词要求模型**只输出 JSON**，
 * 调用 `chatCompletion` 后由 `extractJsonObject` 稳健解析。
 * 任何失败（网络 / 鉴权 / 计费 / 响应损坏 / 解析失败）都返回 `undefined`，
 * 调用方可据此回退到确定性兜底、**不产出事件**（v10 §15.6 失败不落库）。
 */
export async function summarize(
  text: string,
  opts: { kind: LlmKind, baseUrl?: string, model?: string, token?: string },
): Promise<LlmOutput | undefined> {
  const baseUrl = opts.baseUrl ?? DEFAULT_REST_BASE_URL
  const result = await chatCompletion(baseUrl, {
    model: opts.model ?? 'auto',
    token: opts.token,
    messages: [{ role: 'user', content: buildPrompt(text, opts.kind) }],
  })

  if (!result.ok) {
    // 401 区分「没配凭据」与「凭据被拒」：两者下一步动作完全不同。
    if (result.kind === 'unauthorized') {
      console.warn(`[llm] 鉴权失败：${result.reason === 'rejected' ? '凭据无效或已过期（请检查设置中的 Bearer Token）' : '未配置凭据（请在设置中填写 Bearer Token）'}`)
    }
    else {
      // 402/503/429/5xx 等为预期失败，记日志但不抛出，交由上层决定回退或不落库。
      console.warn(`[llm] chatCompletion 失败 (kind=${result.kind} status=${result.status}): ${result.message}`)
    }
    return undefined
  }

  const parsed = extractJsonObject(result.content)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
    return undefined

  return parsed as LlmOutput
}
