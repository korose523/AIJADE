/**
 * v7 §38 / J1-C5 — opt-in fault-injection harness (AgentChaos-style taxonomy).
 *
 * Motivation (J1 §C5): a verifiable event-driven architecture must be shown to
 * fail closed* under component faults, not just succeed on the happy path. This
 * module is a SELF-CONTAINED, OPT-IN instantiation of that methodology on the
 * memory-retrieval path: it perturbs the candidates an agent actually receives,
 * so robustness claims become reproducible and falsifiable.
 *
 * Design contract (matches §38's reproducibility requirements):
 * - **Opt-in + default-off**: the store only calls the injector when
 *   `config.faultInjection.enabled` is explicitly true. Absent config ⇒ zero
 *   behaviour change on the default path (H2c compatible).
 * - **Deterministic**: fault selection is driven by the existing
 *   `interventionRng(seed)` (the same RNG the §38 ablation system uses), and
 *   candidates are processed in a stable (id-sorted) order, so the *same*
 *   (config, candidate set) always yields the *same* perturbation. Reproducible,
 *   not declared.
 * - **AgentChaos taxonomy**: `message_drop` / `latency_injection` /
 *   `value_corruption` / `component_crash` / `duplicate_event` — the five
 *   fault classes AgentChaos enumerates for distributed LLM systems, mapped onto
 *   the retrieval result the companion returns to the agent.
 * - **Fail-closed**: `component_crash` throws a typed `FaultInjectedError`.
 *   The store catches it and *degrades gracefully* (serves the remaining healthy
 *   stores) rather than returning garbage — this is the J1 fail-closed guarantee
 *   made explicit and test-covered here.
 * - **Registered**: `registerFaultExperiment` reuses the §38
 *   `registerExperimentManifest` chain, so a fault scenario is a *registered*
 *   experiment, consistent with every other published claim.
 *
 * Honesty note: the codebase had no pre-existing J1 event-driven-architecture
 * fault-injection framework. This harness lands on the `memory-biomimetic`
 * §38 intervention scaffolding as a *reproducible instantiation* of the J1-C5
 * methodology — it perturbs retrieval results, it does not (yet) inject faults
 * into the event bus / scheduler that J1 describes. That gap is declared in
 * J1/P1, not hidden.
 */

import type { CandidateKind, ScoredCandidate } from './types'

import { fnv1a } from './contracts'
import { buildExperimentManifest, registerExperimentManifest } from './experiment'
import { interventionRng } from './intervention'

/** AgentChaos fault taxonomy, mapped onto the retrieval result. */
export type FaultKind
  = | 'message_drop' // a retrieved item (message/event) is lost in transit
    | 'latency_injection' // delivery is slowed (modelled, not a real sleep)
    | 'value_corruption' // a payload arrives corrupted / garbled
    | 'component_crash' // a backing store crashes → exercise fail-closed
    | 'duplicate_event' // the same event is delivered more than once

export interface FaultInjectionConfig {
  /** Master switch. Default false → harness is a no-op. */
  enabled: boolean
  /** Which fault class to inject. */
  kind: FaultKind
  /**
   * Target of the fault.
   * - For `component_crash`: the `CandidateKind` whose store "crashed"
   *   (e.g. `'fact'`); if omitted, the lexicographically-first kind present
   *   is chosen (deterministic).
   * - For other kinds: an optional substring matched against candidate ids;
   *   if omitted, all candidates are eligible.
   */
  target?: CandidateKind | string
  /** Fraction of eligible candidates perturbed, in [0,1]. */
  rate: number
  /** Fixed seed (§38 reproducibility). Drives `interventionRng`. */
  seed: number
  /** Max modelled latency for `latency_injection` (ms). Default 500. */
  maxLatencyMs?: number
}

export const DEFAULT_FAULT_INJECTION: FaultInjectionConfig = {
  enabled: false,
  kind: 'message_drop',
  rate: 0.2,
  seed: 0,
  maxLatencyMs: 500,
}

