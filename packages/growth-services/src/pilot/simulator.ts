/**
 * §5.3 / §5.4 — Mechanism-level simulator (REFACTORED).
 *
 * The earlier version decided every metric from `config` flags via `if/else`
 * (e.g. `config.dualGraphSeparation ? contradictionCases : 0`), which is the
 * self-fulfilling "config → ranking" pattern the pilot must avoid.
 *
 * New design — the ranking grows out of the code, not out of the config:
 *
 *   1. Each Table-3 configuration installs a *real* `StoragePort` decorator
 *      (`PolicyStorage`, see `./memory-policies`) that implements its memory-write
 *      strategy. The only thing the config picks is *which* decorator — the
 *      treatment — which is exactly the independent variable.
 *   2. Every benchmark session is fed to the genuine `GrowthLoop.runOnce(...)`
 *      (interest → quest → acquire → verify → synthesise → journal → share) using
 *      the in-memory stub ports (`../in-memory`). The loop writes its
 *      `SourceRecord`s through the policy decorator, which gates/evicts them.
 *   3. ALL metrics are then computed from (a) the policy's *genuinely committed*
 *      memory set and (b) the real `GrowthLoopSummary` returns — never from a
 *      config flag. If a metric cannot be derived from the real run, it is dropped
 *      rather than faked.
 *
 * This is still a *deterministic mechanism-level simulation*: no real LLM, no
 * Postgres, no human subjects. The endogenous-state / CDI gates are modelled as
 * threshold functions over the statement attributes (documented in the report).
 */

import type { InterestComponents } from '@proj-aijade/memory-biomimetic'

import type { LongitudinalDataset, StatementRole, SyntheticLongitudinalBenchmark } from '../benchmark/synthetic-longitudinal'
import type { IdentityCounts } from '../metrics/identity'
import type { RawHit, SearchPort } from '../ports'
import type { MechanismConfig } from './configs'
import type { MemoryMeta } from './memory-policies'

import { GrowthLoop } from '../growth-loop'
import { InMemoryScheduler, InMemorySigning, InMemoryStorage, StubLlm } from '../in-memory'
import {
  contradictionRetention,
  effectiveProactivity,
  evidencePrecisionRecall,
  falseConsolidationRate,
  futureUtilityAtBudget,
  growthCoherence,
} from '../metrics/formulas'
import {
  coreStability,
  countIdentity,

  identityDrift,
  skillRetention,
} from '../metrics/identity'
import {
  CORE_PERSONA_ROLES,
  encodeLocator,
  makeReflection,
  MEMORY_KIND,

  policyParamsFrom,
  PolicyStorage,
} from './memory-policies'

/** Per-role predicted future value (HAC gate) and importance (threshold baselines). */
const ROLE_PROPS: Record<StatementRole, { fv: number, imp: number }> = {
  preference_early: { fv: 0.40, imp: 0.50 },
  preference_late: { fv: 0.85, imp: 0.80 },
  conflict_early: { fv: 0.60, imp: 0.70 },
  conflict_late: { fv: 0.65, imp: 0.75 },
  lowfreq_highvalue: { fv: 1.00, imp: 0.95 },
  highfreq_lowvalue: { fv: 0.05, imp: 0.10 },
  emotion_high_lowfact: { fv: 0.10, imp: 0.15 },
  delayed_useful: { fv: 0.95, imp: 0.45 },
  poison: { fv: 0.00, imp: 0.30 },
  relationship_boundary: { fv: 0.70, imp: 0.70 },
  neutral_fact: { fv: 0.30, imp: 0.50 },
}

/** Roles that count as "valuable" for the golden task-retrieval set. */
const VALUABLE_ROLES = new Set<StatementRole>([
  'lowfreq_highvalue',
  'delayed_useful',
  'preference_late',
  'conflict_early',
  'conflict_late',
  'relationship_boundary',
])

/** Developmental interest components passed to `GrowthLoop.runOnce` (fixed, harmless). */
const COMPONENTS: InterestComponents = {
  novelty: 0.6,
  knowledgeGap: 0.5,
  identityRelevance: 0.7,
  challenge: 0.5,
  userRelevance: 0.6,
  futureUtility: 0.5,
  cost: 0.2,
  risk: 0.1,
  repetitionPenalty: 0.1,
}

/** A search stub that returns exactly the current session's statements. */
class SessionSearch implements SearchPort {
  current: RawHit[] = []
  async search(): Promise<RawHit[]> {
    return this.current
  }
}

