/**
 * RQ-C experiment harness — the mechanism that produces publishable evidence.
 *
 * ## The 2x2
 *
 *   |                         | envFeedback OFF          | envFeedback ON            |
 *   |-------------------------|--------------------------|---------------------------|
 *   | selfVerification OFF    | naïve accumulation        | env-feedback only         |
 *   | selfVerification ON     | naïve self-report         | full closed loop          |
 *
 * ## Why tasks are revisited every round
 *
 * A skill is generated once, then the agent *re-encounters the same task* in
 * subsequent rounds. This is what makes the envFeedback axis meaningful:
 *
 *  - envFeedback OFF: a bad skill is reused forever; precision stays flat.
 *  - envFeedback ON : a repeatedly-failing skill is pruned (retired) once it
 *    crosses `minCalls`, so the next round *regenerates* a fresh candidate —
 *    which may be correct. Precision can then rise. (With `minCalls = k` you need
 *    `rounds > k` for the regeneration to get a chance to help; see the
 *    PREREGISTRATION note below.)
 *
 * Only the `envFeedback = ON` column can ever contain *retired* skills, because
 * self-verification rejections land in `status: 'rejected'` (not `'retired'`),
 * so `retiredRate` cleanly isolates the pruning effect.
 *
 * ## Analysis unit (fixes the pseudo-replication Blocker B1)
 *
 * The valid analysis unit is the **skill**, not the execution. A skill reused
 * across rounds is fully correlated with itself (rho=1), so treating every
 * execution as an independent Bernoulli trial understates the standard error by
 * ~1.5x and makes execution-level p-values spuriously small. All proportion
 * inference below therefore collapses each skill to one binary outcome
 * (success iff successCount/callCount >= 0.5) and tests at the skill level. The
 * old execution-level chi-square is retained as `chiSquareExecutionLevel` but
 * is explicitly diagnostic-only (see its comment).
 */

import type {
  BenchTask,
  ExecutionVerdict,
} from '@proj-aijade/skill-bench-env'
import type {
  LearningLoopCell,
  SelfVerificationDiagnostic,
  SkillRecord,
} from '@proj-aijade/skill-forge-store'

import type { LLMBackend } from './backends'
import type {
  ChiSquareResult,
  CI,
  DiDResult,
  HolmStep,
  LogOddsInteractionResult,
  McNemarResult,
} from './stats'

import {
  extractCodeBlock,
  runTask,
  sampleTasks,
} from '@proj-aijade/skill-bench-env'
import {
  computeLearningLoopTable,
  computeSelfVerificationDiagnostics,
  createMemorySkillStore,
  createSkillRegistry,
} from '@proj-aijade/skill-forge-store'

import {
  bootstrapPooledPrecision,
  chiSquare2x2,
  cohensH,
  cramersV,
  holmBonferroni,
  logOddsInteraction,
  mcnemarExactOrChi,
  minDetectableEffectProportion,
  mulberry32,
  oddsRatio,
  pooledDifferenceInDifferences,
  riskDifference,
} from './stats'

/**
 * Pre-registered experimental design.
 *
 * These values are the registered protocol, NOT tuning knobs. The CLI and the
 * harness both read their defaults from here so code and documentation can never
 * drift apart (fixes the selective-inference Blocker B3).
 *
 * `rounds` is 5 (not the old 3) because `pruneMinCalls` is 3: with `minCalls =
 * 3` the auto-retire can only fire once a skill has >=3 calls, so a failing
 * skill is first eligible for pruning in round 3. To give the regeneration a
 * chance to *help* before the run ends we need `rounds > minCalls`, hence 5.
 * `seed` is the default master seed; the CLI may override it per run.
 */
export const PREREGISTRATION = {
  trials: 30,
  rounds: 5,
  nTasks: 12,
  pruneThreshold: 0.5,
  pruneMinCalls: 3,
  seed: 42,
} as const

/**
 * Fixed label mixed into the trial-sampling seed so task selection depends on
 *  the trial only (block design, Blocker B4) — never on the condition index.
 */
const BLOCK_LABEL = 0xC0FFEE

export interface Condition {
  selfVerification: boolean
  envFeedback: boolean
}

/** Canonical condition order — matches `computeLearningLoopTable` cell order. */
export const CONDITIONS: readonly Condition[] = [
  { selfVerification: false, envFeedback: false },
  { selfVerification: false, envFeedback: true },
  { selfVerification: true, envFeedback: false },
  { selfVerification: true, envFeedback: true },
]

