/**
 * Minimal chat-protocol types shared across AIJADE's agent capability packages.
 *
 * These intentionally mirror the OpenAI chat-completions shape (which is what
 * Ollama's `/v1/chat/completions` endpoint speaks) so the client can talk to
 * any OpenAI-compatible server — local Ollama, Nous Portal, OpenRouter, etc.
 */

export type ChatRole = 'system' | 'user' | 'assistant' | 'tool'

export interface ChatMessage {
  role: ChatRole
  content: string
  /** Optional author name (used for `tool` / named participants). */
  name?: string
}

export interface ChatRequestOptions {
  temperature?: number
  topP?: number
  maxTokens?: number
  stop?: string[]
  /** Abort an in-flight request. */
  signal?: AbortSignal
  /** Per-call timeout in ms (defaults to the client's `defaultTimeoutMs`). */
  timeoutMs?: number
}

export interface TokenUsage {
  promptTokens: number
  completionTokens: number
  totalTokens: number
}

export interface ChatCompletion {
  id: string
  model: string
  text: string
  finishReason: string | null
  usage: TokenUsage | null
  /** The raw provider payload, kept for debugging / extensibility. */
  raw: unknown
}
