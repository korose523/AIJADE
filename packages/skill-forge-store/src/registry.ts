/**
 * A skill registry that can actually be measured.
 *
 * ## What changes relative to `packages/agent-skill-forge/src/registry.ts`
 *
 * | Concern | Upstream | Here |
 * |---|---|---|
 * | Storage | `new Map()` — lost on restart | Pluggable `SkillStore`, JSONL by default |
 * | Lifecycle | add-only | `active` → `retired` / `rejected` |
 * | Usage | never recorded | `callCount` / `successCount` / `failureCount` |
 * | Ground truth | none | `recordExecution()` captures the environment's verdict |
 * | Metrics | none | `metrics()` and `twoByTwo()` |
 *
 * ## Why retirement matters for the science
 *
 * An add-only library can only ever support a quantity of the form
 * "how many skills were produced". Every interesting question — is the library
 * getting *better*, does self-verification *help*, do bad skills get *reused* —
 * needs a denominator that only exists if skills can also leave. Retirement is
 * not housekeeping; it is what turns a log into an experiment.
 */

import type { SkillStore } from './storage'
import type { ExecutionOutcome, SkillDomain, SkillLibraryMetrics, SkillRecord, TwoByTwoCell } from './types'

import {
  createMemorySkillStore,

} from './storage'
import {
  computeMetrics,
  computeTwoByTwo,

  hasEnvironmentalOracle,

} from './types'

export interface CreateSkillOptions {
  name: string
  domain: SkillDomain
  body?: string
  trigger?: SkillRecord['trigger']
  /** The LLM's verdict at creation time, if self-verification is enabled. */
  selfVerification?: {
    verdict: 'pass' | 'fail'
    score?: number
    rationale?: string
    model?: string
    enabled: boolean
  }
  /**
   * Whether the environment's verdicts should be fed back into this skill's
   * lifecycle (driving retirement / pruning). Optional and backward compatible:
   * when omitted, downstream functions treat it as disabled
   * (`r.envFeedback?.enabled ?? false`).
   */
  envFeedback?: {
    enabled: boolean
    appliedAt?: number
  }
  metadata?: Record<string, unknown>
  /** Override id generation (tests / reproducible runs). */
  skillId?: string
  /** Override clock (tests). */
  now?: () => number
}

export interface SkillRegistry {
  create: (options: CreateSkillOptions) => Promise<SkillRecord>
  get: (skillId: string) => Promise<SkillRecord | undefined>
  all: () => Promise<SkillRecord[]>
  /** Attach or update the LLM's self-assessment. */
  setSelfVerification: (
    skillId: string,
    verdict: 'pass' | 'fail',
    extra?: { score?: number, rationale?: string, model?: string },
  ) => Promise<SkillRecord>
  /**
   * Enable or disable the environmental feedback loop for a skill. Backward
   * compatible: has no effect on skills already retired/rejected.
   */
  setEnvFeedback: (skillId: string, enabled: boolean) => Promise<SkillRecord>
  /**
   * Record that the skill was actually invoked, and what the environment said.
   * This is the ground-truth half of RQ-C.
   */
  recordExecution: (skillId: string, outcome: ExecutionOutcome) => Promise<SkillRecord>
  /** Remove a skill from the active set, with a reason. */
  retire: (
    skillId: string,
    reason: NonNullable<SkillRecord['retirementReason']>,
  ) => Promise<SkillRecord>
  metrics: () => Promise<SkillLibraryMetrics>
  twoByTwo: () => Promise<TwoByTwoCell[]>
  /**
   * Retire every active skill whose precision has fallen below `threshold`.
   * Requires `minCalls` before judging, so a skill tried once and failing once
   * is not condemned prematurely.
   */
  pruneLowPrecision: (threshold: number, minCalls?: number) => Promise<SkillRecord[]>
}

export interface SkillRegistryOptions {
  store?: SkillStore
  now?: () => number
}