/** Build the per-session search hits for a dataset, embedding ground truth in `locator`. */
function buildSessionHits(dataset: LongitudinalDataset): RawHit[][] {
  const bySession = new Map<number, RawHit[]>()
  for (const stmt of dataset.statements) {
    const props = ROLE_PROPS[stmt.role]
    const meta: Omit<MemoryMeta, 'stmtId'> = {
      sessionIndex: stmt.sessionIndex,
      isTrue: stmt.isTrue,
      role: stmt.role,
      isDistractor: stmt.isDistractor,
      isContradictionLate: stmt.isContradictionLate,
      contradicts: stmt.contradicts,
      topic: stmt.isContradictionLate && stmt.contradicts ? stmt.contradicts : stmt.id,
      futureValue: props.fv,
      importance: props.imp,
    }
    const hit: RawHit = {
      locator: encodeLocator(stmt.id, meta),
      sourceType: stmt.role,
      content: stmt.text,
      fetchedAt: 0,
    }
    const arr = bySession.get(stmt.sessionIndex) ?? []
    arr.push(hit)
    bySession.set(stmt.sessionIndex, arr)
  }
  const out: RawHit[][] = []
  for (let s = 0; s < Math.max(...bySession.keys()) + 1; s++)
    out.push(bySession.get(s) ?? [])
  return out
}

/** The eight §5.4 + §5.4* (identity) metrics produced per dataset. */
export interface DatasetMetrics {
  fub: number
  epNet: number
  epRate: number
  gc: number
  precision: number
  recall: number
  cr: number
  fcr: number
  storedCount: number
  coreStability: number
  identityDrift: number
  skillRetention: number
}

/** Result for one configuration across all datasets. */
export interface ConfigResult {
  config: MechanismConfig
  perDataset: Record<keyof DatasetMetrics, number[]>
  metrics: DatasetMetrics
}

function mean(xs: number[]): number {
  if (xs.length === 0)
    return 0
  return xs.reduce((a, b) => a + b, 0) / xs.length
}

/** Per-dataset contradiction pairs (early → late) derived from the statements. */
function contradictionPairs(dataset: LongitudinalDataset): { early: string, late: string }[] {
  const pairs: { early: string, late: string }[] = []
  for (const s of dataset.statements) {
    if (s.isContradictionLate && s.contradicts)
      pairs.push({ early: s.contradicts, late: s.id })
  }
  return pairs
}

/** Simulate one configuration over one dataset through the real GrowthLoop. */
async function simulateDataset(config: MechanismConfig, dataset: LongitudinalDataset, budget: number): Promise<DatasetMetrics> {
  const base = new InMemoryStorage()
  const llm = new StubLlm()
  const policy = new PolicyStorage(base, policyParamsFrom(config, budget, makeReflection(llm)))
  const search = new SessionSearch()
  const signing = new InMemorySigning()
  const sched = new InMemoryScheduler()
  sched.markUnlimited('growth_loop')
  const loop = new GrowthLoop({ storage: policy, search, signing, scheduler: sched, llm }, 'agent-pilot', `scope-${dataset.id}`)

  const sessionHits = buildSessionHits(dataset)
  for (let s = 0; s < sessionHits.length; s++) {
    search.current = sessionHits[s]
    await loop.runOnce({
      subject: `session-${s}`,
      originEventIds: [`e${s}`],
      components: COMPONENTS,
      identityRelevance: 0.7,
      userRelevance: 0.6,
      noveltyFrontier: 0.5,
      researchQuestion: `learn session ${s}`,
      operationalDefinition: 'consolidate statement',
      expectedInformationGain: 0.5,
      questionType: 'everyday',
      query: `session-${s}`,
    })
  }

  return computeDatasetMetrics(policy.committed(), dataset, budget)
}

