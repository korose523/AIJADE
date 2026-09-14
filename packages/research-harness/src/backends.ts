/**
 * Pluggable LLM backends for the RQ-C harness.
 *
 * A {@link CandidateGenerator} produces a candidate skill implementation from a
 * task; a {@link SelfVerifier} judges whether that candidate is correct. The
 * full {@link LLMBackend} bundles both.
 *
 * Two implementations are provided:
 *  - {@link createMockBackend} — deterministic, seeded; for mechanism / estimator
 *    testing. It produces "wrong but runnable" candidates and a self-verdict that
 *    is driven by *configurable* hallucination / miss probabilities, never copied
 *    from the true outcome.
 *  - {@link createOllamaBackend} — talks to a local Ollama server via its
 *    `/api/chat` endpoint using `node:` fetch. Fails loudly if the model is
 *    unavailable (never silently emits fake data).
 */

import type { BenchTask } from '@proj-aijade/skill-bench-env'

import {
  extractCodeBlock,
  REFERENCE_SOLUTIONS,
  runTask,
  WRONG_CANDIDATES,
} from '@proj-aijade/skill-bench-env'

import { mulberry32 } from './stats'

export interface GenerateContext {
  /** Which attempt at this task this generation is (0-based). */
  attempt: number
  /** The previous failure detail, if the agent is retrying. */
  previousFailure?: string
}

export interface CandidateGenerator {
  /** Generate a candidate skill implementation (Markdown containing a ```js block). */
  generate: (task: BenchTask, ctx: GenerateContext) => Promise<string>
}

export interface SelfVerifierVerdict {
  verdict: 'pass' | 'fail'
  /** Self-reported confidence/skill score in [0,1]. */
  score: number
  rationale: string
}

export interface SelfVerifier {
  /** Judge whether the candidate solves the task, returning the model's self-assessment. */
  verify: (task: BenchTask, candidate: string) => Promise<SelfVerifierVerdict>
}

export interface LLMBackend {
  name: string
  generate: CandidateGenerator['generate']
  verify: SelfVerifier['verify']
}

function wrapCode(code: string): string {
  return [
    'Here is the implementation. Return ONLY the function; do not explain.',
    '',
    '```js',
    code,
    '```',
  ].join('\n')
}

export interface MockBackendOptions {
  /** Probability the generator emits the correct reference solution (default 0.5). */
  pCorrect?: number
  /**
   * Injected hallucination rate: P(self pass | actually WRONG). This is the rate
   * the diagnostic estimator should recover — it is NOT the true outcome.
   */
  hallucination?: number
  /** Injected miss rate: P(self fail | actually CORRECT). */
  miss?: number
  /** Seed for the backend's internal PRNG (default derived). */
  seed?: number
}

/**
 * Deterministic mock backend.
 *
 * Honesty note: the self-verdict is sampled from the configured hallucination /
 * miss rates *conditioned on the true outcome* (the mock runs the code internally
 * to learn the true outcome, then samples). This is a SIMULATION: it validates
 * that `computeSelfVerificationDiagnostics` recovers the injected rates. It must
 * never be read as an empirical hallucination rate — real rates come only from
 * `--backend ollama`.
 */
export function createMockBackend(seed: number, opts: MockBackendOptions = {}): LLMBackend {
  const pCorrect = opts.pCorrect ?? 0.5
  const hallucination = opts.hallucination ?? 0.3
  const miss = opts.miss ?? 0.1
  const rng = mulberry32(seed >>> 0)

  return {
    name: 'mock',
    async generate(task, _ctx) {
      const roll = rng()
      let code: string
      if (roll < pCorrect) {
        code = REFERENCE_SOLUTIONS[task.id]
      }
      else {
        const idx = Math.floor(rng() * WRONG_CANDIDATES.length)
        code = WRONG_CANDIDATES[idx]
      }
      return wrapCode(code)
    },
    async verify(task, candidate) {
      const code = extractCodeBlock(candidate) ?? candidate
      const verdict = runTask(code, task)
      const ok = verdict.ok
      // Sample the self-verdict from the injected rates; this is the simulation
      // knob that lets us test the estimator's unbiasedness.
      const pass = ok ? rng() >= miss : rng() < hallucination
      const score = pass ? 0.6 + rng() * 0.39 : rng() * 0.39
      return {
        verdict: pass ? 'pass' : 'fail',
        score,
        rationale: `[simulation] true_ok=${ok}; sampled self-verdict from hallucination=${hallucination}, miss=${miss}`,
      }
    },
  }
}

export interface OllamaSamplingOptions {
  /**
   * Sampling temperature. Fixed to 0 for greedy decoding so a given seed is
   *  fully reproducible (ACM "Reproduced" badge requirement).
   */
  temperature?: number
  /**
   * Integer sampling seed, injected into every request. MUST be derived from
   *  the run's master seed (e.g. CLI `--seed`) so two runs with the same seed
   *  produce identical generations/verdicts.
   */
  seed?: number
}

