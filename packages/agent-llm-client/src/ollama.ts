import type { ChatCompletion, ChatMessage, ChatRequestOptions } from './types'

import { nanoid } from 'nanoid'

import { createLogger } from './logger'
import { parseChatCompletion, parseJsonContent } from './parse'

const logger = createLogger('agent-llm-client')

export interface OllamaClientOptions {
  /** Base URL of an OpenAI-compatible server. Defaults to `http://localhost:11434` (Ollama). */
  baseURL?: string
  /** Default model name. Can be overridden per call by setting it on the client. */
  model?: string
  apiKey?: string
  /** Default per-request timeout in ms. Defaults to 120_000. */
  defaultTimeoutMs?: number
}

/**
 * Structural stand-in for a Zod schema so this package does not hard-depend on
 * `zod`. Any object with a `parse(input): T` method (including `z.ZodType`) works.
 */
export interface ZodSchemaLike<T> {
  parse: (input: unknown) => T
}

export interface JsonCompleteOptions<T> extends ChatRequestOptions {
  /** Optional validator applied to the parsed JSON. */
  schema?: ZodSchemaLike<T>
}

export interface OllamaClient {
  readonly baseURL: string
  readonly model: string
  /** One chat turn, returning the raw text completion. */
  complete: (messages: ChatMessage[], options?: ChatRequestOptions) => Promise<ChatCompletion>
  /** One chat turn forced to JSON output, parsed (and optionally validated). */
  jsonComplete: <T = unknown>(messages: ChatMessage[], options?: JsonCompleteOptions<T>) => Promise<T>
  /** List models available on the server (`/api/tags`). */
  listModels: () => Promise<string[]>
}

function normalizeBaseURL(baseURL?: string): string {
  const raw = (baseURL ?? 'http://localhost:11434').trim().replace(/\/+$/, '')
  return raw
}

interface BuildBodyOptions {
  temperature?: number
  topP?: number
  maxTokens?: number
  stop?: string[]
}

function buildBody(
  model: string,
  messages: ChatMessage[],
  options: BuildBodyOptions,
  jsonMode: boolean,
): Record<string, unknown> {
  const body: Record<string, unknown> = {
    model,
    stream: false,
    messages: messages.map(m => ({
      role: m.role,
      content: m.content,
      ...(m.name ? { name: m.name } : {}),
    })),
  }
  if (jsonMode)
    body.response_format = { type: 'json_object' }
  if (options.temperature !== undefined)
    body.temperature = options.temperature
  if (options.topP !== undefined)
    body.top_p = options.topP
  if (options.maxTokens !== undefined)
    body.max_tokens = options.maxTokens
  if (options.stop)
    body.stop = options.stop
  return body
}

async function fetchJson(
  url: string,
  body: unknown | null,
  apiKey: string | undefined,
  signal: AbortSignal,
): Promise<unknown> {
  const res = await fetch(url, {
    method: body ? 'POST' : 'GET',
    headers: {
      'content-type': 'application/json',
      ...(apiKey ? { authorization: `Bearer ${apiKey}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`LLM request failed (${res.status} ${res.statusText}): ${text.slice(0, 500)}`)
  }
  return res.json()
}

/**
 * Create a chat client for any OpenAI-compatible server. Out of the box it
 * targets the local Ollama instance (`:11434`), which is what AIJADE already
 * runs for on-device inference.
 */
export function createOllamaClient(options: OllamaClientOptions = {}): OllamaClient {
  const baseURL = normalizeBaseURL(options.baseURL)
  const model = options.model ?? 'default'
  const apiKey = options.apiKey
  const defaultTimeoutMs = options.defaultTimeoutMs ?? 120_000

  async function complete(messages: ChatMessage[], opts: ChatRequestOptions = {}): Promise<ChatCompletion> {
    const timeoutMs = opts.timeoutMs ?? defaultTimeoutMs
    const signal = opts.signal ?? AbortSignal.timeout(timeoutMs)
    const body = buildBody(model, messages, opts, false)
    const requestId = nanoid(8)
    logger.debug(`chat/completions id=${requestId} model=${model} messages=${messages.length}`)
    const data = await fetchJson(`${baseURL}/v1/chat/completions`, body, apiKey, signal)
    return parseChatCompletion(data, model)
  }

  async function jsonComplete<T = unknown>(
    messages: ChatMessage[],
    opts: JsonCompleteOptions<T> = {},
  ): Promise<T> {
    const timeoutMs = opts.timeoutMs ?? defaultTimeoutMs
    const signal = opts.signal ?? AbortSignal.timeout(timeoutMs)
    const body = buildBody(model, messages, opts, true)
    const requestId = nanoid(8)
    logger.debug(`chat/completions(json) id=${requestId} model=${model} messages=${messages.length}`)
    const data = await fetchJson(`${baseURL}/v1/chat/completions`, body, apiKey, signal)
    const completion = parseChatCompletion(data, model)
    const parsed = parseJsonContent(completion.text)
    if (opts.schema)
      return opts.schema.parse(parsed)
    return parsed as T
  }

  async function listModels(): Promise<string[]> {
    const requestId = nanoid(8)
    logger.debug(`list/models id=${requestId}`)
    const data = await fetchJson(`${baseURL}/api/tags`, null, apiKey, AbortSignal.timeout(defaultTimeoutMs))
    const models = (data as { models?: Array<{ name?: string }> })?.models ?? []
    return models.map(m => m.name ?? '').filter(Boolean)
  }

  return {
    baseURL,
    model,
    complete,
    jsonComplete,
    listModels,
  }
}
