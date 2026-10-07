/**
 * Determinism verification for L0.
 *
 * This exists because reproducibility is an *empirical* property, not a
 * declaration. Greedy decoding on llama.cpp is usually bit-exact, but batch
 * scheduling and floating-point reduction order can differ between calls, so
 * "we set temperature to 0" is a claim that needs evidence behind it.
 *
 * Run this once per model before trusting any experiment that uses it, and
 * record the result alongside the artifact.
 *
 * ## Scope of the guarantee — read this before quoting the check in a paper
 *
 * Passing means: **on this machine, with this server, at this batch size, right
 * now**, decoding is reproducible. It does **not** mean the run reproduces on
 * other hardware. Greedy decoding is not precision-invariant: floating-point
 * addition is non-associative, and device / kernel / batch-size changes alter
 * the reduction order, so the same weights and prompt can still diverge.
 * Measured elsewhere at up to **9% accuracy and 9,000 tokens of length
 * difference** under BF16 when only GPU count, GPU type and batch size were
 * varied [Yuan et al., arXiv:2506.09501], and **49–100% of prompts diverging**
 * between BF16 and FP16 on *identical* hardware [Du et al., TMLR 2026,
 * arXiv:2609.26621]; cross-architecture bitwise agreement requires fixing the
 * reduction order itself [Cooper et al., arXiv:2609.25624].
 *
 * ⇒ Cite this check as **"same-device, same-configuration reproducibility"**
 *   and nothing stronger. This module does not, and cannot, test cross-device
 *   reproducibility: every repeat runs through the same substrate instance.
 *
 * ## Known false positive — a PASS here is not yet evidence of greedy decoding
 *
 * Read this before quoting `identical: true` as "the sampler was pinned".
 *
 * `measureDeterminism` observes one thing: *the output did not change while the
 * seed changed.* It cannot tell **why** it did not change. At least two very
 * different mechanisms produce that observation:
 *
 * 1. decoding really is greedy, so the seed is irrelevant; or
 * 2. **the sampling parameters never reached the decoder at all**, so there was
 *    nothing for the seed to perturb.
 *
 * Case 2 is not hypothetical. Measured on 2026-10-07 against Ollama 0.35.1
 * (`qwythos:latest`, `127.0.0.1:11434`, prompt asking for a ~120-word
 * description of the water cycle, output 776 chars, `think: false`), 5 runs
 * under each arm:
 *
 * | arm | sampling | 5 varied-seed runs |
 * |---|---|---|
 * | A greedy (= `RESEARCH_SAMPLING`) | `temperature=0, top_k=1, top_p=1` | 5/5 byte-identical, sha256 `a0b618b83646` |
 * | B sampling (positive control) | `temperature=1.0, top_k=40, top_p=0.95` | **also 5/5 byte-identical, same sha256 `a0b618b83646`** |
 *
 * Arm B deliberately opened the sampler. If the check had discriminating
 * power, arm B would have diverged. It did not ⇒ "output is stable across
 * seeds" **cannot distinguish real greedy decoding from sampling parameters
 * being silently dropped**. For a substrate with no seed support at all this is
 * a *guaranteed* false positive: `mem0/llms/ollama.py` builds its `options`
 * literal from only `temperature / num_predict / top_p` (`seed` appears zero
 * times in the file, and `top_k` is accepted by config but never read), so
 * `measureDeterminism(..., {seedStrategy: 'varied'})` against mem0 always
 * reports "deterministic" no matter what the sampler is doing.
 *
 * ⇒ Therefore: **`identical: true` is only evidence once a positive control has
 *   diverged on the same substrate.** Run `auditDeterminism`, which pairs the
 *   main check with a positive control that *must* diverge if sampling is
 *   honoured. Three outcomes, none of which may be silently collapsed into
 *   "pass":
 *
 *   - control diverges ⇒ the check does discriminate; `identical: true` stands.
 *   - control is identical ⇒ **false-positive alarm**: this substrate cannot
 *     distinguish the two mechanisms, so the main result proves nothing.
 *   - control could not run (server rejected the parameters / model does not
 *     support them) ⇒ **indeterminate**; *not* a pass. An unrunnable control
 *     means the question is unanswered.
 *
 *   The control must vary the seed *and* open the temperature: a fixed seed
 *   with `temperature > 0` is itself deterministic on Ollama, so a
 *   fixed-seed control would "pass" while proving nothing.
 *
 * Note the control cannot be run through a `research`-mode substrate — that
 * mode rejects `temperature !== 0` by design. Pass a substrate that permits
 * sampling; if you do not, the control reports `indeterminate`.
 *
 * ## Traps when running the control by hand
 *
 * - **Send `"think": false`.** A reasoning model left in thinking mode returns
 *   an empty `message.content`, and N identical empty strings hash the same —
 *   a fake "the control didn't diverge" pass.
 * - **Use a prompt that forces a long, prose-like answer.** A short prompt
 *   ("reply yes") has one correct answer under *every* decoding mode, so the
 *   control cannot diverge no matter how well sampling works. This is why the
 *   CLI uses a ≥100-character probe for the control arm.
 * - **Reach the server on `127.0.0.1`, not `localhost`** (IPv4-only listener).
 */

