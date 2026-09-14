import type { ChatCompletion, TokenUsage } from './types'

interface OpenAIChatMessage {
  role?: string
  content?: string | null
}

interface OpenAIChoice {
  index?: number
  message?: OpenAIChatMessage
  finish_reason?: string | null
}

interface OpenAIUsage {
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
}

interface OpenAIChatResponse {
  id?: string
  model?: string
  choices?: OpenAIChoice[]
  usage?: OpenAIUsage
}

/** Normalize the provider usage block into AIJADE's {@link TokenUsage}. */
function normalizeUsage(u: OpenAIUsage | undefined): TokenUsage | null {
  if (!u)
    return null
  return {
    promptTokens: u.prompt_tokens ?? 0,
    completionTokens: u.completion_tokens ?? 0,
    totalTokens: u.total_tokens ?? 0,
  }
}

/** Parse an OpenAI-shaped chat-completions payload into a {@link ChatCompletion}. */
export function parseChatCompletion(raw: unknown, fallbackModel: string): ChatCompletion {
  const data = raw as OpenAIChatResponse
  const choice = data?.choices?.[0]
  const message = choice?.message
  const text = message?.content ?? ''
  return {
    id: data?.id ?? '',
    model: data?.model ?? fallbackModel,
    text,
    finishReason: choice?.finish_reason ?? null,
    usage: normalizeUsage(data?.usage),
    raw,
  }
}

/**
 * Best-effort extraction of a JSON value from model output. Handles the common
 * cases where the model wraps JSON in a ```json fence or emits prose around it.
 */
export function parseJsonContent(text: string): unknown {
  const trimmed = text.trim()
  if (!trimmed)
    throw new Error('Model returned empty content; cannot parse JSON.')

  // Strip a ```json ... ``` or ``` ... ``` fence if present.
  const fenced = trimmed.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i)
  const candidate = fenced ? fenced[1].trim() : trimmed

  try {
    return JSON.parse(candidate)
  }
  catch {
    // Fall back to the outermost {...} or [...].
    const start = Math.min(
      !candidate.includes('{') ? Infinity : candidate.indexOf('{'),
      !candidate.includes('[') ? Infinity : candidate.indexOf('['),
    )
    const end = Math.max(
      !candidate.includes('}') ? -1 : candidate.lastIndexOf('}'),
      !candidate.includes(']') ? -1 : candidate.lastIndexOf(']'),
    )
    if (start === Infinity || end === -1 || end < start)
      throw new Error(`Could not extract JSON from model output: ${trimmed.slice(0, 200)}`)
    const slice = candidate.slice(start, end + 1)
    return JSON.parse(slice)
  }
}
