/**
 * §39.1 / §5.2 — Deterministic synthetic longitudinal benchmark generator.
 *
 * Produces multi-day timelines that explicitly contain, and let us perturb, the
 * phenomena required by the paper: user-preference drift (early A → late B),
 * conflicting facts, low-frequency high-value events, high-frequency low-value
 * noise, high-emotion low-fact events, delayed-usefulness information, malicious
 * memory poisoning and relationship-boundary shifts.
 *
 * Determinism contract: the generator uses ONLY a seeded PRNG (mulberry32); it
 * never calls `Math.random()`. The same `seed` yields a byte-identical benchmark,
 * which the pilot test asserts via deep equality.
 *
 * Scale (paper §5.2 leaves the exact numbers 【待作者确认】; the design document
 * §39.1 lists the required *categories* but no explicit counts, so we adopt the
 * fixed numbers specified for this implementation and reported in the result file):
 *   12 datasets × 20 sessions × 8 statements = 1920 statements
 *   6 time windows (40 sessions / window)
 *   contradiction injection rate 15% (late member of a conflict pair)
 *   distractor ratio 10%
 *   storage budget B = 200 memory slots / dataset (for Future Utility@Budget)
 */

/** Role of a single synthetic statement. */
export type StatementRole
  = | 'preference_early'
    | 'preference_late'
    | 'conflict_early'
    | 'conflict_late'
    | 'lowfreq_highvalue'
    | 'highfreq_lowvalue'
    | 'emotion_high_lowfact'
    | 'delayed_useful'
    | 'poison'
    | 'relationship_boundary'
    | 'neutral_fact'

/** A single labelled statement in the longitudinal timeline. */
export interface Statement {
  id: string
  datasetId: number
  sessionIndex: number
  globalIndex: number
  windowIndex: number
  text: string
  /** 真值标注：true=事实正确，false=错误事实/投毒。 */
  isTrue: boolean
  role: StatementRole
  /** 干扰项（10%）：高频无价值或情绪高事实低价值。 */
  isDistractor: boolean
  /** 该陈述是否为矛盾对的“后期相反证据”成员。 */
  isContradictionLate: boolean
  /** 若存在，指向更早的 conflict_early 陈述 id（矛盾对）。 */
  contradicts?: string
}

/** A held-out task query used to measure Future Utility / Evidence recall. */
export interface TaskQuery {
  id: string
  datasetId: number
  windowIndex: number
  weight: number
  /** golden 相关真陈述 id（检索时应命中）。 */
  relevantTrueIds: string[]
}

/** One scenario (independent memory budget & retrieval isolation). */
export interface LongitudinalDataset {
  id: number
  statements: Statement[]
  taskQueries: TaskQuery[]
}

/** Benchmark scale parameters (reported in the pilot result file). */
export interface BenchmarkScale {
  datasets: number
  sessionsPerDataset: number
  statementsPerSession: number
  windows: number
  sessionsPerWindow: number
  contradictionRate: number
  distractorRate: number
  budgetPerDataset: number
  totalStatements: number
}

/** The full generated benchmark. */
export interface SyntheticLongitudinalBenchmark {
  seed: number
  scale: BenchmarkScale
  datasets: LongitudinalDataset[]
  /** All contradiction pairs (early → late). */
  contradictions: { earlyId: string, lateId: string }[]
  /** All distractor statement ids. */
  distractors: string[]
}

/** Default scale — the fixed numbers specified for this implementation. */
export function defaultScale(): BenchmarkScale {
  const datasets = 12
  const sessionsPerDataset = 20
  const statementsPerSession = 8
  const windows = 6
  const sessionsPerWindow = (datasets * sessionsPerDataset) / windows // 40
  const contradictionRate = 0.15
  const distractorRate = 0.10
  const budgetPerDataset = 200
  return {
    datasets,
    sessionsPerDataset,
    statementsPerSession,
    windows,
    sessionsPerWindow,
    contradictionRate,
    distractorRate,
    budgetPerDataset,
    totalStatements: datasets * sessionsPerDataset * statementsPerSession,
  }
}

// --- seeded PRNG (local, not exported) ----------------------------------------
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return function () {
    a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function shuffle<T>(xs: T[], rng: () => number): T[] {
  const a = xs.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1))
    const tmp = a[i]
    a[i] = a[j]
    a[j] = tmp
  }
  return a
}

const ROLE_TEMPLATE: { role: StatementRole, count: number }[] = [
  { role: 'lowfreq_highvalue', count: 12 },
  { role: 'delayed_useful', count: 12 },
  { role: 'preference_early', count: 12 },
  { role: 'preference_late', count: 12 },
  { role: 'relationship_boundary', count: 10 },
  { role: 'highfreq_lowvalue', count: 10 },
  { role: 'emotion_high_lowfact', count: 6 },
  { role: 'neutral_fact', count: 30 },
]
// non-contradiction, non-poison roles sum to 12+12+12+12+10+10+6+30 = 104.

const VALUABLE_ROLES: StatementRole[] = [
  'lowfreq_highvalue',
  'delayed_useful',
  'preference_late',
  'conflict_early',
  'conflict_late',
  'relationship_boundary',
]

function isDistractorRole(role: StatementRole): boolean {
  return role === 'highfreq_lowvalue' || role === 'emotion_high_lowfact'
}

/**
 * Generate the synthetic longitudinal benchmark for a given integer `seed`.
 * Pure: identical seed → identical structure (deep-equal).
 */
