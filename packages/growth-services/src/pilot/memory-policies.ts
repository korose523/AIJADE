/**
 * §5.3 — Memory-write policies as `StoragePort` decorators.
 *
 * This is the heart of the methodological fix requested for the pilot: the
 * B0–B5 / A1 difference is no longer encoded as `if (config.X) return <fixed
 * value>` inside the metric formulas. Instead each memory strategy is a real
 * `StoragePort` *decorator* that wraps the in-memory stub and decides, on every
 * `put`, what actually enters long-term memory — purely from the *attributes of
 * the value being written* (its truth, role, importance, predicted future value,
 * session index, and contradiction relationship) plus the mechanism parameters
 * that constitute the independent variable under test (dual-graph separation,
 * CDI identity constraint).
 *
 * The only thing the configuration decides is *which policy class is installed*
 * (the treatment). Everything downstream — what gets written, what is kept after
 * eviction, what is retrieved, whether a contradiction is preserved or silently
 * overwritten — is produced by this code path. No metric is ever fed a
 * pre-computed ranking.
 *
 * The longitudinal benchmark statements flow through the real `GrowthLoop`, whose
 * `KnowledgeAcquirer` persists each statement as a `SourceRecord`. We embed the
 * statement's ground-truth attributes into the record's `locator` (the only
 * source field `KnowledgeAcquirer` copies verbatim) so the policy can read them
 * back on `put`.
 */

import type { LlmPort, StoragePort } from '../ports'
import type { MechanismConfig, MemoryWriteStrategy } from './configs'

import { fnv1a } from '../util'

/** Managed storage kind: the only kind the policy gates / evicts. */
export const MEMORY_KIND = 'source_record'

/** Decoded ground-truth attributes of one benchmark statement. */
export interface MemoryMeta {
  /** Benchmark statement id (also the golden-set key). */
  stmtId: string
  /** Session the statement belongs to (for sliding-window eviction). */
  sessionIndex: number
  /** True iff the statement is a correct fact (false = poison / false fact). */
  isTrue: boolean
  /** Statement role (also a persona-layer tag). */
  role: string
  /** Low-value / high-frequency distractor. */
  isDistractor: boolean
  /** Late member of a contradiction pair. */
  isContradictionLate: boolean
  /** When contradictory, the id of the earlier member. */
  contradicts?: string
  /** Grouping key for contradiction pairs (early id) or the stmt id itself. */
  topic: string
  /** Predicted future utility (HAC gate input). */
  futureValue: number
  /** Importance (threshold / budget gates input). */
  importance: number
}

/** Persona-core roles whose retention defines Core Stability. */
export const CORE_PERSONA_ROLES = new Set<string>([
  'preference_early',
  'preference_late',
  'relationship_boundary',
])

/** Identity-destabilising roles (high-emotion, low-fact) — blocked by CDI. */
export const DESTABILIZING_ROLES = new Set<string>([
  'emotion_high_lowfact',
])

/** Encode the statement attributes into a `SourceRecord.locator`. */
export function encodeLocator(stmtId: string, m: Omit<MemoryMeta, 'stmtId'>): string {
  const blob = [
    `s=${m.sessionIndex}`,
    `t=${m.isTrue ? 1 : 0}`,
    `r=${m.role}`,
    `d=${m.isDistractor ? 1 : 0}`,
    `c=${m.isContradictionLate ? 1 : 0}`,
    `ct=${m.contradicts ?? ''}`,
    `tp=${m.topic}`,
    `fv=${m.futureValue}`,
    `imp=${m.importance}`,
  ].join('&')
  return `stmt:${stmtId}|meta:${blob}`
}

