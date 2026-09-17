import type {
  ExecutionOutcome,
  SkillDomain,
  SkillLibraryMetrics,
  SkillRecord,
  TwoByTwoCell,
} from '@proj-aijade/skill-forge-store'

import type { SkillBody, SkillPackage, SkillRegistry } from './types'

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

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

function toRecord(pkg: SkillPackage, domain: SkillDomain): SkillRecord {
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

function pkgFromRecord(r: SkillRecord): SkillPackage {
  const body = (r.body ? JSON.parse(r.body) as SkillBody : null)
  return {
    frontmatter: { name: r.name, description: '', version: '0.1.0', author: 'AIJADE' },
    body: body ?? { title: r.name, whenToUse: [], procedure: [] },
    createdAt: r.createdAt,
    updatedAt: r.createdAt,
    source: 'hand-authored',
    evolutionLog: [],
  }
}

/**
 * Drop the non-serialisable `module.run` (functions cannot be persisted) so the
 * package survives a JSON round-trip. The rest of `module` (e.g. `tools`) is
 * kept.
 */
function serializablePkg(pkg: SkillPackage): SkillPackage {
  if (!pkg.module)
    return pkg
  const { run: _run, ...rest } = pkg.module
  void _run
  return Object.keys(rest).length ? { ...pkg, module: rest } : { ...pkg, module: undefined }
}

export interface PersistentSkillRegistryOptions {
  /** Full path to the JSONL library file, e.g. `<dir>/skill-library.jsonl`. */
  file: string
  /** Domain stamped on every record (drives the 2×2). Default `'synthetic'`. */
  domain?: SkillDomain
  /** Override clock (tests / reproducible runs). */
  now?: () => number
}

/**
 * A `MeasuredSkillRegistry` that persists to disk (JSONL) so the skill library
 * survives a process restart — fixing the defect where the entire library was a
 * process-local `Map` and every "learned" skill vanished on exit.
 *
 * This is the durability half of `@proj-aijade/skill-forge-store`: it reuses
 * that package's `SkillRecord` data model and its `computeMetrics` /
 * `computeTwoByTwo` maths (identical to the store's own `createSkillRegistry`),
 * but performs the I/O **synchronously** so it satisfies this package's
 * synchronous `SkillRegistry` contract — `add` / `get` / `has` / `list` are
 * consumed synchronously by `SkillForge.register` and the chat bridge's
 * `skillIndexText`. (`skill-forge-store`'s own store is async via
 * `node:fs/promises`, so it cannot back a synchronous registry directly.)
 *
 * On-disk format: one JSON object per line — `{ record: SkillRecord, pkg: SkillPackage }`.
 * The `pkg` half is what lets a fresh instance reconstruct a usable
 * `SkillPackage`; the `record` half is what `computeMetrics` / `computeTwoByTwo`
 * read. The file is rewritten in full on every mutation (cheap for the record
 * volumes of a single participant; swap to SQLite if a study outgrows it — the
 * `SkillRecord` shape is unchanged).
 */
export function createPersistentSkillRegistry(
  initial: SkillPackage[] = [],
  options: PersistentSkillRegistryOptions,
): MeasuredSkillRegistry {
  const { file } = options
  const domain = options.domain ?? 'synthetic'
  const now = options.now ?? (() => Date.now())

  const packages = new Map<string, SkillPackage>()
  const records = new Map<string, SkillRecord>()

  function persist(): void {
    const lines = [...records.values()].map((r) => {
      const pkg = packages.get(r.skillId) ?? pkgFromRecord(r)
      return JSON.stringify({ record: r, pkg: serializablePkg(pkg) })
    })
    mkdirSync(dirname(file), { recursive: true })
    writeFileSync(file, lines.length ? `${lines.join('\n')}\n` : '', 'utf8')
  }

  function load(): void {
    if (!existsSync(file))
      return
    const raw = readFileSync(file, 'utf8')
    for (const line of raw.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed)
        continue
      const parsed = JSON.parse(trimmed) as { record: SkillRecord, pkg?: SkillPackage }
      records.set(parsed.record.skillId, parsed.record)
      packages.set(parsed.record.skillId, parsed.pkg ?? pkgFromRecord(parsed.record))
    }
  }
  load()

  for (const pkg of initial) {
    packages.set(pkg.frontmatter.name, pkg)
    records.set(pkg.frontmatter.name, toRecord(pkg, domain))
  }
  if (initial.length)
    persist()

  return {
    add(pkg) {
      packages.set(pkg.frontmatter.name, pkg)
      records.set(pkg.frontmatter.name, toRecord(pkg, domain))
      persist()
    },
    get(name) {
      return packages.get(name)
    },
    has(name) {
      return packages.has(name)
    },
    list() {
      return [...packages.values()]
    },
    remove(name) {
      const had = packages.delete(name)
      records.delete(name)
      if (had)
        persist()
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
      persist()
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
      persist()
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
      persist()
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
      if (doomed.length)
        persist()
      return doomed
    },
  }
}
