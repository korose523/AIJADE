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

/**
 * Redacted environment-feedback signal handed back to the generator on a retry.
 *
 * WHY IT IS REDACTED: the whole measurement rests on the oracle being a
 * reference standard* the model cannot read. `BenchFailure` carries both
 * `expected` and `actual`, so forwarding it verbatim would let the model copy
 * the answer and would invalidate `hallucinationRate` / `missRate`. We therefore
 * forward only what a real sandbox legitimately exposes — which cases failed,
 * how many passed, and any error the candidate itself raised — and never the
 * expected outputs. This preserves the no-leakage invariant that the `verify()`
 * path also obeys (expected outputs are withheld there too).
 */
export interface EnvironmentFeedbackSignal {
  /** 0-based indices of the test cases the candidate failed. */
  failedCaseIndices: number[]
  /** How many cases passed. */
  passed: number
  /** Total cases in the task's suite. */
  total: number
  /** Error messages raised by the candidate itself (never expected values). */
  errors: string[]
}

/**
 * Context handed to {@link CandidateGenerator.generate} on every call.
 *
 * CRITICAL (see the "constructive null design" note in harness.ts): if this
 * context is ignored, and the backend decodes greedily, then a regeneration is
 * byte-identical to the first attempt. The envFeedback and selfVerification
 * manipulations would then have NO causal path to the execution outcome, and all
 * four 2x2 cells would be forced to the same precision. The generators below
 * therefore MUST fold this context into the prompt.
 */
export interface GenerateContext {
  /** Which attempt at this task this generation is (0-based). */
  attempt: number
  /**
   * Present iff the `envFeedback` factor is ON and a previous execution failed.
   * This is the environment's contribution to the closed loop.
   */
  envFeedback?: EnvironmentFeedbackSignal
  /**
   * Present iff the `selfVerification` factor is ON and the model rejected a
   * previous candidate. This is the self-verifier's contribution to the loop.
   */
  selfCritique?: string
  /**
   * The candidate that is being replaced. At `temperature: 0` a 7B model will
   * happily re-emit its own earlier solution even when the prompt has changed,
   * which makes the retry inert again by a different route (measured: 2 of 3
   * retries returned byte-identical code with feedback alone). Showing the model
   * its own rejected code and forbidding a repeat is what actually moves it.
   */
  previousCode?: string
  /** @deprecated free-text failure detail; superseded by `envFeedback`. */
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
  /**
   * Probability that a RETRY carrying a feedback signal (environment failure or
   * self-critique) produces the reference solution. This is the simulation knob
   * that models "a retry informed by evidence can actually fix the bug".
   *
   * It exists because a retry knob of exactly 0 is the *constructive null
   * design*: if retries can never change the outcome, the envFeedback axis has
   * no causal path and the 2x2 is guaranteed to be a null. Default 0.7.
   */
  pRetrySuccess?: number
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
  const pRetrySuccess = opts.pRetrySuccess ?? 0.7
  const rng = mulberry32(seed >>> 0)

  /** True when the caller actually handed the generator a feedback signal. */
  const hasSignal = (ctx: GenerateContext) =>
    ctx.envFeedback !== undefined || ctx.selfCritique !== undefined || ctx.previousFailure !== undefined

  return {
    name: 'mock',
    async generate(task, ctx) {
      // A retry that carries evidence can recover; a retry without evidence is
      // the null design (identical output, no causal path). Gating recovery on
      // the *presence of a signal* is what makes the mock a faithful positive
      // control for the reachability diagnostic.
      if (ctx.attempt > 0 && hasSignal(ctx) && rng() < pRetrySuccess)
        return wrapCode(REFERENCE_SOLUTIONS[task.id])
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
 * Build the generation prompt as a DETERMINISTIC function of
 * `(task, ctx)`. Determinism is preserved under `temperature: 0` because the
 * prompt itself — not the sampler — carries the variation. That is the whole
 * point: two retries differ only because the *evidence* differs.
 */
export function buildGeneratePrompt(task: BenchTask, ctx: GenerateContext): string {
  const s = ctx.selfCritique
  const e = ctx.envFeedback
  const informedRetry = (e !== undefined || s !== undefined || ctx.previousFailure !== undefined) && ctx.attempt > 0

  const lines: string[] = []

  // On an informed retry the evidence comes FIRST and the implementation request
  // LAST, so the model reads the diagnosis before it starts writing. Putting the
  // evidence after the code request measurably fails to change the output.
  if (informedRetry) {
    lines.push('You are an expert JavaScript programmer fixing a previous failure.')
    lines.push(`Task: ${task.instruction}`)
    lines.push('')
    lines.push('--- WHY THE PREVIOUS ATTEMPT FAILED ---')
    if (e) {
      lines.push(`The previous implementation was executed against the task's test suite and FAILED: ${e.passed}/${e.total} cases passed.`)
      if (e.failedCaseIndices.length > 0)
        lines.push(`Failing case indices (0-based): ${e.failedCaseIndices.join(', ')}.`)
      if (e.errors.length > 0)
        lines.push(`It raised: ${e.errors.join(' | ')}`)
      lines.push('The expected outputs of the test cases are withheld from you. Diagnose the defect from the case inputs and the failure pattern.')
    }
    if (s)
      lines.push(`Your own verification step REJECTED the previous implementation with this critique: ${s}`)
    lines.push('')
    if (ctx.previousCode && ctx.previousCode.trim().length > 0) {
      lines.push('The rejected implementation, which you MUST NOT repeat:')
      lines.push('```js')
      lines.push(ctx.previousCode.trim())
      lines.push('```')
      lines.push('')
    }
    lines.push('Write a CORRECTED implementation that is materially DIFFERENT from the rejected one.')
    lines.push('Re-examine the specification and the failing cases; do not just re-emit the same logic with cosmetic edits.')
  }
  else {
    lines.push('You are an expert JavaScript programmer.')
    lines.push(`Implement the following function. Task: ${task.instruction}`)
  }

  lines.push('Respond with ONLY a single fenced JavaScript code block (```js ... ```)')
  lines.push('that defines a function named `solve` (or a single callable expression).')
  lines.push('Do not include any explanation outside the code block.')

  return lines.join('\n')
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
    async generate(task, ctx) {
      const prompt = buildGeneratePrompt(task, ctx)
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
