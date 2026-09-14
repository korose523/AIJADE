/**
 * Ollama-backed L0 substrate.
 *
 * The only job here is to guarantee that a recorded fingerprint and an actual
 * request never disagree. Everything else (prompting, parsing, orchestration)
 * belongs in higher layers.
 */

import type {
  GenerateOptions,
  GenerateResult,
  ModelIdentity,
  RunFingerprint,
  SamplingConfig,
  Substrate,
  SubstrateMode,
} from './types'

import {
  assertCompleteSampling,
  assertResearchMode,
  buildFingerprint,
  resolveModelIdentity,
  resolveServerVersion,
} from './fingerprint'
import { SamplingError } from './types'

/**
 * Sampling recommended by the Qwythos Modelfile (Empero AI), for interactive use.
 * Note temperature 0.6 — that is fine for a product and fatal for an experiment.
 */
export const QWYTHOS_INTERACTIVE_SAMPLING: SamplingConfig = {
  temperature: 0.6,
  seed: 42,
  top_p: 0.95,
  top_k: 20,
  repeat_penalty: 1.05,
  num_ctx: 32768,
  num_predict: 2048,
  think: true,
}

/**
 * Deterministic decoding for experiments.
 *
 * `temperature: 0` is greedy decoding; `top_k: 1` is belt-and-braces so the
 * result stays greedy even if a future server changes how temperature 0 is
 * interpreted. `repeat_penalty: 1` disables a stateful-ish term whose effect
 * depends on prompt history in ways that are easy to forget.
 */
export const RESEARCH_SAMPLING: SamplingConfig = {
  temperature: 0,
  seed: 42,
  top_p: 1,
  top_k: 1,
  repeat_penalty: 1,
  num_ctx: 32768,
  num_predict: 2048,
  // Reasoning models emit a thinking trace and leave `content` empty while
  // thinking; for a deterministic factual-QA experiment we want the direct
  // answer only, so thinking is off. (It is still fingerprinted below.)
  think: false,
}

export interface OllamaSubstrateOptions {
  /** Model tag, e.g. "qwythos" or "qwen2.5-coder:7b-instruct". */
  model: string
  mode?: SubstrateMode
  /** Required unless `mode` is given; defaults per mode when omitted. */
  sampling?: SamplingConfig
  baseUrl?: string
  timeoutMs?: number
}

export interface OllamaSubstrate extends Substrate {
  readonly options: Required<Pick<OllamaSubstrateOptions, 'model' | 'mode' | 'baseUrl' | 'timeoutMs'>>
}

export function createOllamaSubstrate(options: OllamaSubstrateOptions): OllamaSubstrate {
  const model = options.model
  if (!model || !model.trim())
    throw new SamplingError('createOllamaSubstrate: "model" is required')

  const mode: SubstrateMode = options.mode ?? 'interactive'
  const baseUrl = (options.baseUrl ?? 'http://localhost:11434').replace(/\/+$/, '')
  const timeoutMs = options.timeoutMs ?? 120_000

  // Pick the mode-appropriate default, then let an explicit config win.
  const sampling = options.sampling ?? (mode === 'research' ? { ...RESEARCH_SAMPLING } : { ...QWYTHOS_INTERACTIVE_SAMPLING })

  assertCompleteSampling(sampling)
  if (mode === 'research')
    assertResearchMode(sampling)

  let identityPromise: Promise<ModelIdentity> | undefined
  let serverVersionPromise: Promise<string | undefined> | undefined

  function resolveSampling(override?: SamplingConfig): SamplingConfig {
    const effective = override ?? sampling
    assertCompleteSampling(effective)
    if (mode === 'research')
      assertResearchMode(effective)
    return effective
  }

  return {
    options: { model, mode, baseUrl, timeoutMs },

    identity() {
      identityPromise ??= resolveModelIdentity(baseUrl, model)
      return identityPromise
    },

    async fingerprint(override?: SamplingConfig): Promise<RunFingerprint> {
      const effective = resolveSampling(override)
      serverVersionPromise ??= resolveServerVersion(baseUrl)
      const [identity, serverVersion] = await Promise.all([this.identity(), serverVersionPromise])
      return buildFingerprint(mode, identity, effective, serverVersion)
    },

    async generate(opts: GenerateOptions): Promise<GenerateResult> {
      if (!opts.messages || opts.messages.length === 0)
        throw new SamplingError('generate(): at least one message is required')

      const effective = resolveSampling(opts.sampling)
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), timeoutMs)

      let res: Response
      try {
        res = await fetch(`${baseUrl}/api/chat`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            model,
            messages: opts.messages,
            stream: false,
            // Reasoning-model toggle — top level, not inside `options`.
            think: effective.think,
            // The whole point: never let the server choose decoding parameters.
            // `think: undefined` is dropped by JSON.stringify, so it never leaks
            // into `options` (where Ollama would ignore it anyway).
            options: { ...effective, think: undefined },
            ...(opts.json ? { format: 'json' } : {}),
          }),
          signal: controller.signal,
        })
      }
      catch (e) {
        clearTimeout(timer)
        throw new SamplingError(
          `Ollama unreachable at ${baseUrl}/api/chat — is the server running and is "${model}" pulled? `
          + `(${e instanceof Error ? String(e.message) : String(e)})`,
        )
      }
      clearTimeout(timer)

      if (!res.ok)
        throw new SamplingError(`Ollama returned HTTP ${res.status} ${res.statusText}`)

      const data = await res.json() as {
        model?: string
        created_at?: string
        message?: { content?: string }
        total_duration?: number
        eval_count?: number
        prompt_eval_count?: number
      }

      const text = data.message?.content ?? ''
      if (!text)
        throw new SamplingError('Ollama returned an empty completion — refusing to fabricate a result')

      return {
        text,
        model: data.model ?? model,
        createdAt: data.created_at ?? new Date().toISOString(),
        totalDurationNs: data.total_duration,
        evalCount: data.eval_count,
        promptEvalCount: data.prompt_eval_count,
        fingerprint: await this.fingerprint(effective),
      }
    },
  }
}
