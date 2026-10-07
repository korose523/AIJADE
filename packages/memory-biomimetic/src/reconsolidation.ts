import type { SemanticFact } from './types'

/**
 * Reconsolidation — the biological "destabilize → restabilize" update cycle that
 * fires when a memory is retrieved (Nader et al., 2000). This module is a
 * SELF-CONTAINED, OPT-IN implementation: it is a no-op unless explicitly enabled
 * via {@link ReconsolidationConfig.enabled}, so it never changes existing product
 * behaviour on the default path.
 *
 * It mirrors the design of mnemos' MutableRAG and REALM's retrieval-driven
 * reconsolidation, which the AIJADE paper J4 cites (§Limitations) as mechanisms
 * our system currently lacks. This module is the first step toward closing that
 * gap, kept behind a config flag so the default memory path is untouched.
 *
 * Design choices:
 * - A retrieved fact enters a *labile* window (default 60 min, mirroring biology).
 * - A pluggable {@link ContradictionDetector} decides whether a candidate
 *   contradicts or merely updates the stored fact. The default {@link NoOpDetector}
 *   never mutates — a real (e.g. LLM-based) detector is injected to enable updates.
 * - Updates are versioned in place with an audit trail; a cooldown prevents
 *   thrashing; `maxVersions` caps history.
 */

export interface ReconsolidationConfig {
  /** Master switch. Default false → entire engine is a no-op. */
  enabled: boolean
  /** How long a retrieved fact stays labile (ms). */
  labileWindowMs: number
  /** Minimum gap between two applied updates to the same fact (ms). */
  cooldownMs: number
  /** Max applied versions per fact (history cap). */
  maxVersions: number
}

export const DEFAULT_RECONSOLIDATION: ReconsolidationConfig = {
  enabled: false,
  labileWindowMs: 60 * 60 * 1000, // 60 min — biological lability window
  cooldownMs: 60 * 1000, // 60 s — prevents thrashing
  maxVersions: 10,
}

export type ReconsolidationKind = 'contradiction' | 'update' | 'none'

export interface ReconsolidationVerdict {
  kind: ReconsolidationKind
  confidence: number
  /** New content to store when kind !== 'none'. */
  proposedContent?: string
  /** New confidence when kind !== 'none'. */
  proposedConfidence?: number
}

export interface ReconsolidationEvent {
  timestamp: number
  factId: string
  fromVersion: number
  toVersion: number
  kind: ReconsolidationKind
  summary: string
}

export interface ReconsolidatedFact extends SemanticFact {
  reconsolidation?: { version: number, lastUpdatedAt: number }
}

export interface ContradictionDetector {
  evaluate: (existing: SemanticFact, candidate: string) => ReconsolidationVerdict
}

/**
 * Safe default detector: always returns `none`. A retrieved fact is never
 * mutated unless a real detector (e.g. an LLM that detects contradictions) is
 * injected. This keeps the module harmless on the default path.
 */
export const NoOpDetector: ContradictionDetector = {
  evaluate: () => ({ kind: 'none', confidence: 0 }),
}

export class ReconsolidationEngine {
  private labile = new Map<string, number>()
  private lastApplied = new Map<string, number>()
  private versions = new Map<string, number>()
  private audit: ReconsolidationEvent[] = []

  constructor(
    private readonly config: ReconsolidationConfig = DEFAULT_RECONSOLIDATION,
    private readonly detector: ContradictionDetector = NoOpDetector,
  ) {}

  /** Mark a fact labile after retrieval. No-op when disabled. */
  markLabile(factId: string, now: number): void {
    if (!this.config.enabled)
      return
    this.labile.set(factId, now + this.config.labileWindowMs)
  }

  /** True only while the fact is inside its lability window. */
  isLabile(factId: string, now: number): boolean {
    const until = this.labile.get(factId)
    if (until === undefined)
      return false
    if (now > until) {
      this.labile.delete(factId)
      return false
    }
    return true
  }

  getAuditTrail(): readonly ReconsolidationEvent[] {
    return this.audit
  }

  /**
   * Apply a reconsolidation step to a retrieved fact. Acts only when ALL hold:
   * engine enabled, fact is currently labile, detector returns a non-`none`
   * verdict, cooldown elapsed, and `maxVersions` not exceeded.
   * Returns the (possibly updated) fact and the audit event (null if no change).
   */
  reconsolidate(
    fact: SemanticFact,
    candidate: string,
    now: number,
  ): { fact: ReconsolidatedFact, event: ReconsolidationEvent | null } {
    if (!this.config.enabled)
      return { fact, event: null }
    if (!this.isLabile(fact.id, now))
      return { fact, event: null }

    const verdict = this.detector.evaluate(fact, candidate)
    if (verdict.kind === 'none')
      return { fact, event: null }

    const last = this.lastApplied.get(fact.id)
    if (last !== undefined && now - last < this.config.cooldownMs)
      return { fact, event: null } // cooldown — avoid thrashing

    const fromVersion = this.versions.get(fact.id) ?? 0
    if (fromVersion >= this.config.maxVersions)
      return { fact, event: null }

    const toVersion = fromVersion + 1
    this.versions.set(fact.id, toVersion)
    this.lastApplied.set(fact.id, now)

    const updated: ReconsolidatedFact = {
      ...fact,
      content: verdict.proposedContent ?? fact.content,
      confidence: verdict.proposedConfidence ?? fact.confidence,
      reconsolidation: { version: toVersion, lastUpdatedAt: now },
    }
    const event: ReconsolidationEvent = {
      timestamp: now,
      factId: fact.id,
      fromVersion,
      toVersion,
      kind: verdict.kind,
      summary: `${verdict.kind} applied (conf ${fact.confidence}→${updated.confidence})`,
    }
    this.audit.push(event)
    return { fact: updated, event }
  }
}