export function generateSyntheticLongitudinal(seed = 1, scale: BenchmarkScale = defaultScale()): SyntheticLongitudinalBenchmark {
  const rng = mulberry32(seed)
  const datasets: LongitudinalDataset[] = []
  const allContradictions: { earlyId: string, lateId: string }[] = []
  const allDistractors: string[] = []

  for (let d = 0; d < scale.datasets; d++) {
    const statements: Statement[] = []
    const contradictions: { earlyId: string, lateId: string }[] = []

    // Build the per-dataset role multiset, guaranteeing every conflict_late has an
    // earlier conflict_early (all early live in the first half, all late in second).
    // Per-dataset COUNT JITTER (deterministic, seeded). Keeps the *global* averages
    // at the spec rates (≈15% contradiction-late, ≈10% distractors) while giving each
    // scenario realistic variation so the bootstrap CIs and effect sizes are non-degenerate.
    const nCL = 20 + Math.floor(rng() * 9) // 20..28 (avg 24 → 15% of 160)
    const nPoison = 6 + Math.floor(rng() * 5) // 6..10 (avg 8)
    const other = 160 - 2 * nCL - nPoison
    const tTotal = ROLE_TEMPLATE.reduce((a, t) => a + t.count, 0) // 104
    const otherRoles: StatementRole[] = []
    for (const t of ROLE_TEMPLATE) {
      const c = Math.max(0, Math.round((t.count / tTotal) * other))
      for (let i = 0; i < c; i++)
        otherRoles.push(t.role)
    }
    // Fix rounding drift on neutral_fact (largest share) to hit `other` exactly.
    const drift = other - otherRoles.length
    if (drift > 0) {
      for (let i = 0; i < drift; i++)
        otherRoles.push('neutral_fact')
    }
    else if (drift < 0) {
      let remove = -drift
      for (let i = otherRoles.length - 1; i >= 0 && remove > 0; i--) {
        if (otherRoles[i] === 'neutral_fact') {
          otherRoles.splice(i, 1)
          remove--
        }
      }
      for (let i = 0; i < remove; i++)
        otherRoles.push('neutral_fact')
    }

    const firstN = Math.floor(other / 2)
    const poisonFirst: StatementRole[] = Array.from({ length: Math.floor(nPoison / 2) }, () => 'poison' as StatementRole)
    const poisonSecond: StatementRole[] = Array.from({ length: nPoison - Math.floor(nPoison / 2) }, () => 'poison' as StatementRole)
    const earlyRoles: StatementRole[] = Array.from({ length: nCL }, () => 'conflict_early' as StatementRole)
    const lateRoles: StatementRole[] = Array.from({ length: nCL }, () => 'conflict_late' as StatementRole)

    const firstHalfRoles = shuffle([...otherRoles.slice(0, firstN), ...poisonFirst, ...earlyRoles], rng)
    const secondHalfRoles = shuffle([...otherRoles.slice(firstN), ...poisonSecond, ...lateRoles], rng)

    const earlyPool: string[] = []
    let localIndex = 0
    const half = firstHalfRoles.length + secondHalfRoles.length // 160
    const emit = (role: StatementRole) => {
      const sessionIndex = Math.floor(localIndex / scale.statementsPerSession)
      const globalIndex = d * half + localIndex
      const sessionGlobal = d * scale.sessionsPerDataset + sessionIndex
      const windowIndex = Math.floor(sessionGlobal / scale.sessionsPerWindow)
      const id = `st_${globalIndex}`
      const isDistractor = isDistractorRole(role)
      const isContradictionLate = role === 'conflict_late'
      const stmt: Statement = {
        id,
        datasetId: d,
        sessionIndex,
        globalIndex,
        windowIndex,
        text: `${role}@d${d}s${sessionIndex}#${localIndex}`,
        isTrue: role !== 'poison',
        role,
        isDistractor,
        isContradictionLate,
      }
      if (isContradictionLate) {
        const earlyId = earlyPool[earlyPool.length - 1]
        stmt.contradicts = earlyId
        contradictions.push({ earlyId, lateId: id })
      }
      if (role === 'conflict_early')
        earlyPool.push(id)
      if (isDistractor)
        allDistractors.push(id)
      statements.push(stmt)
      localIndex++
    }

    for (const r of firstHalfRoles)
      emit(r)
    for (const r of secondHalfRoles)
      emit(r)

    // Task queries: 6 per dataset (one per virtual window of ~3-4 sessions).
    // Golden = valuable statements from strictly earlier sessions (delayed use).
    const taskQueries: TaskQuery[] = []
    const sessionsPerVWin = Math.ceil(scale.sessionsPerDataset / scale.windows) // 4
    for (let q = 0; q < scale.windows; q++) {
      const startSession = q * sessionsPerVWin
      const golden: string[] = []
      for (const s of statements) {
        if (VALUABLE_ROLES.includes(s.role) && s.sessionIndex < startSession)
          golden.push(s.id)
      }
      // For the very first window there is no earlier session; anchor on its own.
      if (golden.length === 0) {
        for (const s of statements) {
          if (VALUABLE_ROLES.includes(s.role) && s.sessionIndex <= startSession)
            golden.push(s.id)
        }
      }
      taskQueries.push({
        id: `q_${d}_${q}`,
        datasetId: d,
        windowIndex: q,
        weight: 1,
        relevantTrueIds: golden,
      })
    }

    datasets.push({ id: d, statements, taskQueries })
    allContradictions.push(...contradictions)
  }

  return {
    seed,
    scale,
    datasets,
    contradictions: allContradictions,
    distractors: allDistractors,
  }
}