import type { ChatMessage, SamplingConfig, Substrate } from './types'

import { fnv1a, hashSampling } from './fingerprint'

export interface DeterminismOptions {
  /** Number of repeats. Use >= 3; 5 is cheap and catches flakiness. */
  runs?: number
  /**
   * `fixed`   — reuse one seed; outputs must match exactly.
   * `varied`  — use a different seed each run; if outputs still match, decoding
   *             is seed-independent (i.e. genuinely greedy), which is the
   *             strongest reproducibility guarantee available.
   */
  seedStrategy?: 'fixed' | 'varied'
}

export interface DeterminismRun {
  index: number
  seed: number
  hash: string
  chars: number
  text: string
}

export interface DeterminismReport {
  identical: boolean
  runs: number
  seedStrategy: 'fixed' | 'varied'
  uniqueOutputs: number
  perRun: DeterminismRun[]
  /** Fingerprint of the final run, for artifact recording. */
  fingerprint: string
}

export function hashText(text: string): string {
  return fnv1a(text)
}

/**
 * Run the same request repeatedly and report whether outputs actually match.
 */
export async function measureDeterminism(
  substrate: Substrate,
  messages: ChatMessage[],
  options: DeterminismOptions = {},
): Promise<DeterminismReport> {
  const runs = Math.max(2, options.runs ?? 5)
  const seedStrategy = options.seedStrategy ?? 'fixed'

  const baseFingerprint = await substrate.fingerprint()
  const baseSampling: SamplingConfig = baseFingerprint.sampling

  const perRun: DeterminismRun[] = []
  let lastFingerprint = baseFingerprint.fingerprint

  for (let i = 0; i < runs; i++) {
    const seed = seedStrategy === 'varied' ? baseSampling.seed + i * 7919 : baseSampling.seed
    const result = await substrate.generate({
      messages,
      sampling: { ...baseSampling, seed },
    })
    lastFingerprint = result.fingerprint.fingerprint
    perRun.push({
      index: i,
      seed,
      hash: hashText(result.text),
      chars: result.text.length,
      text: result.text,
    })
  }

  const unique = new Set(perRun.map(r => r.hash)).size

  return {
    identical: unique === 1,
    runs,
    seedStrategy,
    uniqueOutputs: unique,
    perRun,
    fingerprint: lastFingerprint,
  }
}

/**
 * Throw unless every repeat produced byte-identical output.
 *
 * Intended for CI and for the pre-flight check before a long experiment: better
 * to discover non-determinism in 30 seconds than after a 3-hour run.
 *
 * ⚠️ This inherits the false positive documented at the top of this file: it can
 * only see *that* outputs matched, never *why*. Prefer `assertDeterminismAudit`,
 * which additionally requires a positive control to diverge before it will
 * accept a pass.
 */