export interface FaultReport {
  kind: FaultKind
  seed: number
  /** Number of candidates actually perturbed. */
  applied: number
  /** Total eligible candidates considered. */
  total: number
  /** Modelled latency for `latency_injection` (ms). */
  latencyMs?: number
  /** For `component_crash`: which component was removed. */
  crashedComponent?: CandidateKind
  detail: string
}

/**
 * Thrown by `component_crash`. The store catches this and degrades gracefully
 * (drops the crashed component), turning a fault into a fail-closed path rather
 * than a crash that poisons the returned result.
 */
export class FaultInjectedError extends Error {
  constructor(
    public readonly component: CandidateKind,
    public readonly report: FaultReport,
  ) {
    super(`fault-injection: component "${component}" crashed (fail-closed engaged)`)
    this.name = 'FaultInjectedError'
  }
}

const CANDIDATE_KINDS: CandidateKind[] = ['episode', 'fact', 'procedural', 'working']

/**
 * Deterministic fault injector. Pure with respect to (config, candidate list):
 * given the same inputs it always produces the same output, because candidate
 * selection is drawn from `interventionRng(seed)` in a stable (id-sorted) order.
 */
export class FaultInjector {
  constructor(private readonly config: FaultInjectionConfig) {}

  /**
   * Apply the configured fault to a candidate list (the set the agent receives).
   * Returns the (possibly perturbed) list plus a machine-readable report.
   * For `component_crash` this THROWS {@link FaultInjectedError} so the caller
   * can exercise its fail-closed path.
   */
  apply<C extends ScoredCandidate>(candidates: C[]): { candidates: C[], report: FaultReport } {
    const eligible = this.eligible(candidates)
    const total = eligible.length

    switch (this.config.kind) {
      case 'message_drop':
        return this.dropMessages(candidates, eligible)
      case 'duplicate_event':
        return this.duplicateEvents(candidates, eligible)
      case 'value_corruption':
        return this.corruptValues(candidates, eligible)
      case 'latency_injection':
        return this.injectLatency(candidates, total)
      case 'component_crash':
        return this.crashComponent(candidates)
      default: {
        const _exhaustive: never = this.config.kind
        throw new Error(`unknown fault kind: ${String(_exhaustive)}`)
      }
    }
  }

  /** Candidates eligible for per-item faults (subject to optional id substring). */
  private eligible<C extends ScoredCandidate>(candidates: C[]): C[] {
    const t = this.config.target
    if (typeof t === 'string' && t.length > 0 && !CANDIDATE_KINDS.includes(t as CandidateKind)) {
      return candidates.filter(c => c.id.includes(t))
    }
    return candidates
  }