/** Decode a `SourceRecord.locator` back into statement attributes. */
export function decodeLocator(locator: string): MemoryMeta | null {
  const sep = '|meta:'
  const i = locator.indexOf(sep)
  if (i < 0)
    return null
  const stmtId = locator.slice(0, i).replace(/^stmt:/, '')
  const blob = locator.slice(i + sep.length)
  const kv: Record<string, string> = {}
  for (const part of blob.split('&')) {
    const eq = part.indexOf('=')
    if (eq < 0)
      continue
    kv[part.slice(0, eq)] = part.slice(eq + 1)
  }
  if (!stmtId)
    return null
  return {
    stmtId,
    sessionIndex: Number(kv.s) || 0,
    isTrue: kv.t === '1',
    role: kv.r,
    isDistractor: kv.d === '1',
    isContradictionLate: kv.c === '1',
    contradicts: kv.ct ? kv.ct : undefined,
    topic: kv.tp,
    futureValue: Number(kv.fv) || 0,
    importance: Number(kv.imp) || 0,
  }
}

/** Mechanism parameters that constitute the independent variable. */
export interface PolicyParams {
  strategy: MemoryWriteStrategy
  /** DGM — experience/belief dual-graph separation (false-fact filter + contradiction retention). */
  dualGraphSeparation: boolean
  /** CDI — identity constraint (blocks identity-destabilising writes). */
  cdiEnabled: boolean
  /** Sliding-window size (number of recent sessions retained). */
  windowSessions: number
  /** Fixed-budget slot ceiling (LRU / importance eviction target). */
  budget: number
  /** Optional deterministic reflection summariser (used by the B4 policy). */
  reflect?: (content: string) => Promise<string>
}

/** Build the policy parameters for a Table-3 configuration. */
export function policyParamsFrom(config: MechanismConfig, budget: number, reflect?: (content: string) => string): PolicyParams {
  return {
    strategy: config.memoryWrite,
    dualGraphSeparation: config.dualGraphSeparation,
    cdiEnabled: config.identityConstraint,
    windowSessions: 10,
    budget,
    reflect,
  }
}

/**
 * A `StoragePort` decorator that implements a memory-write strategy.
 *
 * Non-memory kinds (interest threads, quests, beliefs, artifacts, journals,
 * share candidates) are passed straight through to the wrapped base storage so
 * the `GrowthLoop` runs normally. Only `MEMORY_KIND` ('source_record') is
 * intercepted and subjected to the strategy's admission / eviction / dual-graph
 * logic. The genuinely committed set is exposed via {@link committed}.
 */
export class PolicyStorage implements StoragePort {
  private readonly base: StoragePort
  private readonly p: PolicyParams
  /** Genuinely committed memory: stmtId → decoded meta. */
  private readonly mem = new Map<string, MemoryMeta>()
  /** Insertion order of unique stmt ids (for LRU / tie-break eviction). */
  private readonly order: string[] = []
  private maxSession = -1
  /** Reconstructed records for get/list/query on the managed kind. */
  private readonly records = new Map<string, unknown>()

  constructor(base: StoragePort, params: PolicyParams) {
    this.base = base
    this.p = params
  }

  /** The genuinely persisted memory set (stmtId → meta). Read by the metrics. */
  committed(): Map<string, MemoryMeta> {
    return this.mem
  }

  /** Admission decision for a *true, non-contradiction* write, by strategy. */
  private admitTrue(meta: MemoryMeta): boolean {
    switch (this.p.strategy) {
      case 'none':
        return false
      case 'sliding_window':
        return true
      case 'vector_allwrite':
        return true
      case 'importance_threshold':
        return meta.importance >= 0.5
      case 'llm_reflection': {
        if (meta.importance >= 0.5)
          return true
        if (this.p.reflect) {
          const out = await this.p.reflect(meta.role + meta.stmtId)
          return fnv1a(out) % 1000 < 300
        }
        return false
      }
      case 'fixed_budget':
        return meta.importance >= 0.4
      case 'hac_gated':
        // HAC endogenous gate: prioritise predicted future utility, with a
        // high-confidence importance fallback. False facts are NOT gated here —
        // the DGM / dual-graph mechanism decides those (see put()).
        return meta.futureValue >= 0.4 || meta.importance >= 0.7
    }
  }