export async function assertDeterminism(
  substrate: Substrate,
  messages: ChatMessage[],
  options: DeterminismOptions = {},
): Promise<DeterminismReport> {
  const report = await measureDeterminism(substrate, messages, options)
  if (!report.identical) {
    const summary = report.perRun
      .map(r => `run ${r.index} seed=${r.seed} hash=${r.hash} chars=${r.chars}`)
      .join('\n  ')
    throw new Error(
      `Non-deterministic decoding: ${report.uniqueOutputs} distinct outputs across ${report.runs} runs.\n  ${summary}\n`
      + 'Refusing to run an experiment on a substrate that cannot reproduce itself.',
    )
  }
  return report
}

/* ------------------------------------------------------------------------- *
 * Positive control — the thing that makes the pass mean something
 * ------------------------------------------------------------------------- */

/**
 * Default sampling overrides for the positive control.
 *
 * Deliberately the arm-B configuration from the measured table in the file
 * header: wide open (`temperature=1`), nucleus sampling on, top-k wide. If the
 * decoder honours these, a seed change *must* move the output.
 */
export const SAMPLING_CONTROL_OVERRIDES: Partial<SamplingConfig> = {
  temperature: 1,
  top_k: 40,
  top_p: 0.95,
}

/**
 * What the control arm observed. Deliberately three-valued — collapsing
 * "identical" and "could not run" into a single `false` is exactly the mistake
 * that lets a false positive through quietly.
 *
 * - `divergent`    — output moved across runs ⇒ sampling parameters are honoured,
 *                    so the substrate is capable of showing sampling sensitivity
 *                    and the main check has discriminating power.
 * - `identical`    — output did *not* move even with the sampler wide open ⇒
 *                    sampling parameters are being ignored ⇒ the main check
 *                    cannot distinguish greedy decoding from a dropped config.
 * - `indeterminate`— the control could not be executed or its output is
 *                    unusable (server rejected the parameters, model does not
 *                    support them, or every completion came back empty).
 *                    **Not** a pass.
 */
export type SamplingControlVerdict = 'divergent' | 'identical' | 'indeterminate'

export interface SamplingControlRun {
  index: number
  seed: number
  hash: string
  chars: number
  text: string
}

export interface SamplingControlReport {
  verdict: SamplingControlVerdict
  /** Always populated. The sentence a reader of the artifact needs. */
  reason: string
  runs: number
  uniqueOutputs: number
  perRun: SamplingControlRun[]
  /** The exact config sent on every control run. Evidence, not decoration. */
  sampling: SamplingConfig
  samplingHash: string
  /** Populated only when `verdict === 'indeterminate'`. */
  error?: string
}

export interface SamplingControlOptions {
  /** Repeats for the control arm. Default 5. */
  runs?: number
  /** Probe prompt for the control. Defaults to the main check's messages. */
  messages?: ChatMessage[]
  /**
   * Substrate used for the control arm. It must *permit* sampling: a
   * `research`-mode substrate rejects `temperature !== 0` by design, so passing
   * one here yields `indeterminate` (the honest answer, not a workaround).
   * Defaults to the substrate under test.
   */
  substrate?: Substrate
  /** Sampling overrides for the control arm. Defaults to `SAMPLING_CONTROL_OVERRIDES`. */
  sampling?: Partial<SamplingConfig>
}

/**
 * Run a deliberately non-greedy arm to prove the substrate *can* show sampling
 * sensitivity.
 *
 * This is the positive control for `measureDeterminism`. It answers exactly one
 * question — "if I open the sampler and change the seed, does anything move?" —
 * and it answers it in three distinguishable ways so that a caller cannot
 * accidentally read "the sampler was ignored" as "the model is deterministic".
 *
 * Both knobs are turned at once on purpose: a *fixed* seed with
 * `temperature > 0` is itself deterministic on Ollama, so a fixed-seed control
 * would report `identical` while demonstrating nothing.
 *
 * Default off in the sense that nothing here runs unless a caller asks: it is a
 * separate exported function, never invoked by `measureDeterminism`.
 */