export function conditionId(c: Condition): string {
  return `sv${c.selfVerification ? 1 : 0}-ef${c.envFeedback ? 1 : 0}`
}

export interface StepRecord {
  condition: string
  trial: number
  round: number
  taskId: string
  skillId: string
  /** Whether this step reused an already-active skill instead of generating one. */
  reused: boolean
  /** Model self-verdict at this step (null when selfVerification is OFF, or on reuse). */
  selfVerdict: 'pass' | 'fail' | null
  /** Ground-truth execution outcome. */
  execOk: boolean
  durationMs: number
}

export interface RunOptions {
  backend: LLMBackend
  /** Trials (independent replications) per condition. */
  trials: number
  /** How many times the agent re-encounters each task. */
  rounds: number
  /** Master seed; per-condition/trial seeds are derived deterministically. */
  seed: number
  /** Number of distinct tasks sampled per trial. */
  nTasks: number
  /** Precision threshold for pruning. Default from PREREGISTRATION (not tuned). */
  pruneThreshold?: number
  /** Min calls before a skill may be pruned. Default from PREREGISTRATION (not tuned). */
  pruneMinCalls?: number
  /** Clock used by the registry (default: constant 0 for full determinism). */
  now?: () => number
  /** Called once per execution step (for streaming JSONL). */
  onStep?: (step: StepRecord) => void
}

export interface ConditionResult {
  condition: Condition
  id: string
  records: SkillRecord[]
}

export interface CellPrecision {
  sv: boolean
  ef: boolean
  /** Per-skill aggregated (successCount, callCount) for pooled-precision resampling. */
  skills: { succ: number, calls: number }[]
}

export interface EffectSizes {
  oddsRatio: number
  riskDifference: number
  cramersV: number
  cohensH: number
  interactionLogOdds: LogOddsInteractionResult
}

export interface PowerDeclaration {
  /** Minimum detectable effect (percentage points) at alpha=0.05, 80% power, p0=0.5. */
  minDetectableEffectAt80: number
  /** Skills per cell used for the power calculation. */
  nSkillsPerCell: number
}

export interface ExperimentResult {
  conditions: ConditionResult[]
  /** 4-cell learning-loop table (precision, retiredRate, meanCallsPerSkill). */
  table: LearningLoopCell[]
  /** Self-verification diagnostic, defined only on the selfVerification = ON row. */
  diagnostics: SelfVerificationDiagnostic
  /** Bootstrap CI per cell precision (pooled-precision resampling). */
  perCellCI: { sv: boolean, ef: boolean, ci: CI }[]
  /** The valid analysis unit for all proportion inference. */
  analysisUnit: 'skill'
  /** Number of skills with a defined outcome (callCount > 0): the effective N. */
  nSkills: number
  /** Total executions across all skills (!= nSkills; reported for transparency). */
  nExecutions: number
  /** Effect sizes for the envFeedback contrast and the 2x2 interaction. */
  effectSizes: EffectSizes
  /** Holm step-down correction over this run's primary inferences. */
  multiplicity: { method: 'holm', alpha: number, adjusted: HolmStep[] }
  /** 2x2 factorial interaction on the log-odds scale (replaces the old "DiD"). */
  factorialInteraction: LogOddsInteractionResult
  /** Skill-level chi-square: envFeedback (rows) x outcome (cols). PRIMARY TEST. */
  chiSquare: ChiSquareResult
  /**
   * Execution-level chi-square, retained only for historical comparison /
   * diagnosis. NOT VALID FOR INFERENCE: it counts every execution as
   * independent, ignoring that re-used skills are perfectly correlated
   * (pseudo-replication, Blocker B1). Its p-value is spuriously low.
   */
  chiSquareExecutionLevel: ChiSquareResult
  /** Paired McNemar test, envFeedback ON vs OFF, skills paired by trial x task. */
  mcnemarEnvFeedback: McNemarResult
  /** Declared statistical power for the skill-level design. */
  power: PowerDeclaration
  /**
   * Interaction effect (pooled DiD) on precision — kept as an alias of the old
   *  `diffInDiff` field for backward compatibility; the headline is now
   *  `factorialInteraction`. Conclusion language should say "2x2 factorial
   *  interaction", not "DiD".
   */
  diffInDiff: DiDResult
  /** Per-cell per-skill precision arrays (for downstream resampling). */
  cells: CellPrecision[]
}

