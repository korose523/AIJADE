/**
 * Real LLM adapter — backs the product-layer {@link LlmPort} with a local or
 * remote OpenAI-compatible chat server (the in-repo `agent-llm-client`, which
 * targets the on-device Ollama instance at `:11434` by default).
 *
 * This replaces the deterministic `StubLlm` in `in-memory.ts` with a genuine
 * model call: `complete(prompt)` sends a single user turn and returns the raw
 * text completion, exactly what the growth services expect.
 */

import type { OllamaClient, OllamaClientOptions } from '@proj-aijade/agent-llm-client'

import type { LlmPort } from '../ports'

import process from 'node:process'

import { createOllamaClient } from '@proj-aijade/agent-llm-client'

export interface OllamaLlmOptions {
  baseURL?: string
  model?: string
  apiKey?: string
  defaultTimeoutMs?: number
}

/**
 * Genuine {@link LlmPort} implementation. Talks to any OpenAI-compatible
 * `/v1/chat/completions` endpoint (Ollama, Nous Portal, OpenRouter, …).
 */
export class OllamaLlmAdapter implements LlmPort {
  private readonly client: OllamaClient
  private readonly resolvedModel: string

  constructor(opts: OllamaLlmOptions = {}) {
    const baseURL = opts.baseURL ?? process.env.AIJADE_LLM_BASE_URL ?? 'http://localhost:11434'
    const model = opts.model ?? process.env.AIJADE_LLM_MODEL ?? 'qwythos:latest'
    this.resolvedModel = model
    const clientOpts: OllamaClientOptions = {
      baseURL,
      model,
      apiKey: opts.apiKey ?? process.env.AIJADE_LLM_API_KEY,
      defaultTimeoutMs: opts.defaultTimeoutMs ?? 120_000,
    }
    this.client = createOllamaClient(clientOpts)
  }

  /** The model this adapter will call (useful for logging / tests). */
  get model(): string {
    return this.resolvedModel
  }

  async complete(prompt: string): Promise<string> {
    const completion = await this.client.complete([{ role: 'user', content: prompt }])
    return completion.text
  }

  /** Probe reachability; returns the available model names or `null` on failure. */
  async listModels(): Promise<string[] | null> {
    try {
      return await this.client.listModels()
    }
    catch {
      return null
    }
  }
}

/** Build the default Ollama-backed LLM adapter (honours env config). */
export function createDefaultOllamaLlm(opts: OllamaLlmOptions = {}): OllamaLlmAdapter {
  return new OllamaLlmAdapter(opts)
}