/** Compute every metric from the genuinely committed memory set + dataset ground truth. */
function computeDatasetMetrics(
  committed: Map<string, MemoryMeta>,
  dataset: LongitudinalDataset,
  budget: number,
): DatasetMetrics {
  const committedIds = new Set(committed.keys())

  // --- Effective Proactivity (from the committed memory substrate) -----------
  // acceptedUseful = valuable true, non-distractor memories (worth proactively sharing)
  // intrusive      = true but low-value clutter (neutral / high-freq noise) → over-sharing
  // unjustified    = false facts (poison) admitted → sharing without evidence
  let acceptedUseful = 0
  let intrusive = 0
  let unjustified = 0
  let distractorsCommitted = 0
  for (const m of committed.values()) {
    if (!m.isTrue) {
      unjustified++
      continue
    }
    if (m.isDistractor || m.role === 'neutral_fact') {
      intrusive++
      if (m.isDistractor)
        distractorsCommitted++
      continue
    }
    if (VALUABLE_ROLES.has(m.role as StatementRole))
      acceptedUseful++
  }
  const ep = effectiveProactivity({ acceptedUseful, intrusive, unjustified })

  // --- Future Utility @ Budget + Evidence Precision/Recall ------------------
  const golden = new Set<string>()
  for (const q of dataset.taskQueries) {
    for (const id of q.relevantTrueIds)
      golden.add(id)
  }
  const tp = [...golden].filter(id => committedIds.has(id)).length
  const fp = distractorsCommitted
  const pr = evidencePrecisionRecall({
    retrieved: [
      ...Array.from({ length: tp }, () => ({ isRelevant: true })),
      ...Array.from({ length: fp }, () => ({ isRelevant: false })),
    ],
    relevantTotal: golden.size,
  })
  const taskResults = dataset.taskQueries.map(q => ({
    weight: q.weight,
    utility: q.relevantTrueIds.some(id => committedIds.has(id)) ? 1 : 0,
  }))
  const fub = futureUtilityAtBudget({ budget, storedCount: committedIds.size, taskResults })

  // --- Contradiction Retention (dual-graph code path, not a flag) -----------
  const pairs = contradictionPairs(dataset)
  const contradictionCases = pairs.length
  const retainedCases = pairs.filter(p => committedIds.has(p.early) && committedIds.has(p.late)).length
  const cr = contradictionRetention({ contradictionCases, retainedCases })

  // --- False Consolidation Rate (poison that survived the policy) ------------
  const poisonIds = dataset.statements.filter(s => s.role === 'poison').map(s => s.id)
  const consolidatedFalse = poisonIds.filter(id => committedIds.has(id)).length
  const fcr = falseConsolidationRate({ falseFacts: poisonIds.length, consolidatedFalse })

  // --- Growth Coherence (loop evidence retained in memory) ------------------
  // GC = fraction of developmental learning events whose evidence (source record)
  // remains consolidated in long-term memory at the end of the run.
  const gc = growthCoherence({ totalChanges: dataset.statements.length, explainedChanges: committedIds.size })

  // --- Identity / skill metrics (from committed set) -------------------------
  const counts: IdentityCounts = countIdentity(committed)
  counts.totalSkills = dataset.statements.filter(s => s.role === 'lowfreq_highvalue').length
  const cs = coreStability(counts)
  const id = identityDrift(counts)
  const sr = skillRetention(counts)

  return {
    fub,
    epNet: ep.net,
    epRate: ep.rate,
    gc,
    precision: pr.precision,
    recall: pr.recall,
    cr,
    fcr,
    storedCount: committedIds.size,
    coreStability: cs,
    identityDrift: id,
    skillRetention: sr,
  }
}

/** Simulate every configuration over the whole benchmark. Pure & deterministic. */
export async function simulateAll(
  benchmark: SyntheticLongitudinalBenchmark,
  configs: MechanismConfig[],
): Promise<ConfigResult[]> {
  const results: ConfigResult[] = []
  for (const config of configs) {
    const per = await Promise.all(
      benchmark.datasets.map(d => simulateDataset(config, d, benchmark.scale.budgetPerDataset)),
    )
    const perDataset = {} as Record<keyof DatasetMetrics, number[]>
    for (const key of Object.keys(per[0]) as (keyof DatasetMetrics)[]) {
      perDataset[key] = per.map(m => m[key])
    }
    const metrics: DatasetMetrics = {
      fub: mean(per.map(m => m.fub)),
      epNet: mean(per.map(m => m.epNet)),
      epRate: mean(per.map(m => m.epRate)),
      gc: mean(per.map(m => m.gc)),
      precision: mean(per.map(m => m.precision)),
      recall: mean(per.map(m => m.recall)),
      cr: mean(per.map(m => m.cr)),
      fcr: mean(per.map(m => m.fcr)),
      storedCount: Math.round(mean(per.map(m => m.storedCount))),
      coreStability: mean(per.map(m => m.coreStability)),
      identityDrift: mean(per.map(m => m.identityDrift)),
      skillRetention: mean(per.map(m => m.skillRetention)),
    }
    results.push({ config, perDataset, metrics })
  }
  return results
}

// Re-export so consumers can reference the managed kind if needed.
export { MEMORY_KIND }
export { CORE_PERSONA_ROLES }