/** Deterministic, well-mixed seed derivation for a condition / trial. */
function deriveSeed(base: number, i: number, t = 0): number {
  return (Math.imul(base ^ 0x85EBCA6B, 0x9E3779B9) ^ Math.imul(i + 1, 0xC2B2AE35) ^ Math.imul(t + 1, 0x27D4EB2F)) >>> 0
}

/** Collapse a skill to its binary outcome: success iff success/calls >= 0.5. */
function skillSuccess(r: SkillRecord): boolean {
  return r.callCount > 0 && (r.successCount / r.callCount) >= 0.5
}

export async function runExperiment(opts: RunOptions): Promise<ExperimentResult> {
  const pruneThreshold = opts.pruneThreshold ?? PREREGISTRATION.pruneThreshold
  // Default taken from the pre-registered protocol. `pruneMinCalls` is NOT a
  // tuning knob: it is fixed by PREREGISTRATION so the env-feedback effect is
  // estimated on the registered design, not chosen to make an effect appear.
  const pruneMinCalls = opts.pruneMinCalls ?? PREREGISTRATION.pruneMinCalls
  const now = opts.now ?? (() => 0)

  // --- Block design (Blocker B4) -------------------------------------------
  // Tasks are sampled ONCE per trial, indexed only by the trial number. Every
  // condition reuses the SAME task set for a given trial, so the four conditions
  // are balanced on task difficulty and McNemar pairing is valid. The old code
  // mixed the condition index into the sampling seed, which gave each condition
  // a different task subset (a fully randomized, not blocked, design).
  const trialTasks: BenchTask[][] = Array.from(
    { length: opts.trials },
    (_, t) => sampleTasks(opts.nTasks, deriveSeed(opts.seed, BLOCK_LABEL, t)),
  )

  const conditions: ConditionResult[] = []
  for (let i = 0; i < CONDITIONS.length; i++) {
    const cond = CONDITIONS[i]
    const res = await runCondition(cond, {
      ...opts,
      pruneThreshold,
      pruneMinCalls,
      now,
    }, trialTasks)
    conditions.push(res)
  }

  const allRecords = conditions.flatMap(c => c.records)

  const table = computeLearningLoopTable(allRecords, { domain: 'executable' })
  const diagnostics = computeSelfVerificationDiagnostics(allRecords)

  // Per-cell skill-level data: each skill contributes (successCount, callCount).
  interface SkillAgg { succ: number, calls: number }
  const cells: CellPrecision[] = []
  for (const sv of [false, true]) {
    for (const ef of [false, true]) {
      const skills: SkillAgg[] = allRecords
        .filter(
          r => (r.selfVerification?.enabled ?? false) === sv && (r.envFeedback?.enabled ?? false) === ef,
        )
        .filter(r => r.callCount > 0)
        .map(r => ({ succ: r.successCount, calls: r.callCount }))
      cells.push({ sv, ef, skills })
    }
  }
  const getCell = (sv: boolean, ef: boolean) => cells.find(c => c.sv === sv && c.ef === ef)!

  const perCellCI = cells.map(c => ({
    sv: c.sv,
    ef: c.ef,
    ci: bootstrapPooledPrecision(c.skills, { seed: deriveSeed(opts.seed, c.sv ? 3 : 1, c.ef ? 2 : 0) }),
  }))

  const cellSkills = (sv: boolean, ef: boolean) => getCell(sv, ef).skills
  const A = cellSkills(false, false)
  const B = cellSkills(false, true)
  const C = cellSkills(true, false)
  const D = cellSkills(true, true)

  // Pooled-precision DiD on the same (pooled) definition as the headline table.
  const diffInDiff = pooledDifferenceInDifferences(A, B, C, D, { seed: (opts.seed ^ 0x5BD1E995) >>> 0 })

  // --- Skill-level 2x2: envFeedback (rows) x outcome (cols) -----------------
  // Each skill is ONE binary observation. This is the valid primary contrast
  // (fixes pseudo-replication, Blocker B1).
  let onSucc = 0
  let onFail = 0
  let offSucc = 0
  let offFail = 0
  let nSkills = 0
  let nExecutions = 0
  for (const r of allRecords) {
    nExecutions += r.callCount
    if (r.callCount === 0)
      continue
    nSkills++
    const ok = skillSuccess(r)
    if (r.envFeedback?.enabled ?? false) {
      if (ok)
        onSucc++
      else onFail++
    }
    else if (ok) {
      offSucc++
    }
    else {
      offFail++
    }
  }
  const chiSquare = chiSquare2x2(onSucc, onFail, offSucc, offFail)

  // --- Execution-level chi-square (DIAGNOSTIC ONLY) -------------------------
  // Retained for historical comparison. Counts every execution as independent,
  // which UNDERSTATES the SE (~1.5x) and makes p spuriously small. Never use it
  // for inference.
  const sumSucc = (xs: SkillRecord[]) => xs.reduce((a, r) => a + r.successCount, 0)
  const sumFail = (xs: SkillRecord[]) => xs.reduce((a, r) => a + (r.callCount - r.successCount), 0)
  const envOn = allRecords.filter(r => r.envFeedback?.enabled ?? false)
  const envOff = allRecords.filter(r => !(r.envFeedback?.enabled ?? false))
  const chiSquareExecutionLevel = chiSquare2x2(
    sumSucc(envOn),
    sumFail(envOn),
    sumSucc(envOff),
    sumFail(envOff),
  )

  // --- Effect sizes (journal requirement) -----------------------------------
  const onRate = onSucc + onFail === 0 ? Number.NaN : onSucc / (onSucc + onFail)
  const offRate = offSucc + offFail === 0 ? Number.NaN : offSucc / (offSucc + offFail)
  const effectSizes: EffectSizes = {
    oddsRatio: oddsRatio(onSucc, onFail, offSucc, offFail),
    riskDifference: riskDifference(onSucc, onFail, offSucc, offFail),
    cramersV: cramersV(chiSquare.statistic, nSkills),
    cohensH: cohensH(onRate, offRate),
    // 2x2 factorial interaction on the log-odds scale: a=(sv0,ef0), b=(sv0,ef1),
    // c=(sv1,ef0), d=(sv1,ef1) cell success counts.
    interactionLogOdds: logOddsInteraction(
      getCell(false, false).skills.reduce((a, s) => a + s.succ, 0),
      getCell(false, true).skills.reduce((a, s) => a + s.succ, 0),
      getCell(true, false).skills.reduce((a, s) => a + s.succ, 0),
      getCell(true, true).skills.reduce((a, s) => a + s.succ, 0),
    ),
  }

  // --- Paired McNemar (Blocker B4) ------------------------------------------
  // Pair the envFeedback OFF vs ON skill for each (sv, trial, task). Valid only
  // because the block design guarantees both conditions see the same task.
  const mcnemar = mcnemarExactOrChi(...buildMcNemarTable(allRecords))

  // --- 2x2 factorial interaction (log-odds) --------------------------------
  const factorialInteraction = effectSizes.interactionLogOdds

  // --- Holm correction over the primary inference family --------------------
  const multiplicity = {
    method: 'holm' as const,
    alpha: 0.05,
    adjusted: holmBonferroni(
      [chiSquare.p, mcnemar.p, factorialInteraction.p],
      0.05,
      ['envFeedback.skillLevelChiSquare', 'envFeedback.mcnemar', 'svXef.factorialInteraction'],
    ),
  }

  // --- Declared power -------------------------------------------------------
  const nSkillsPerCell = nSkills > 0 ? Math.round(nSkills / 4) : 0
  const minDetectableEffectAt80 = nSkillsPerCell > 0
    ? minDetectableEffectProportion(nSkillsPerCell) * 100
    : Number.NaN

  return {
    conditions,
    table,
    diagnostics,
    perCellCI,
    analysisUnit: 'skill',
    nSkills,
    nExecutions,
    effectSizes,
    multiplicity,
    factorialInteraction,
    chiSquare,
    chiSquareExecutionLevel,
    mcnemarEnvFeedback: mcnemar,
    power: { minDetectableEffectAt80, nSkillsPerCell },
    diffInDiff,
    cells,
  }
}

