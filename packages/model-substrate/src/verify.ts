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
 */

import type { ChatMessage, SamplingConfig, Substrate } from './types'

import { fnv1a } from './fingerprint'

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
