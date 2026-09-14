import type {
  ExecutionOutcome,
  SkillDomain,
  SkillLibraryMetrics,
  SkillRecord,
  TwoByTwoCell,
} from '@proj-aijade/skill-forge-store'

import type { SkillPackage, SkillRegistry } from './types'

import { computeMetrics, computeTwoByTwo } from '@proj-aijade/skill-forge-store'

/**
 * The legacy registry was a `Map<string, SkillPackage>` with add-only
 * semantics. It could answer "how many skills exist?" but never "how many of
 * them are any good?" — because nothing recorded whether a skill was ever used
 * or, once used, whether it worked.
 *
 * This version keeps the synchronous legacy surface (so `agent-skill-forge` and
 * `agent-capabilities` keep compiling and running unchanged) while also
 * maintaining a parallel {@link SkillRecord} mirror. The mirror is what makes
 * RQ-C measurable: precision and the self-verification 2×2 fall out of it for
 * free, computed synchronously so no async plumbing reaches the hot path.
 *
 * Persistence is deliberately out of scope here — the mirror is in-memory so the
 * sync API stays synchronous. For a durable, JSONL-backed library use
 * `@proj-aijade/skill-forge-store`'s `createSkillRegistry` directly (identical
 * maths, async, file-backed).
 */
export interface MeasuredSkillRegistry extends SkillRegistry {
  /** Record that the skill was actually invoked and what the environment said. */
  recordExecution: (name: string, outcome: ExecutionOutcome) => void
  /** Attach the LLM's own verdict at creation time (the 2×2 predictor). */
  setSelfVerification: (name: string, verdict: 'pass' | 'fail', opts?: { score?: number, rationale?: string, model?: string }) => void
  /** Retire a skill from the active set with a reason. */
  retire: (name: string, reason: 'low-precision' | 'superseded' | 'self-rejected' | 'manual') => void
  /** Library-level metrics (RQ-C). Rates are NaN when a denominator is empty. */
  metrics: () => SkillLibraryMetrics
  /** 2×2 contingency: oracle-available × self-verification-on. */
  twoByTwo: () => TwoByTwoCell[]
  /** Retire every active skill whose precision fell below `threshold`. */
  pruneLowPrecision: (threshold: number, minCalls?: number) => string[]
}

export interface MeasuredSkillRegistryOptions {
  /** Domain stamped on every record — drives the 2×2. Default `'synthetic'`. */
  domain?: SkillDomain
  /** Override clock (tests / reproducible runs). */
  now?: () => number
}

export function createSkillRegistry(
  initial: SkillPackage[] = [],
  options: MeasuredSkillRegistryOptions = {},
): MeasuredSkillRegistry {
  const map = new Map<string, SkillPackage>()
  const records = new Map<string, SkillRecord>()
  const domain = options.domain ?? 'synthetic'
  const now = options.now ?? (() => Date.now())

  function toRecord(pkg: SkillPackage): SkillRecord {
    return {
      skillId: pkg.frontmatter.name,
      name: pkg.frontmatter.name,
      createdAt: pkg.createdAt,
      domain,
      callCount: 0,
      successCount: 0,
      failureCount: 0,
      status: 'active',
      ...(pkg.body ? { body: JSON.stringify(pkg.body) } : {}),
    }
  }

  // Seed from initial skills.
  for (const pkg of initial) {
    map.set(pkg.frontmatter.name, pkg)
    records.set(pkg.frontmatter.name, toRecord(pkg))
  }

  return {
    add(pkg) {
      map.set(pkg.frontmatter.name, pkg)
      if (!records.has(pkg.frontmatter.name))
        records.set(pkg.frontmatter.name, toRecord(pkg))
    },
    get(name) {
      return map.get(name)
    },
    has(name) {
      return map.has(name)
    },
    list() {
      return [...map.values()]
    },
    remove(name) {
      const had = map.delete(name)
      records.delete(name)
      return had
    },

    recordExecution(name, outcome) {
      const r = records.get(name)
      if (!r)
        return
      const callCount = r.callCount + 1
      const successCount = r.successCount + (outcome.ok ? 1 : 0)
      const failureCount = r.failureCount + (outcome.ok ? 0 : 1)
      const ts = now()
      const retired = callCount >= 3 && successCount === 0 && r.status === 'active'
      records.set(name, {
        ...r,
        callCount,
        successCount,
        failureCount,
        lastUsedAt: ts,
        execution: {
          ok: outcome.ok,
          executedAt: ts,
          attempt: callCount,
          ...(outcome.detail ? { detail: outcome.detail } : {}),
          ...(outcome.durationMs !== undefined ? { durationMs: outcome.durationMs } : {}),
        },
        ...(retired
          ? { status: 'retired' as const, retirementReason: 'low-precision' as const, retiredAt: ts }
          : {}),
      })
    },

    setSelfVerification(name, verdict, opts) {
      const r = records.get(name)
      if (!r)
        return
      records.set(name, {
        ...r,
        selfVerification: {
          verdict,
          enabled: true,
          ...(opts?.score !== undefined ? { score: opts.score } : {}),
          ...(opts?.rationale ? { rationale: opts.rationale } : {}),
          ...(opts?.model ? { model: opts.model } : {}),
        },
        ...(verdict === 'fail' && r.status === 'active'
          ? { status: 'rejected' as const, retirementReason: 'self-rejected' as const, retiredAt: now() }
          : {}),
      })
    },

    retire(name, reason) {
      const r = records.get(name)
      if (!r)
        return
      records.set(name, {
        ...r,
        status: reason === 'self-rejected' ? 'rejected' : 'retired',
        retirementReason: reason,
        retiredAt: now(),
      })
    },

    metrics() {
      return computeMetrics([...records.values()])
    },

    twoByTwo() {
      return computeTwoByTwo([...records.values()])
    },

    pruneLowPrecision(threshold, minCalls = 3) {
      const doomed: string[] = []
      const ts = now()
      for (const r of records.values()) {
        if (r.status === 'active' && r.callCount >= minCalls && (r.successCount / r.callCount) < threshold) {
          records.set(r.skillId, { ...r, status: 'retired', retirementReason: 'low-precision', retiredAt: ts })
          doomed.push(r.skillId)
        }
      }
      return doomed
    },
  }
}