export interface OllamaBackendOptions {
  /** Model name passed to Ollama (e.g. "qwen2.5-coder:7b"). */
  model: string
  /** Base URL of the Ollama server (default http://localhost:11434). */
  baseUrl?: string
  /** Per-request timeout in ms (default 120000). */
  timeoutMs?: number
  /**
   * Sampling controls. `temperature` defaults to 0; `seed` should be injected
   *  from the run seed. If `seed` is omitted a deterministic hash of
   *  (model, baseUrl) is used as a fallback so results stay reproducible.
   */
  sampling?: OllamaSamplingOptions
}

/**
 * Ollama backend. Uses the native `fetch` (no new dependencies). Always fails
 * loudly when the server is unreachable or returns a non-OK status, so a missing
 * model can never masquerade as a (wrong) generation.
 */
export function createOllamaBackend(opts: OllamaBackendOptions): LLMBackend {
  const baseUrl = opts.baseUrl ?? 'http://localhost:11434'
  const model = opts.model
  const timeoutMs = opts.timeoutMs ?? 120_000
  const sampling = opts.sampling ?? {}

  return {
    name: 'ollama',
    async generate(task, _ctx) {
      const prompt = [
        'You are an expert JavaScript programmer.',
        `Implement the following function. Task: ${task.instruction}`,
        'Respond with ONLY a single fenced JavaScript code block (```js ... ```)',
        'that defines a function named `solve` (or a single callable expression).',
        'Do not include any explanation outside the code block.',
      ].join('\n')
      const content = await chat(baseUrl, model, prompt, timeoutMs, sampling)
      if (!content)
        throw new Error('Ollama generate() returned an empty response')
      return content
    },
    async verify(task, candidate) {
      const code = extractCodeBlock(candidate) ?? candidate
      const inputs = task.tests
        .map((t, i) => `  case ${i}: args = ${JSON.stringify(t.args)} (expected WITHHELD)`)
        .join('\n')
      const prompt = [
        'You are verifying a JavaScript solution against a task.',
        `Task: ${task.instruction}`,
        'Candidate code:',
        '```js',
        code,
        '```',
        'You are given ONLY the inputs of the test cases, never the expected outputs:',
        inputs,
        'For each case, decide whether the code returns the correct result, then give an overall verdict.',
        'Respond with a single line: either "PASS" or "FAIL", followed by a short reason.',
      ].join('\n')
      const content = await chat(baseUrl, model, prompt, timeoutMs, sampling)
      if (!content)
        throw new Error('Ollama verify() returned an empty response')
      const pass = /^\s*PASS\b/i.test(content)
      return {
        verdict: pass ? 'pass' : 'fail',
        score: pass ? 0.8 : 0.2,
        rationale: content.slice(0, 280),
      }
    },
  }
}

/**
 * Deterministic, reproducible seed for Ollama when one is not explicitly
 * injected. Derived purely from the (model, baseUrl) strings so it is stable
 * across runs; the CLI always overrides this with a value derived from
 * `--seed`.
 */
function deriveOllamaSeed(model: string, baseUrl: string): number {
  let h = 0x811C9DC5
  for (const ch of `${model}|${baseUrl}`) {
    h ^= ch.charCodeAt(0)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

async function chat(
  baseUrl: string,
  model: string,
  prompt: string,
  timeoutMs: number,
  sampling: OllamaSamplingOptions = {},
): Promise<string> {
  const temperature = sampling.temperature ?? 0
  const seed = sampling.seed ?? deriveOllamaSeed(model, baseUrl)
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(`${baseUrl}/api/chat`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      // LOCKED SAMPLING: temperature:0 + seed makes generations/verdicts
      // reproducible for a given run seed (ACM "Reproduced" badge). Without
      // `options` Ollama uses its default (random) sampling and runs diverge.
      body: JSON.stringify({
        model,
        messages: [{ role: 'user', content: prompt }],
        stream: false,
        options: { temperature, seed },
      }),
      signal: controller.signal,
    })
  }
  catch (e) {
    clearTimeout(timer)
    let reason: string
    if (e instanceof Error)
      reason = e.message
    else reason = String(e)
    throw new Error(
      `Ollama backend unreachable at ${baseUrl}/api/chat — is the model server running? (${reason})`,
    )
  }
  clearTimeout(timer)
  if (!res.ok)
    throw new Error(`Ollama backend returned HTTP ${res.status} ${res.statusText}`)
  const data = await res.json() as { message?: { content?: string } }
  return data?.message?.content ?? ''
}

/**
 * Query the Ollama server version. Used to stamp every run summary so a run is
 * uniquely identifiable (review §2.5). Returns `null` on any failure (timeout,
 * unreachable) rather than throwing — a missing version must never abort a run.
 */
export async function ollamaVersion(baseUrl: string, timeoutMs = 3000): Promise<string | null> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${baseUrl}/api/version`, { signal: controller.signal })
    if (!res.ok)
      return null
    const data = await res.json() as { version?: string }
    return data.version ?? null
  }
  catch {
    return null
  }
  finally {
    clearTimeout(timer)
  }
}