  /** Stable (id-sorted) draw order → reproducible selection independent of input order. */
  private drawSelections(eligible: ScoredCandidate[]): Set<string> {
    const rng = interventionRng(this.config.seed)
    const ordered = [...eligible].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))
    const selected = new Set<string>()
    for (const c of ordered) {
      if (rng() < this.config.rate)
        selected.add(c.id)
    }
    return selected
  }

  private dropMessages<C extends ScoredCandidate>(
    candidates: C[],
    eligible: C[],
  ): { candidates: C[], report: FaultReport } {
    const drop = this.drawSelections(eligible)
    const kept = candidates.filter(c => !drop.has(c.id))
    return {
      candidates: kept,
      report: {
        kind: 'message_drop',
        seed: this.config.seed,
        applied: drop.size,
        total: eligible.length,
        detail: `dropped ${drop.size}/${eligible.length} candidates (rate=${this.config.rate})`,
      },
    }
  }

  private duplicateEvents<C extends ScoredCandidate>(
    candidates: C[],
    eligible: C[],
  ): { candidates: C[], report: FaultReport } {
    const dup = this.drawSelections(eligible)
    const extra: C[] = candidates
      .filter(c => dup.has(c.id))
      .map((c) => {
        // deterministic unique id: hash the original id so duplicates are
        // distinguishable yet reproducible.
        const suffix = fnv1a(`${this.config.seed}:${c.id}`).slice(0, 8)
        return { ...c, id: `${c.id}:dup:${suffix}` }
      })
    return {
      candidates: [...candidates, ...extra],
      report: {
        kind: 'duplicate_event',
        seed: this.config.seed,
        applied: dup.size,
        total: eligible.length,
        detail: `duplicated ${dup.size}/${eligible.length} candidates`,
      },
    }
  }

  private corruptValues<C extends ScoredCandidate>(
    candidates: C[],
    eligible: C[],
  ): { candidates: C[], report: FaultReport } {
    const corrupt = this.drawSelections(eligible)
    const out = candidates.map((c) => {
      if (!corrupt.has(c.id))
        return c
      // Deterministic corruption: reverse the payload. The downstream consumer
      // must handle a garbled value gracefully (this is the point of the fault).
      return { ...c, content: c.content.split('').reverse().join('') }
    })
    return {
      candidates: out,
      report: {
        kind: 'value_corruption',
        seed: this.config.seed,
        applied: corrupt.size,
        total: eligible.length,
        detail: `corrupted ${corrupt.size}/${eligible.length} payloads`,
      },
    }
  }

  private injectLatency<C extends ScoredCandidate>(
    candidates: C[],
    total: number,
  ): { candidates: C[], report: FaultReport } {
    const maxLat = this.config.maxLatencyMs ?? 500
    // Deterministic modelled latency in [0, maxLat).
    const rng = interventionRng(this.config.seed)
    const latencyMs = Math.floor(rng() * maxLat)
    return {
      // candidates are NOT mutated — latency is a delivery property, modelled.
      candidates,
      report: {
        kind: 'latency_injection',
        seed: this.config.seed,
        applied: total,
        total,
        latencyMs,
        detail: `modelled ${latencyMs}ms delivery latency (not a real sleep)`,
      },
    }
  }

  private crashComponent<C extends ScoredCandidate>(
    candidates: C[],
  ): { candidates: C[], report: FaultReport } {
    const t = this.config.target
    let component: CandidateKind
    if (t && CANDIDATE_KINDS.includes(t as CandidateKind)) {
      component = t as CandidateKind
    }
    else {
      // deterministic fallback: lexicographically-first kind actually present.
      const present = CANDIDATE_KINDS.filter(k => candidates.some(c => c.kind === k))
      if (present.length === 0)
        throw new Error('component_crash: no candidates to crash')
      component = present[0]
    }
    const report: FaultReport = {
      kind: 'component_crash',
      seed: this.config.seed,
      applied: candidates.filter(c => c.kind === component).length,
      total: candidates.length,
      crashedComponent: component,
      detail: `component "${component}" crashed; store must serve remaining stores`,
    }
    throw new FaultInjectedError(component, report)
  }
}

export interface RegisterFaultOptions {
  seed?: number
  metrics?: string[]
  /** registry path; defaults to the committed §38 registry. */
  registryPath?: string
}

/**
 * Register a fault scenario as a §38 `ExperimentManifest` so a robustness claim
 * is *registered* and reproducible, on the same chain as every other experiment.
 */
export function registerFaultExperiment(
  config: FaultInjectionConfig,
  opts: RegisterFaultOptions = {},
): { manifest: ReturnType<typeof buildExperimentManifest> } {
  const seed = config.seed ?? 0
  const manifest = buildExperimentManifest({
    id: `fault:${config.kind}`,
    name: `Fault injection (${config.kind})`,
    seed,
    conditions: [{
      name: config.kind,
      description: 'AgentChaos-style fault injected into the memory-retrieval result (J1-C5).',
      params: {
        kind: config.kind,
        target: config.target ?? null,
        rate: config.rate,
        seed,
        maxLatencyMs: config.maxLatencyMs ?? 500,
      },
    }],
    metrics: opts.metrics ?? ['fault.kind', 'fault.rate', 'fault.applied'],
    notes: `§38/J1-C5 fault-injection harness (AgentChaos taxonomy). Opt-in, default-off, deterministic via interventionRng(seed).`,
  })
  registerExperimentManifest(manifest, opts.registryPath)
  return { manifest }
}