/**
 * Build the McNemar (a,b,c,d) table by pairing envFeedback OFF/ON skills per
 *  (selfVerification, trial, task). Returns [a, b, c, d].
 */
function buildMcNemarTable(records: SkillRecord[]): [number, number, number, number] {
  const pairs = new Map<string, { off?: SkillRecord, on?: SkillRecord }>()
  for (const r of records) {
    const sv = r.selfVerification?.enabled ?? false
    const ef = r.envFeedback?.enabled ?? false
    const taskId = r.metadata?.taskId as string | undefined
    const trial = r.metadata?.trial as number | undefined
    if (taskId === undefined || trial === undefined)
      continue
    const key = `${sv}|${trial}|${taskId}`
    const entry = pairs.get(key) ?? {}
    if (ef)
      entry.on = r
    else entry.off = r
    pairs.set(key, entry)
  }
  let a = 0
  let b = 0
  let c = 0
  let d = 0
  for (const e of pairs.values()) {
    if (!e.off || !e.on)
      continue
    const offOk = skillSuccess(e.off)
    const onOk = skillSuccess(e.on)
    if (!offOk && !onOk)
      a++
    else if (!offOk && onOk)
      b++
    else if (offOk && !onOk)
      c++
    else d++
  }
  return [a, b, c, d]
}