export async function runSamplingControl(
  substrate: Substrate,
  messages: ChatMessage[],
  options: SamplingControlOptions = {},
): Promise<SamplingControlReport> {
  const runs = Math.max(2, options.runs ?? 5)
  const controlSubstrate = options.substrate ?? substrate

  // Build the control config on top of whatever the substrate itself considers a
  // complete config, so the control differs from the main arm *only* in the
  // sampling knobs we are deliberately widening.
  const baseFingerprint = await controlSubstrate.fingerprint()
  const sampling: SamplingConfig = {
    ...baseFingerprint.sampling,
    ...SAMPLING_CONTROL_OVERRIDES,
    ...options.sampling,
  }

  const perRun: SamplingControlRun[] = []

  for (let i = 0; i < runs; i++) {
    const seed = sampling.seed + i * 7919
    let text: string
    try {
      const result = await controlSubstrate.generate({
        messages: options.messages ?? messages,
        sampling: { ...sampling, seed },
      })
      text = result.text
    }
    catch (e) {
      // A refused request is not a passing control. Report it as undecidable
      // and hand the caller the server's own words.
      const error = e instanceof Error ? e.message : String(e)
      return {
        verdict: 'indeterminate',
        reason: `Positive control aborted on run ${i} of ${runs}: the substrate refused the wide-open sampling request. `
          + 'Sampling sensitivity is UNKNOWN — this is not evidence that the main check passed.',
        runs,
        uniqueOutputs: new Set(perRun.map(r => r.hash)).size,
        perRun,
        sampling,
        samplingHash: hashSampling(sampling),
        error,
      }
    }
    perRun.push({ index: i, seed, hash: hashText(text), chars: text.length, text })
  }

  const uniqueOutputs = new Set(perRun.map(r => r.hash)).size

  // The reasoning-model trap: `think` left on, `message.content` is empty for
  // every run, and N identical empty strings hash the same — a fake
  // "the control did not diverge" result. Catch it rather than report it.
  if (perRun.every(r => r.chars === 0)) {
    return {
      verdict: 'indeterminate',
      reason: 'Positive control returned an empty completion on every run (all hashes identical only because "" is). '
        + 'This is the reasoning-model `think` trap, not a result. Re-run with "think": false.',
      runs,
      uniqueOutputs,
      perRun,
      sampling,
      samplingHash: hashSampling(sampling),
      error: 'all control completions were empty',
    }
  }

  if (uniqueOutputs > 1) {
    return {
      verdict: 'divergent',
      reason: `Positive control produced ${uniqueOutputs} distinct outputs across ${runs} runs with the sampler wide open. `
        + 'The substrate demonstrably responds to sampling parameters, so a matching main check reflects real greedy decoding.',
      runs,
      uniqueOutputs,
      perRun,
      sampling,
      samplingHash: hashSampling(sampling),
    }
  }

  return {
    verdict: 'identical',
    reason: `FALSE-POSITIVE ALARM: the positive control produced 1 distinct output across ${runs} runs even with `
      + `${JSON.stringify(options.sampling ?? SAMPLING_CONTROL_OVERRIDES)} and a different seed every run. `
      + 'Sampling parameters are being ignored on this substrate, so the main check cannot tell genuine greedy '
      + 'decoding from a dropped sampling config. Do NOT report the main check as a determinism pass.',
    runs,
    uniqueOutputs,
    perRun,
    sampling,
    samplingHash: hashSampling(sampling),
  }
}

/* ------------------------------------------------------------------------- *
 * Audit — main check plus positive control, with an explicit verdict
 * ------------------------------------------------------------------------- */

/**
 * - `pass`                  — main check matched **and** the positive control
 *                             diverged. The only outcome that licenses quoting
 *                             the main check as a determinism result.
 * - `non-deterministic`     — the main check found divergence. A true negative:
 *                             the substrate genuinely does not reproduce itself.
 * - `false-positive-risk`   — main check matched but the control did not move,
 *                             so the match carries no information.
 * - `inconclusive-control`  — the control could not run. Unknown, not a pass.
 */
export type DeterminismAuditVerdict
  = | 'pass'
    | 'non-deterministic'
    | 'false-positive-risk'
    | 'inconclusive-control'

export interface DeterminismAuditOptions extends DeterminismOptions {
  /** Positive-control configuration. The control is part of every audit. */
  control?: SamplingControlOptions
}