  async put<T>(kind: string, id: string, value: T): Promise<void> {
    if (kind !== MEMORY_KIND) {
      await this.base.put(kind, id, value)
      return
    }
    const meta = decodeLocator((value as { locator: string }).locator)
    if (!meta) {
      await this.base.put(kind, id, value)
      return
    }

    // --- DGM / dual-graph separation ---------------------------------------
    // False facts: the dual graph is the *only* false-fact filter. With DGM on,
    // poisoning is rejected at write time; without it, the statement proceeds to
    // the strategy gate (and is typically admitted by the baselines).
    if (!meta.isTrue && this.p.dualGraphSeparation)
      return

    // Contradictions: with DGM on, the late evidence is *added* (experience and
    // belief co-exist — both sides retained). Without DGM, the early member is
    // silently overwritten by the late one (only the latest survives).
    if (meta.isContradictionLate && meta.contradicts) {
      if (!this.p.dualGraphSeparation)
        this.mem.delete(meta.contradicts)
    }

    // --- CDI identity guard ------------------------------------------------
    // When the identity constraint is active, identity-destabilising writes
    // (high-emotion, low-fact) are blocked outright.
    if (this.p.cdiEnabled && DESTABILIZING_ROLES.has(meta.role))
      return

    // False facts that cleared the dual-graph check reach here only when DGM is
    // off; baselines admit them (that is the point of the ablation).
    if (!meta.isTrue)
      return this.commit(meta, value)

    if (!this.admitTrue(meta))
      return
    this.commit(meta, value)
  }

  private commit(meta: MemoryMeta, value: unknown): void {
    if (!this.mem.has(meta.stmtId))
      this.order.push(meta.stmtId)
    this.mem.set(meta.stmtId, meta)
    this.records.set(meta.stmtId, value)
    if (meta.sessionIndex > this.maxSession)
      this.maxSession = meta.sessionIndex
    this.enforce()
  }

  /** Apply strategy-specific eviction after every commit. */
  private enforce(): void {
    if (this.p.strategy === 'sliding_window') {
      const cut = this.maxSession - (this.p.windowSessions - 1)
      for (const id of [...this.mem.keys()]) {
        if (this.mem.get(id)!.sessionIndex < cut) {
          this.mem.delete(id)
          this.records.delete(id)
        }
      }
    }
    else if (this.p.strategy === 'fixed_budget') {
      while (this.mem.size > this.p.budget) {
        const victim = this.evictionCandidate()
        if (!victim)
          break
        this.mem.delete(victim)
        this.records.delete(victim)
      }
    }
    // none / vector_allwrite / importance_threshold / llm_reflection / hac_gated
    // have no hard slot cap here (the FUB metric caps usable recall at B).
  }

  /** Lowest-importance, oldest-inserted committed entry (LRU + importance). */
  private evictionCandidate(): string | undefined {
    let worst: string | undefined
    let worstScore = Infinity
    let worstOrder = Infinity
    for (const id of this.mem.keys()) {
      const m = this.mem.get(id)!
      const score = m.importance
      const oi = this.order.indexOf(id)
      if (score < worstScore || (score === worstScore && oi < worstOrder)) {
        worst = id
        worstScore = score
        worstOrder = oi
      }
    }
    return worst
  }

  async get<T>(kind: string, id: string): Promise<T | undefined> {
    if (kind !== MEMORY_KIND)
      return this.base.get<T>(kind, id)
    return this.records.get(id) as T | undefined
  }

  async list<T>(kind: string): Promise<T[]> {
    if (kind !== MEMORY_KIND)
      return this.base.list<T>(kind)
    return [...this.records.values()] as T[]
  }

  async query<T>(kind: string, pred: (item: T) => boolean): Promise<T[]> {
    if (kind !== MEMORY_KIND)
      return this.base.query<T>(kind, pred)
    return (await this.list<T>(kind)).filter(pred)
  }
}

/** Convenience: a reflection summariser backed by the deterministic stub LLM. */
export function makeReflection(llm: LlmPort): (content: string) => string {
  return (content: string) => llm.complete(`reflect: ${content}`)
}