async function runCondition(
  cond: Condition,
  opts: Required<Pick<RunOptions, 'backend' | 'trials' | 'rounds' | 'nTasks' | 'pruneThreshold' | 'pruneMinCalls' | 'now'>> & Pick<RunOptions, 'onStep'>,
  trialTasks: BenchTask[][],
): Promise<ConditionResult> {
  const records: SkillRecord[] = []
  for (let t = 0; t < opts.trials; t++) {
    // Tasks for this trial are FIXED (block design): every condition uses the
    // same `trialTasks[t]`. This function therefore never samples on its own.
    const tasks: BenchTask[] = trialTasks[t]
    const registry = createSkillRegistry({ store: createMemorySkillStore(), now: opts.now })
    const skillByTask = new Map<string, string>()

    for (let round = 0; round < opts.rounds; round++) {
      for (const task of tasks) {
        let skillId = skillByTask.get(task.id)
        let reused = false
        let existing: SkillRecord | undefined
        if (skillId) {
          existing = await registry.get(skillId)
          if (existing && existing.status === 'active') {
            reused = true
          }
          else {
            // retired / rejected / missing -> force a fresh generation this round.
            skillId = undefined
            existing = undefined
          }
        }

        let codeForExec: string
        let selfVerdict: 'pass' | 'fail' | null = null

        if (!skillId) {
          const candidate = await opts.backend.generate(task, { attempt: round })
          const code = extractCodeBlock(candidate) ?? candidate
          codeForExec = code
          skillId = `${conditionId(cond)}-t${t}-r${round}-${task.id}`
          await registry.create({
            name: `skill-${task.id}`,
            domain: 'executable',
            skillId,
            body: candidate,
            envFeedback: { enabled: cond.envFeedback },
            metadata: { taskId: task.id, trial: t, round, condition: conditionId(cond) },
          })
          if (cond.selfVerification) {
            const v = await opts.backend.verify(task, candidate)
            await registry.setSelfVerification(skillId, v.verdict, {
              score: v.score,
              rationale: v.rationale,
              model: opts.backend.name,
            })
            selfVerdict = v.verdict
          }
          // Register the new skill so subsequent rounds REUSE it (this is what lets
          // callCount accumulate and pruning/retirement fire). Without this the
          // agent would regenerate every round and the env-feedback axis dies.
          skillByTask.set(task.id, skillId)
        }
        else {
          // Reuse: keep the prior self-verdict for diagnostics pairing.
          codeForExec = existing!.body ? extractCodeBlock(existing!.body) ?? existing!.body : ''
          selfVerdict = existing!.selfVerification?.verdict ?? null
        }

        const verdict: ExecutionVerdict = runTask(codeForExec, task)
        await registry.recordExecution(skillId, {
          ok: verdict.ok,
          detail: verdict.error,
          durationMs: Math.round(verdict.durationMs),
        })

        if (cond.envFeedback)
          await registry.pruneLowPrecision(opts.pruneThreshold, opts.pruneMinCalls)

        opts.onStep?.({
          condition: conditionId(cond),
          trial: t,
          round,
          taskId: task.id,
          skillId,
          reused,
          selfVerdict,
          execOk: verdict.ok,
          durationMs: Math.round(verdict.durationMs),
        })
      }
    }

    records.push(...(await registry.all()))
  }

  return { condition: cond, id: conditionId(cond), records }
}

/** Small helper re-exported for convenience in tests. */
export { mulberry32 }