export interface DeterminismAudit {
  verdict: DeterminismAuditVerdict
  /** True only when the control diverged — i.e. the substrate *can* show sampling sensitivity. */
  discriminative: boolean
  /** True when the main check said "identical" but that result must not be trusted. */
  falsePositiveRisk: boolean
  /** Always populated. */
  reason: string
  /** The unmodified main check, for the artifact record. */
  check: DeterminismReport
  /** The positive control, including the config it actually used. */
  control: SamplingControlReport
}

/**
 * `measureDeterminism` + a positive control, with a verdict that cannot be
 * mistaken for a pass.
 *
 * Use this instead of `measureDeterminism` whenever the result is going into a
 * paper, an artifact, or a pre-flight gate. `measureDeterminism` alone can only
 * report that outputs matched; this can say whether that observation means
 * anything.
 */
export async function auditDeterminism(
  substrate: Substrate,
  messages: ChatMessage[],
  options: DeterminismAuditOptions = {},
): Promise<DeterminismAudit> {
  const check = await measureDeterminism(substrate, messages, options)

  const control = await runSamplingControl(substrate, messages, {
    runs: options.runs,
    ...options.control,
  })

  if (control.verdict === 'indeterminate') {
    return {
      verdict: 'inconclusive-control',
      discriminative: false,
      falsePositiveRisk: check.identical,
      reason: `Determinism is UNDECIDED on this substrate. ${control.reason}`,
      check,
      control,
    }
  }

  if (control.verdict === 'identical') {
    // Whether or not the main check matched, the control tells us the substrate
    // is blind to sampling parameters — so a match proves nothing. If the main
    // check *did* diverge, that divergence is still a real observation.
    return {
      verdict: check.identical ? 'false-positive-risk' : 'non-deterministic',
      discriminative: false,
      falsePositiveRisk: check.identical,
      reason: check.identical
        ? control.reason
        : `${control.reason} Note: the main check did diverge (${check.uniqueOutputs} distinct outputs across `
          + `${check.runs} runs), so the substrate is non-reproducible regardless — but the blind control means the `
          + 'underlying cause (sampling config dropped vs. genuine run-to-run nondeterminism) is still unknown.',
      check,
      control,
    }
  }

  // Control diverged: the substrate is demonstrably sensitive to sampling, so
  // the main check's verdict is meaningful.
  if (!check.identical) {
    return {
      verdict: 'non-deterministic',
      discriminative: true,
      falsePositiveRisk: false,
      reason: `Genuinely non-deterministic: ${check.uniqueOutputs} distinct outputs across ${check.runs} runs, on a substrate `
        + 'whose positive control confirms sampling parameters are honoured.',
      check,
      control,
    }
  }

  return {
    verdict: 'pass',
    discriminative: true,
    falsePositiveRisk: false,
    reason: `Deterministic and verified: 1 distinct output across ${check.runs} ${check.seedStrategy}-seed runs, on a substrate `
      + 'whose positive control diverged — so the match reflects real greedy decoding, not ignored sampling parameters.',
    check,
    control,
  }
}

/**
 * Throw unless the audit says `pass`.
 *
 * This is the gate to put in front of a long experiment. It refuses in all three
 * non-pass cases, so a false positive or an unrunnable control cannot slip
 * through as a green result.
 */
export async function assertDeterminismAudit(
  substrate: Substrate,
  messages: ChatMessage[],
  options: DeterminismAuditOptions = {},
): Promise<DeterminismAudit> {
  const audit = await auditDeterminism(substrate, messages, options)
  if (audit.verdict === 'pass')
    return audit

  const controlDetail = [
    `control verdict    ${audit.control.verdict}`,
    `control sampling   ${JSON.stringify(audit.control.sampling)}`,
    `control samplingHash ${audit.control.samplingHash}`,
    `control hashes     ${audit.control.perRun.map(r => r.hash).join(', ') || '(none completed)'}`,
  ].join('\n  ')

  throw new Error(
    `Determinism audit did not pass (${audit.verdict}).\n${audit.reason}\n  ${controlDetail}\n`
    + 'Refusing to treat an unverified or contradicted determinism check as a pass.',
  )
}