export function createSkillRegistry(options: SkillRegistryOptions = {}): SkillRegistry {
  const store = options.store ?? createMemorySkillStore()
  const now = options.now ?? (() => Date.now())

  async function mutate(
    skillId: string,
    fn: (record: SkillRecord) => SkillRecord,
  ): Promise<SkillRecord> {
    const existing = await store.get(skillId)
    if (!existing)
      throw new Error(`Skill ${skillId} not found`)
    const updated = fn(existing)
    await store.upsert(updated)
    return updated
  }

  return {
    async create(opts) {
      const id = opts.skillId ?? newId()
      // A skill generated with self-verification disabled is the control cell
      // of the 2×2; record that explicitly rather than leaving it undefined,
      // otherwise "no verdict" and "verification was off" become confounded.
      const record: SkillRecord = {
        skillId: id,
        name: opts.name,
        createdAt: now(),
        domain: opts.domain,
        callCount: 0,
        successCount: 0,
        failureCount: 0,
        status: 'active',
        ...(opts.trigger ? { trigger: opts.trigger } : {}),
        ...(opts.selfVerification ? { selfVerification: opts.selfVerification } : {}),
        ...(opts.envFeedback ? { envFeedback: opts.envFeedback } : {}),
        ...(opts.body !== undefined ? { body: opts.body } : {}),
        ...(opts.metadata ? { metadata: opts.metadata } : {}),
      }
      await store.upsert(record)
      return record
    },

    get: store.get,
    all: store.all,

    async setSelfVerification(skillId, verdict, extra) {
      return mutate(skillId, (r) => {
        // Rejecting on self-verification failure is the behaviour that makes
        // `rejected` a meaningful count rather than always zero.
        return {
          ...r,
          selfVerification: {
            verdict,
            enabled: true,
            ...(extra?.score !== undefined ? { score: extra.score } : {}),
            ...(extra?.rationale ? { rationale: extra.rationale } : {}),
            ...(extra?.model ? { model: extra.model } : {}),
          },
          ...(verdict === 'fail' && r.status === 'active'
            ? { status: 'rejected' as const, retirementReason: 'self-rejected' as const, retiredAt: now() }
            : {}),
        }
      })
    },

    async recordExecution(skillId, outcome) {
      return mutate(skillId, (r) => {
        const callCount = r.callCount + 1
        const successCount = r.successCount + (outcome.ok ? 1 : 0)
        const failureCount = r.failureCount + (outcome.ok ? 0 : 1)
        const ts = now()

        return {
          ...r,
          callCount,
          successCount,
          failureCount,
          lastUsedAt: ts,
          // Keep only the latest verdict: the counters carry the history, and
          // storing every attempt here would bloat the record. Use
          // research-telemetry's per-turn log if you need the full trace.
          execution: {
            ok: outcome.ok,
            executedAt: ts,
            attempt: callCount,
            ...(outcome.detail ? { detail: outcome.detail } : {}),
            ...(outcome.durationMs !== undefined ? { durationMs: outcome.durationMs } : {}),
          },
          // A skill that keeps failing is not evidence of learning; it is
          // evidence of a bad skill. Refusing to reuse it is what makes
          // precision rise over time instead of staying flat.
          //
          // This environmental retirement is gated on `envFeedback.enabled`: the
          // feedback loop is exactly what retires bad skills. When envFeedback is
          // OFF the environment's verdicts are NOT fed back into the lifecycle,
          // so a bad skill is reused forever (precision stays flat). Legacy
          // callers that never set `envFeedback` keep the old behaviour via the
          // `?? true` default, so this is backward compatible.
          ...(callCount >= 3 && successCount === 0 && r.status === 'active' && (r.envFeedback?.enabled ?? true)
            ? { status: 'retired' as const, retirementReason: 'low-precision' as const, retiredAt: ts }
            : {}),
        }
      })
    },

    async retire(skillId, reason) {
      return mutate(skillId, r => ({
        ...r,
        status: reason === 'self-rejected' ? 'rejected' : 'retired',
        retirementReason: reason,
        retiredAt: now(),
      }))
    },

    async setEnvFeedback(skillId, enabled) {
      return mutate(skillId, r => ({
        ...r,
        envFeedback: {
          enabled,
          ...(r.envFeedback?.appliedAt ? { appliedAt: r.envFeedback.appliedAt } : {}),
        },
      }))
    },

    async metrics() {
      return computeMetrics(await store.all())
    },

    async twoByTwo() {
      return computeTwoByTwo(await store.all())
    },

    async pruneLowPrecision(threshold, minCalls = 3) {
      const all = await store.all()
      const doomed = all.filter(
        r => r.status === 'active'
          && r.callCount >= minCalls
          && (r.successCount / r.callCount) < threshold,
      )
      const ts = now()
      for (const r of doomed) {
        await store.upsert({
          ...r,
          status: 'retired',
          retirementReason: 'low-precision',
          retiredAt: ts,
        })
      }
      return doomed
    },
  }
}

function newId(): string {
  const g = globalThis as { crypto?: { randomUUID?: () => string } }
  if (g.crypto?.randomUUID)
    return g.crypto.randomUUID()
  return `sk-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * Guard used by the harness: a skill must not be counted as "ground truth
 * available" unless its domain actually provides an oracle.
 *
 * Silently treating conversation-domain outcomes as ground truth would be the
 * single easiest way to invalidate the whole 2×2.
 */
export function assertOracleAvailable(record: SkillRecord): void {
  if (!hasEnvironmentalOracle(record.domain)) {
    throw new Error(
      `Skill ${record.skillId} is in domain "${record.domain}", which has no `
      + 'environmental oracle. Do not record an execution verdict for it — '
      + 'that would fabricate ground truth for the 2×2 control cell.',
    )
  }
}
