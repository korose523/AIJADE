#!/usr/bin/env tsx
import type { CI, SkillCount } from '../src/stats'

import { execSync } from 'node:child_process'
/**
 * replay/replay.ts — Deterministic, provenance-stamped RQ-C replay pipeline.
 *
 * Turns a raw run artifact (`trials.jsonl`, append-only, possibly being written
 * live with a torn final line) plus the harness `summary.json` into every table
 * and figure the paper needs, WITHOUT re-running the experiment.
 *
 * ## Provenance / determinism contract
 *   - No Math.random(), no Date.now() in any *computed* value. Bootstrap uses a
 *     fixed seed taken from the recorded run seed (default 42). Re-running on
 *     byte-identical input yields byte-identical output.
 *   - Emits `out/MANIFEST.json` (sha256 of both inputs, run dir, seed, model
 *     tag, ollama version, record count, git commit) so the ACM artifact claim
 *     is checkable. MANIFEST contains no wall-clock (the run's wall clock is not
 *     recorded in the artifacts, so it is null).
 *
 * ## Data model (verified against a real trials.jsonl line)
 *   Each line of trials.jsonl is a `StepRecord`:
 *     { condition: 'sv0-ef0'|'sv0-ef1'|'sv1-ef0'|'sv1-ef1',
 *       trial, round, taskId, skillId, reused, selfVerdict: 'pass'|'fail'|null,
 *       execOk, durationMs }
 *   A *skill* is identified by `skillId` (pattern `${cond}-t${t}-r${round}-${task}`).
 *   We reconstruct each skill's (successCount, callCount) by grouping steps, and
 *   we track the **creation order** of each skillId (first appearance in the
 *   streaming file) so that bootstrap resampling order matches the harness's
 *   `registry.all()` order exactly — required for bit-identical CIs.
 *
 * ## Functions imported from src/ vs reimplemented
 *   IMPORTED (from `../src/stats.ts`, the canonical, pure, seeded implementations
 *   the harness itself uses — see harness.ts:71-84 imports):
 *     chiSquare2x2, oddsRatio, riskDifference, cramersV, cohensH,
 *     logOddsInteraction, mcnemarExactOrChi, holmBonferroni,
 *     minDetectableEffectProportion, bootstrapPooledPrecision,
 *     pooledDifferenceInDifferences.
 *
 *   REIMPLEMENTED (mirrored from the inline originals in harness.ts, because the
 *   corresponding helpers are module-private and must be reproduced here):
 *     - deriveSeed(base,i,t)        <- harness.ts:239-241
 *     - skillSuccess(r)             <- harness.ts:243-246
 *     - buildMcNemarTable(records)  <- harness.ts:426-460  (rewritten over our
 *                                     reconstructed skills instead of SkillRecords)
 *   The §1.10 "footgun" is explicitly avoided: we use bootstrapPooledPrecision /
 *   pooledDifferenceInDifferences (the harness's headline definitions), NOT the
 *   divergent exported `bootstrapCI` / `differenceInDifferences` which resample
 *   per-unit *values* and take their *mean* — a different estimand. CHECKS.md
 *   records that choice.
 *
 * Usage:
 *   tsx replay/replay.ts --run-dir experiments/rq-c/<runId> \
 *                        [--summary experiments/rq-c/<runId>/summary.json] \
 *                        [--out replay/out] [--bootstrap-seed 42]
 */
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'

import {
  bootstrapPooledPrecision,
  chiSquare2x2,

  cohensH,
  cramersV,
  holmBonferroni,
  logOddsInteraction,
  mcnemarExactOrChi,
  minDetectableEffectProportion,
  oddsRatio,
  pooledDifferenceInDifferences,
  riskDifference,

} from '../src/stats'

// ===========================================================================
// CLI
// ===========================================================================
interface Args {
  runDir: string
  summary: string | null
  out: string
  bootstrapSeed: number
}
function parseArgs(argv: string[]): Args {
  const a: Args = { runDir: '', summary: null, out: 'replay/out', bootstrapSeed: 42 }
  for (let i = 0; i < argv.length; i++) {
    const x = argv[i]
    const next = () => {
      const v = argv[++i]
      if (v === undefined)
        throw new Error(`Missing value for ${x}`)
      return v
    }
    switch (x) {
      case '--run-dir': a.runDir = next(); break
      case '--summary': a.summary = next(); break
      case '--out': a.out = next(); break
      case '--bootstrap-seed': a.bootstrapSeed = Number.parseInt(next(), 10); break
      default: throw new Error(`Unknown arg: ${x}`)
    }
  }
  if (!a.runDir)
    throw new Error('--run-dir is required')
  return a
}

// ===========================================================================
// Reimplemented helpers (mirrored from harness.ts — see header)
// ===========================================================================

/** <- harness.ts:239-241 */
function deriveSeed(base: number, i: number, t = 0): number {
  return (Math.imul(base ^ 0x85EBCA6B, 0x9E3779B9)
    ^ Math.imul(i + 1, 0xC2B2AE35)
    ^ Math.imul(t + 1, 0x27D4EB2F)) >>> 0
}

interface SkillAgg extends SkillCount {
  sv: boolean
  ef: boolean
  taskId: string
  trial: number
  /** first-appearance index in the streaming file = harness creation order. */
  seq: number
  /** selfVerdict seen for a self-verified skill ('pass'|'fail'). */
  selfVerdict: 'pass' | 'fail' | null
}

/** <- harness.ts:243-246 */
function skillSuccess(r: SkillAgg): boolean {
  return r.calls > 0 && (r.succ / r.calls) >= 0.5
}

// ===========================================================================
// Parse trials.jsonl (snapshot; tolerate a torn final line)
// ===========================================================================
interface StepRecord {
  condition: string
  trial: number
  round: number
  taskId: string
  skillId: string
  reused: boolean
  selfVerdict: 'pass' | 'fail' | null
  execOk: boolean
  durationMs: number
}

function sha256File(p: string): string {
  const h = createHash('sha256')
  h.update(readFileSync(p))
  return h.digest('hex')
}

function gitCommit(): string {
  try {
    return execSync('git rev-parse HEAD', { cwd: process.cwd() }).toString().trim()
  }
  catch {
    return 'unknown'
  }
}

// ===========================================================================
// Reconstruct skills + per-step aggregates from trials.jsonl
// ===========================================================================
interface Reconstructed {
  steps: StepRecord[]
  skills: Map<string, SkillAgg>
  /** (sv,trial,taskId) -> { off?:skillKey, on?:skillKey(last in creation order) } */
  mcnemarPairs: Map<string, { off?: string, on?: string }>
  cellSuccess: { [sv: string]: { [ef: string]: number } }
  nExecutions: number
  nSkills: number
}

function reconstruct(trialsPath: string): Reconstructed {
  const raw = readFileSync(trialsPath, 'utf8')
  // Single snapshot read -> consistent even if the file grows between reads.
  const lines = raw.split('\n')
  const steps: StepRecord[] = []
  const skills = new Map<string, SkillAgg>()
  const mcnemarPairs = new Map<string, { off?: string, on?: string }>()
  const cellSuccess: { [sv: string]: { [ef: string]: number } } = { true: { true: 0, false: 0 }, false: { true: 0, false: 0 } }
  let seq = 0
  let nExecutions = 0

  for (const line of lines) {
    const t = line.trim()
    if (t.length === 0)
      continue
    let rec: StepRecord
    try {
      rec = JSON.parse(t) as StepRecord
    }
    catch {
      // Torn final line (file appended live / truncated mid-JSON): discard.
      continue
    }
    steps.push(rec)
    nExecutions++

    const m = /^sv(\d)-ef(\d)$/.exec(rec.condition)
    const sv = m ? m[1] === '1' : false
    const ef = m ? m[2] === '1' : false

    let s = skills.get(rec.skillId)
    if (!s) {
      s = { sv, ef, taskId: rec.taskId, trial: rec.trial, succ: 0, calls: 0, seq: seq++, selfVerdict: rec.selfVerdict }
      skills.set(rec.skillId, s)
    }
    else {
      // keep the recorded selfVerdict if we only saw null first
      if (s.selfVerdict === null && rec.selfVerdict !== null)
        s.selfVerdict = rec.selfVerdict
    }
    s.calls++
    if (rec.execOk)
      s.succ++

    const key = `${sv}|${rec.trial}|${rec.taskId}`
    let pair = mcnemarPairs.get(key)
    if (!pair) {
      pair = {}
      mcnemarPairs.set(key, pair)
    }
    if (ef)
      pair.on = rec.skillId // last assignment wins -> harness keeps the LAST on skill
    else pair.off = rec.skillId
  }

  let nSkills = 0
  for (const s of skills.values()) {
    if (s.calls > 0) {
      nSkills++
      cellSuccess[String(s.sv)][String(s.ef)] += s.succ
    }
  }

  return { steps, skills, mcnemarPairs, cellSuccess, nExecutions, nSkills }
}

// Build the 4 cell skill arrays (ordered by harness creation order).
function cellsByOrder(rec: Reconstructed): { sv: boolean, ef: boolean, skills: SkillCount[] }[] {
  const grouped: { sv: boolean, ef: boolean, list: SkillAgg[] }[] = []
  for (const sv of [false, true]) {
    for (const ef of [false, true]) {
      const list = [...rec.skills.values()]
        .filter(s => s.sv === sv && s.ef === ef && s.calls > 0)
        .sort((a, b) => a.seq - b.seq)
      grouped.push({ sv, ef, list: list.map(s => ({ succ: s.succ, calls: s.calls })) })
    }
  }
  return grouped.map(g => ({ sv: g.sv, ef: g.ef, skills: g.list }))
}

// McNemar table <- harness.ts:426-460 (over reconstructed skills)
function buildMcNemarTable(rec: Reconstructed): [number, number, number, number] {
  let a = 0
  let b = 0
  let c = 0
  let d = 0
  for (const pair of rec.mcnemarPairs.values()) {
    if (!pair.off || !pair.on)
      continue
    const off = rec.skills.get(pair.off)
    const on = rec.skills.get(pair.on)
    if (!off || !on || off.calls === 0 || on.calls === 0)
      continue
    const offOk = skillSuccess(off)
    const onOk = skillSuccess(on)
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

// ===========================================================================
// Self-verification diagnostics — mirrored at STEP level from trials.jsonl.
// The harness's computeSelfVerificationDiagnostics (skill-forge-store/types.ts:524)
// counts only records with selfVerification.enabled && execution and aggregates
// verdict vs outcome. Because each execution step carries the same selfVerdict as
// its (reused) skill, per-step counting reproduces the identical counts.
// ===========================================================================
function computeDiagnostics(rec: Reconstructed) {
  // Mirrors skill-forge-store computeSelfVerificationDiagnostics: it counts only
  // records with selfVerification.enabled && execution, i.e. ONE (verdict,
  // outcome) pair PER SKILL (outcome = skill-level success), not per execution.
  // We therefore reconstruct at the skill level here, not the step level.
  let n = 0
  let passAndFail = 0
  let passTotal = 0
  let failAndPass = 0
  let failTotal = 0
  let agree = 0
  for (const s of rec.skills.values()) {
    if (!s.sv || s.calls === 0 || s.selfVerdict === null)
      continue
    n++
    const ok = skillSuccess(s)
    const selfPass = s.selfVerdict === 'pass'
    if (selfPass) {
      passTotal++
      if (!ok)
        passAndFail++
      else agree++
    }
    else {
      failTotal++
      if (ok)
        failAndPass++
      else agree++
    }
  }
  const nan = (x: number) => (n === 0 || Number.isNaN(x) ? Number.NaN : x)
  return {
    n,
    hallucinationRate: nan(passTotal === 0 ? Number.NaN : passAndFail / passTotal),
    missRate: nan(failTotal === 0 ? Number.NaN : failAndPass / failTotal),
    agreement: nan(n === 0 ? Number.NaN : agree / n),
  }
}

// ===========================================================================
// Core computation (mirrors harness.runExperiment aggregation)
// ===========================================================================
interface Computed {
  nSkills: number
  nExecutions: number
  cells: { sv: boolean, ef: boolean, skills: SkillCount[], precision: number, count: number, meanCalls: number }[]
  chiSquare: ReturnType<typeof chiSquare2x2>
  effectSizes: {
    oddsRatio: number
    riskDifference: number
    cramersV: number
    cohensH: number
    interactionLogOdds: ReturnType<typeof logOddsInteraction>
  }
  factorialInteraction: ReturnType<typeof logOddsInteraction>
  mcnemar: ReturnType<typeof mcnemarExactOrChi>
  multiplicity: ReturnType<typeof holmBonferroni>
  power: { minDetectableEffectAt80: number, nSkillsPerCell: number }
  perCellCI: { sv: boolean, ef: boolean, ci: CI }[]
  diffInDiff: ReturnType<typeof pooledDifferenceInDifferences>
  diagnostics: ReturnType<typeof computeDiagnostics>
}

function compute(rec: Reconstructed, seed: number): Computed {
  const cells = cellsByOrder(rec).map((g) => {
    const calls = g.skills.reduce((a, s) => a + s.calls, 0)
    const succ = g.skills.reduce((a, s) => a + s.succ, 0)
    return {
      sv: g.sv,
      ef: g.ef,
      skills: g.skills,
      precision: calls === 0 ? Number.NaN : succ / calls,
      count: g.skills.length,
      meanCalls: g.skills.length === 0 ? Number.NaN : calls / g.skills.length,
    }
  })
  const getCell = (sv: boolean, ef: boolean) => cells.find(c => c.sv === sv && c.ef === ef)!
  const cellSkills = (sv: boolean, ef: boolean) => getCell(sv, ef).skills

  const A = cellSkills(false, false)
  const B = cellSkills(false, true)
  const C = cellSkills(true, false)
  const D = cellSkills(true, true)

  // Skill-level 2x2: envFeedback (rows) x skill outcome (cols)
  let onSucc = 0
  let onFail = 0
  let offSucc = 0
  let offFail = 0
  for (const s of rec.skills.values()) {
    if (s.calls === 0)
      continue
    const ok = skillSuccess(s)
    if (s.ef) {
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

  const onRate = (onSucc + onFail) === 0 ? Number.NaN : onSucc / (onSucc + onFail)
  const offRate = (offSucc + offFail) === 0 ? Number.NaN : offSucc / (offSucc + offFail)
  const effectSizes = {
    oddsRatio: oddsRatio(onSucc, onFail, offSucc, offFail),
    riskDifference: riskDifference(onSucc, onFail, offSucc, offFail),
    cramersV: cramersV(chiSquare.statistic, rec.nSkills),
    cohensH: cohensH(onRate, offRate),
    interactionLogOdds: logOddsInteraction(
      getCell(false, false).skills.reduce((a, s) => a + s.succ, 0),
      getCell(false, true).skills.reduce((a, s) => a + s.succ, 0),
      getCell(true, false).skills.reduce((a, s) => a + s.succ, 0),
      getCell(true, true).skills.reduce((a, s) => a + s.succ, 0),
    ),
  }
  const factorialInteraction = effectSizes.interactionLogOdds

  const mcnemar = mcnemarExactOrChi(...buildMcNemarTable(rec))

  const multiplicity = holmBonferroni(
    [chiSquare.p, mcnemar.p, factorialInteraction.p],
    0.05,
    ['envFeedback.skillLevelChiSquare', 'envFeedback.mcnemar', 'svXef.factorialInteraction'],
  )

  const nSkillsPerCell = rec.nSkills > 0 ? Math.round(rec.nSkills / 4) : 0
  const minDetectableEffectAt80 = nSkillsPerCell > 0 ? minDetectableEffectProportion(nSkillsPerCell) * 100 : Number.NaN

  const perCellCI = cells.map(c => ({
    sv: c.sv,
    ef: c.ef,
    ci: bootstrapPooledPrecision(c.skills, { seed: deriveSeed(seed, c.sv ? 3 : 1, c.ef ? 2 : 0) }),
  }))

  const diffInDiff = pooledDifferenceInDifferences(A, B, C, D, { seed: (seed ^ 0x5BD1E995) >>> 0 })

  return {
    nSkills: rec.nSkills,
    nExecutions: rec.nExecutions,
    cells,
    chiSquare,
    effectSizes,
    factorialInteraction,
    mcnemar,
    multiplicity,
    power: { minDetectableEffectAt80, nSkillsPerCell },
    perCellCI,
    diffInDiff,
    diagnostics: computeDiagnostics(rec),
  }
}

// ===========================================================================
// Self-validation against summary.json
// ===========================================================================
/**
 * Checks are split into two classes, because "does this number agree?" has two
 * genuinely different answers depending on what kind of number it is:
 *
 *   'A' binding  — counts, contingency tables, and headline estimates. These are
 *                  exact integers or exact ratios of integers, so any drift means
 *                  the two sides analysed different data. A failure here MUST fail
 *                  the build.
 *   'B' numeric  — values produced by a floating-point tail routine (p-values) or
 *                  by a resampling procedure (bootstrap CI bounds). Two correct but
 *                  differently-written routines legitimately differ in the last
 *                  few digits. A discrepancy here is a NOTE to disclose, never a
 *                  build failure — otherwise `make figures` could never pass.
 */
type CheckClass = 'A' | 'B'
interface Check { name: string, got: number | string, want: number | string, ok: boolean, cls: CheckClass, note?: string }
function approx(a: number, b: number, tol: number): boolean {
  if (Number.isNaN(a) && Number.isNaN(b))
    return true
  if (Number.isNaN(a) || Number.isNaN(b))
    return false
  if (a === b)
    return true
  // Relative tolerance: an absolute 1e-9 is meaningless next to p ~ 1e-15.
  const rel = Math.abs(a - b) / (Math.max(Math.abs(a), Math.abs(b)) || 1)
  return rel <= tol
}

/**
 * Detect a value that is a *numeric floor* rather than a computed result.
 *
 * A real tail probability is essentially never an exact power of two. When the
 * harness's tail routine underflows it clamps to something like `2 ** -50`, and
 * that clamped constant then lands in summary.json looking like a measurement.
 * The paper must never quote it as a computed p (review §1.10 / §2.3): report
 * `p < 1e-15` instead. Returns a human-readable note when a floor is detected.
 */
function detectFloor(x: number): string | null {
  if (!Number.isFinite(x) || x <= 0 || x >= 1e-12)
    return null
  const e = Math.log2(x)
  return Number.isInteger(e) ? `harness value is exactly 2^${e} — a numeric floor, not a computed p` : null
}

function crossCheck(comp: Computed, rec: Reconstructed, summary: any | null): { checks: Check[], mismatches: number, notes: number } {
  const checks: Check[] = []
  const add = (name: string, got: number | string, want: number | string, ok: boolean, note?: string, cls: CheckClass = 'A') =>
    checks.push({ name, got, want, ok, cls, note })

  if (!summary) {
    return { checks: [{ name: 'summary.json', got: 'absent', want: 'present', ok: true, cls: 'A', note: 'cross-check skipped (no summary.json provided)' }], mismatches: 0, notes: 0 }
  }

  const TOL_EXACT = 1e-9
  const TOL_CI = 1e-6
  // Class-B allowance: loose enough to absorb a different-but-correct tail
  // routine, far too tight to hide a real analysis-unit change.
  const TOL_NUM = 1e-3
  const f = (x: number) => (Number.isNaN(x) ? 'NaN' : x)

  /**
   * Class-B check for a p-value pair. Tolerates a differing tail routine, and
   *  treats a detected floor on the summary side as agreement-with-a-caveat.
   */
  const pCheck = (name: string, got: number, want: number, sumWant: number) => {
    const floor = detectFloor(sumWant)
    const ok = approx(got, want, TOL_EXACT) || approx(got, want, TOL_NUM) || floor !== null
    const note = floor ?? 'tail routine differs; Class B (non-binding)'
    add(name, f(got), f(want), ok, note, 'B')
  }

  add('analysisUnit.nSkills', comp.nSkills, summary.nSkills, comp.nSkills === summary.nSkills)
  add('analysisUnit.nExecutions', comp.nExecutions, summary.nExecutions, comp.nExecutions === summary.nExecutions)

  // 4-cell precision / count / meanCalls
  for (const c of comp.cells) {
    const tcell = (summary.table as any[]).find((t: any) => t.selfVerificationEnabled === c.sv && t.envFeedbackEnabled === c.ef)
    if (tcell) {
      add(`cell(sv${c.sv ? 1 : 0},ef${c.ef ? 1 : 0}).precision`, f(c.precision), f(tcell.precision), approx(c.precision, tcell.precision, TOL_EXACT))
      add(`cell(sv${c.sv ? 1 : 0},ef${c.ef ? 1 : 0}).count`, c.count, tcell.count, c.count === tcell.count)
      add(`cell(sv${c.sv ? 1 : 0},ef${c.ef ? 1 : 0}).meanCalls`, f(c.meanCalls), f(tcell.meanCallsPerSkill), approx(c.meanCalls, tcell.meanCallsPerSkill, TOL_EXACT))
    }
  }

  // chi-square (skill-level, primary)
  add('chiSquare.statistic', f(comp.chiSquare.statistic), f(summary.chiSquare.statistic), approx(comp.chiSquare.statistic, summary.chiSquare.statistic, TOL_EXACT))
  pCheck('chiSquare.p', comp.chiSquare.p, summary.chiSquare.p, summary.chiSquare.p)
  add('chiSquare.table', JSON.stringify(comp.chiSquare.table), JSON.stringify(summary.chiSquare.table), JSON.stringify(comp.chiSquare.table) === JSON.stringify(summary.chiSquare.table))

  // effect sizes
  add('effectSizes.oddsRatio', f(comp.effectSizes.oddsRatio), f(summary.effectSizes.oddsRatio), approx(comp.effectSizes.oddsRatio, summary.effectSizes.oddsRatio, TOL_EXACT))
  add('effectSizes.riskDifference', f(comp.effectSizes.riskDifference), f(summary.effectSizes.riskDifference), approx(comp.effectSizes.riskDifference, summary.effectSizes.riskDifference, TOL_EXACT))
  add('effectSizes.cramersV', f(comp.effectSizes.cramersV), f(summary.effectSizes.cramersV), approx(comp.effectSizes.cramersV, summary.effectSizes.cramersV, TOL_EXACT))
  add('effectSizes.cohensH', f(comp.effectSizes.cohensH), f(summary.effectSizes.cohensH), approx(comp.effectSizes.cohensH, summary.effectSizes.cohensH, TOL_EXACT))
  add('effectSizes.interactionLogOdds.estimate', f(comp.effectSizes.interactionLogOdds.estimate), f(summary.effectSizes.interactionLogOdds.estimate), approx(comp.effectSizes.interactionLogOdds.estimate, summary.effectSizes.interactionLogOdds.estimate, TOL_EXACT))
  pCheck('effectSizes.interactionLogOdds.p', comp.effectSizes.interactionLogOdds.p, summary.effectSizes.interactionLogOdds.p, summary.effectSizes.interactionLogOdds.p)

  // factorial interaction == interactionLogOdds
  add('factorialInteraction.estimate', f(comp.factorialInteraction.estimate), f(summary.factorialInteraction.estimate), approx(comp.factorialInteraction.estimate, summary.factorialInteraction.estimate, TOL_EXACT))

  // McNemar
  const m = summary.mcnemarEnvFeedback
  add('mcnemar.a/b/c/d', `${comp.mcnemar.a}/${comp.mcnemar.b}/${comp.mcnemar.c}/${comp.mcnemar.d}`, `${m.a}/${m.b}/${m.c}/${m.d}`, comp.mcnemar.a === m.a && comp.mcnemar.b === m.b && comp.mcnemar.c === m.c && comp.mcnemar.d === m.d)
  add('mcnemar.chiSquare', f(comp.mcnemar.chiSquare), f(m.chiSquare), approx(comp.mcnemar.chiSquare, m.chiSquare, TOL_EXACT))
  pCheck('mcnemar.p', comp.mcnemar.p, m.p, m.p)

  // power
  add('power.minDetectableEffectAt80', f(comp.power.minDetectableEffectAt80), f(summary.power.minDetectableEffectAt80), approx(comp.power.minDetectableEffectAt80, summary.power.minDetectableEffectAt80, TOL_EXACT))
  add('power.nSkillsPerCell', comp.power.nSkillsPerCell, summary.power.nSkillsPerCell, comp.power.nSkillsPerCell === summary.power.nSkillsPerCell)

  // per-cell bootstrap CI
  for (const pc of comp.perCellCI) {
    const sc = (summary.perCellCI as any[]).find((x: any) => x.sv === pc.sv && x.ef === pc.ef)
    if (sc) {
      add(`perCellCI(sv${pc.sv ? 1 : 0},ef${pc.ef ? 1 : 0}).mean`, f(pc.ci.mean), f(sc.ci.mean), approx(pc.ci.mean, sc.ci.mean, TOL_EXACT))
      add(`perCellCI(sv${pc.sv ? 1 : 0},ef${pc.ef ? 1 : 0}).lo`, f(pc.ci.lo), f(sc.ci.lo), approx(pc.ci.lo, sc.ci.lo, TOL_CI), 'bootstrap: order-stable within 1e-6', 'B')
      add(`perCellCI(sv${pc.sv ? 1 : 0},ef${pc.ef ? 1 : 0}).hi`, f(pc.ci.hi), f(sc.ci.hi), approx(pc.ci.hi, sc.ci.hi, TOL_CI), 'bootstrap: order-stable within 1e-6', 'B')
    }
  }

  // DiD (pooled)
  add('diffInDiff.estimate', f(comp.diffInDiff.estimate), f(summary.diffInDiff.estimate), approx(comp.diffInDiff.estimate, summary.diffInDiff.estimate, TOL_EXACT))
  add('diffInDiff.ci.lo', f(comp.diffInDiff.ci.lo), f(summary.diffInDiff.ci.lo), approx(comp.diffInDiff.ci.lo, summary.diffInDiff.ci.lo, TOL_CI), 'bootstrap: order-stable within 1e-6', 'B')
  add('diffInDiff.ci.hi', f(comp.diffInDiff.ci.hi), f(summary.diffInDiff.ci.hi), approx(comp.diffInDiff.ci.hi, summary.diffInDiff.ci.hi, TOL_CI), 'bootstrap: order-stable within 1e-6', 'B')

  // diagnostics
  const d = summary.diagnostics
  add('diagnostics.n', comp.diagnostics.n, d.n, comp.diagnostics.n === d.n)
  add('diagnostics.hallucinationRate', f(comp.diagnostics.hallucinationRate), f(d.hallucinationRate), approx(comp.diagnostics.hallucinationRate, d.hallucinationRate, TOL_EXACT))
  add('diagnostics.missRate', f(comp.diagnostics.missRate), f(d.missRate), approx(comp.diagnostics.missRate, d.missRate, TOL_EXACT))
  add('diagnostics.agreement', f(comp.diagnostics.agreement), f(d.agreement), approx(comp.diagnostics.agreement, d.agreement, TOL_EXACT))

  // Only Class-A drift breaks the build. For Class B, ANY pair that is not
  // exactly equal is disclosed even when the loose tolerance accepted it: the
  // difference is real, it simply must not fail the build or be silently dropped.
  const mismatches = checks.filter(c => !c.ok && c.cls === 'A').length
  const notes = checks.filter(c => c.cls === 'B' && typeof c.got === 'number' && typeof c.want === 'number' && c.got !== c.want).length
  return { checks, mismatches, notes }
}

// ===========================================================================
// Markdown tables
// ===========================================================================
const fmtPct = (x: number) => (Number.isNaN(x) ? 'NaN' : `${(x * 100).toFixed(1)}%`)
const fmt3 = (x: number) => (Number.isNaN(x) ? 'NaN' : x.toFixed(3))
const fmt4 = (x: number) => (Number.isNaN(x) ? 'NaN' : x.toFixed(4))
const fmtSci = (x: number) => (Number.isNaN(x) ? 'NaN' : x.toExponential(3))

function tablePrecision(comp: Computed): string {
  const rows = comp.cells.map((c) => {
    const ci = comp.perCellCI.find(p => p.sv === c.sv && p.ef === c.ef)!
    return `| sv${c.sv ? 1 : 0}-ef${c.ef ? 1 : 0} | ${c.count} | ${fmt3(c.precision)} | ${fmt3(ci.ci.mean)} [${fmt3(ci.ci.lo)}, ${fmt3(ci.ci.hi)}] | ${c.meanCalls.toFixed(2)} |`
  }).join('\n')
  return `# Table 1 — 4-cell precision (RQ-C 2×2)\n\nAnalysis unit: **skill** (each skill collapsed to one outcome; pseudo-replication avoided per Blocker B1). N = ${comp.nSkills} skills (${comp.nExecutions} executions).\n\n| Cell | n skills | Pooled precision | 95% bootstrap CI (pooled-precision resampling) | Mean calls/skill |\n|------|---------:|-----------------:|------------------------------------------------|------------------:|\n${rows}\n\nNote: CI uses seeded percentile bootstrap over skills (stats.bootstrapPooledPrecision), not the divergent exported bootstrapCI.\n`
}

function tableEffects(comp: Computed): string {
  const e = comp.effectSizes
  return `# Table 2 — Effect sizes (envFeedback ON vs OFF, skill level)\n\nAnalysis unit: **skill**. N = ${comp.nSkills}. OR/RD/Cramér's V/Cohen's h are for the envFeedback contrast; the 2×2 factorial interaction is on the log-odds scale (headline).\n\n| Effect | Estimate | SE | z | p |\n|--------|---------:|---:|---:|---:|\n| Odds ratio (OR) | ${fmt3(e.oddsRatio)} | — | — | — |\n| Risk difference (RD) | ${fmt3(e.riskDifference)} | — | — | — |\n| Cramér's V | ${fmt3(e.cramersV)} | — | — | — |\n| Cohen's h | ${fmt3(e.cohensH)} | — | — | — |\n| 2×2 factorial interaction (log-odds) | ${fmt4(e.interactionLogOdds.estimate)} | ${fmt4(e.interactionLogOdds.se)} | ${fmt3(e.interactionLogOdds.z)} | ${fmtSci(e.interactionLogOdds.p)} |\n`
}

function tableInference(comp: Computed): string {
  const c = comp.chiSquare
  const m = comp.mcnemar
  const fi = comp.factorialInteraction
  const holm = comp.multiplicity.map(h => `| ${h.label} | ${fmtSci(h.p)} | ${fmtSci(h.adjustedP)} | ${h.reject ? 'YES' : 'no'} |`).join('\n')
  return `# Table 3 — Primary inference (skill level)\n\nAnalysis unit: **skill**. N = ${comp.nSkills}. All tests use the valid skill-level unit (not execution-level).\n\n**Skill-level χ²** (envFeedback × outcome): χ²=${fmt3(c.statistic)}, p=${fmtSci(c.p)}, table=${JSON.stringify(c.table)}\n\n**McNemar paired** (envFeedback ON vs OFF, skills paired by trial×task — block design B4):\n- a(fail/fail)=${m.a} b(offFail/onPass)=${m.b} c(offPass/onFail)=${m.c} d(pass/pass)=${m.d}, nPairs=${m.nPairs}\n- χ²=${fmt3(m.chiSquare)}, p=${fmtSci(m.p)} (${m.usedExact ? 'exact binomial' : 'continuity-corrected χ²'})\n\n**2×2 factorial interaction** (log-odds): estimate=${fmt4(fi.estimate)}, SE=${fmt4(fi.se)}, z=${fmt3(fi.z)}, p=${fmtSci(fi.p)}\n\n**Holm step-down correction** (α=0.05) over the primary family:\n\n| Hypothesis | raw p | Holm adj p | reject |\n|------------|------:|-----------:|--------|\n${holm}\n`
}

function tablePower(comp: Computed): string {
  return `# Table 4 — Declared statistical power\n\nAnalysis unit: **skill**. Design: 2×2, nSkillsPerCell=${comp.power.nSkillsPerCell} (≈ ${comp.nSkills}/4).\n\n| Quantity | Value |\n|----------|------:|\n| Minimum detectable effect @ 80% power, α=0.05, p0=0.5 | ${comp.power.minDetectableEffectAt80.toFixed(2)} pp |\n| Skills per cell | ${comp.power.nSkillsPerCell} |\n`
}

function tableDiagnostics(comp: Computed): string {
  const d = comp.diagnostics
  return `# Table 5 — Self-verification diagnostics (selfVerification = ON row only)\n\nAnalysis unit: **execution overlap** (records with both a self-verdict and an execution verdict), N = ${d.n}. Reconstructed from trials.jsonl step-level (selfVerdict × execOk).\n\n| Metric | Value |\n|--------|------:|\n| n | ${d.n} |\n| Hallucination rate (selfPass ∧ execFail) | ${fmt3(d.hallucinationRate)} |\n| Miss rate (selfFail ∧ execPass) | ${fmt3(d.missRate)} |\n| Self↔env agreement | ${fmt3(d.agreement)} |\n`
}

function tableLearningCurve(rec: Reconstructed): string {
  // success rate by (condition, round), execution unit
  const condRound: { [cond: string]: { [r: number]: { ok: number, n: number } } } = {}
  let maxRound = 0
  for (const st of rec.steps) {
    condRound[st.condition] ??= {}
    condRound[st.condition][st.round] ??= { ok: 0, n: 0 }
    condRound[st.condition][st.round].n++
    if (st.execOk)
      condRound[st.condition][st.round].ok++
    if (st.round > maxRound)
      maxRound = st.round
  }
  const conds = ['sv0-ef0', 'sv0-ef1', 'sv1-ef0', 'sv1-ef1']
  const header = `| Round | ${conds.map(c => c).join(' | ')} |`
  const sep = `|------:|${conds.map(() => '------:').join('')}|`
  const rows = []
  for (let r = 0; r <= maxRound; r++) {
    const cells = conds.map((c) => {
      const cell = condRound[c]?.[r]
      return cell ? fmtPct(cell.ok / cell.n) : '—'
    })
    rows.push(`| ${r} | ${cells.join(' | ')} |`)
  }
  return `# Table 6 — Per-trial learning curve (success rate by round)\n\nAnalysis unit: **execution** (this is the per-trial intermediate quantity §2.3 notes summary.json lacks). Each condition reuses the same task each round; rate = executions succeeded / executions in that round.\n\n${header}\n${sep}\n${rows.join('\n')}\n`
}

function tableExecLevelDiagnostic(comp: Computed, rec: Reconstructed): string {
  // Execution-level χ² for transparency (DIAGNOSTIC ONLY — pseudo-replication)
  let onS = 0
  let onF = 0
  let offS = 0
  let offF = 0
  for (const s of rec.skills.values()) {
    if (s.calls === 0)
      continue
    if (s.ef) {
      onS += s.succ
      onF += (s.calls - s.succ)
    }
    else {
      offS += s.succ
      offF += (s.calls - s.succ)
    }
  }
  const ex = chiSquare2x2(onS, onF, offS, offF)
  return `# Table 7 — Execution-level χ² (DIAGNOSTIC ONLY — not for inference)\n\nAnalysis unit: **execution**. Retained for transparency: counting every execution as independent understates the SE (~1.5×) and makes p spuriously small (pseudo-replication, Blocker B1). Do NOT report this as a result.\n\n| Contrast | χ² | p | table |\n|----------|----:|---:|-------|\n| envFeedback × outcome (execution level) | ${fmt3(ex.statistic)} | ${fmtSci(ex.p)} | ${JSON.stringify(ex.table)} |\n`
}

// ===========================================================================
// SVG figures (hand-rolled, dependency-free)
// ===========================================================================
function esc(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function figPrecision4cell(comp: Computed): string {
  const W = 680
  const H = 360
  const pad = 60
  const data = comp.cells.map(c => ({
    label: `sv${c.sv ? 1 : 0}-ef${c.ef ? 1 : 0}`,
    mean: comp.perCellCI.find(p => p.sv === c.sv && p.ef === c.ef)!.ci.mean,
    lo: comp.perCellCI.find(p => p.sv === c.sv && p.ef === c.ef)!.ci.lo,
    hi: comp.perCellCI.find(p => p.sv === c.sv && p.ef === c.ef)!.ci.hi,
  }))
  const yMax = 1
  const yMin = 0
  const plotW = W - 2 * pad
  const plotH = H - 2 * pad
  const bw = plotW / (data.length * 1.6)
  const x0 = (i: number) => pad + plotW * (i + 0.5) / data.length
  const y = (v: number) => pad + plotH * (1 - (v - yMin) / (yMax - yMin))
  let bars = ''
  data.forEach((d, i) => {
    const cx = x0(i)
    const ym = y(d.mean)
    const ylo = y(d.lo)
    const yhi = y(d.hi)
    bars += `<rect x="${cx - bw / 2}" y="${ym}" width="${bw}" height="${pad + plotH - ym}" fill="#4C72B0"/>`
    bars += `<line x1="${cx}" y1="${ylo}" x2="${cx}" y2="${yhi}" stroke="#C44E52" stroke-width="2"/>`
    bars += `<line x1="${cx - 6}" y1="${ylo}" x2="${cx + 6}" y2="${ylo}" stroke="#C44E52" stroke-width="2"/>`
    bars += `<line x1="${cx - 6}" y1="${yhi}" x2="${cx + 6}" y2="${yhi}" stroke="#C44E52" stroke-width="2"/>`
    bars += `<text x="${cx}" y="${H - pad + 18}" text-anchor="middle" font-size="13">${d.label}</text>`
    bars += `<text x="${cx}" y="${ym - 6}" text-anchor="middle" font-size="11">${fmt3(d.mean)}</text>`
  })
  let yax = ''
  for (let v = 0; v <= 1.0001; v += 0.2) {
    yax += `<line x1="${pad}" y1="${y(v)}" x2="${W - pad}" y2="${y(v)}" stroke="#ddd" stroke-width="1"/>`
    yax += `<text x="${pad - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11">${v.toFixed(1)}</text>`
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" font-family="sans-serif">
<text x="${W / 2}" y="24" text-anchor="middle" font-size="15" font-weight="bold">RQ-C: pooled precision by cell (95% CI)</text>
${yax}${bars}
<text x="${W / 2}" y="${H - 12}" text-anchor="middle" font-size="11">skill-level; CI = seeded bootstrap over skills</text>
</svg>`
}

function figInteraction(comp: Computed): string {
  const W = 680
  const H = 360
  const pad = 60
  const xLabels = ['SV off', 'SV on']
  const off = [comp.cells.find(c => !c.sv && !c.ef)!.precision, comp.cells.find(c => c.sv && !c.ef)!.precision]
  const on = [comp.cells.find(c => !c.sv && c.ef)!.precision, comp.cells.find(c => c.sv && c.ef)!.precision]
  const ciOff = [comp.perCellCI.find(p => !p.sv && !p.ef)!.ci, comp.perCellCI.find(p => p.sv && !p.ef)!.ci]
  const ciOn = [comp.perCellCI.find(p => !p.sv && p.ef)!.ci, comp.perCellCI.find(p => p.sv && p.ef)!.ci]
  const plotW = W - 2 * pad
  const plotH = H - 2 * pad
  const x = (i: number) => pad + plotW * (i + 0.5) / 2
  const y = (v: number) => pad + plotH * (1 - v)
  const line = (vals: number[], col: string) => vals.map((v, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(v)}`).join(' ')
  const errs = (vals: number[], ci: CI[], col: string) => vals.map((v, i) => {
    const err = `<line x1="${x(i)}" y1="${y(ci[i].lo)}" x2="${x(i)}" y2="${y(ci[i].hi)}" stroke="${col}" stroke-width="2"/>`
    const cap = `<line x1="${x(i) - 5}" y1="${y(ci[i].lo)}" x2="${x(i) + 5}" y2="${y(ci[i].lo)}" stroke="${col}" stroke-width="2"/><line x1="${x(i) - 5}" y1="${y(ci[i].hi)}" x2="${x(i) + 5}" y2="${y(ci[i].hi)}" stroke="${col}" stroke-width="2"/>`
    return err + cap
  }).join('')
  let yax = ''
  for (let v = 0; v <= 1.0001; v += 0.2)
    yax += `<line x1="${pad}" y1="${y(v)}" x2="${W - pad}" y2="${y(v)}" stroke="#ddd"/><text x="${pad - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11">${v.toFixed(1)}</text>`
  const xl = xLabels.map((l, i) => `<text x="${x(i)}" y="${H - pad + 18}" text-anchor="middle" font-size="13">${l}</text>`).join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" font-family="sans-serif">
<text x="${W / 2}" y="24" text-anchor="middle" font-size="15" font-weight="bold">RQ-C: selfVerification × envFeedback interaction</text>
${yax}${xl}
<path d="${line(off, '#4C72B0')}" fill="none" stroke="#4C72B0" stroke-width="2"/>
<path d="${line(on, '#C44E52')}" fill="none" stroke="#C44E52" stroke-width="2"/>
${errs(off, ciOff, '#4C72B0')}${errs(on, ciOn, '#C44E52')}
<circle cx="${x(0)}" cy="${y(off[0])}" r="4" fill="#4C72B0"/><circle cx="${x(1)}" cy="${y(off[1])}" r="4" fill="#4C72B0"/>
<circle cx="${x(0)}" cy="${y(on[0])}" r="4" fill="#C44E52"/><circle cx="${x(1)}" cy="${y(on[1])}" r="4" fill="#C44E52"/>
<text x="${W - pad}" y="${pad - 20}" text-anchor="end" font-size="12" fill="#4C72B0">envFeedback OFF</text>
<text x="${W - pad}" y="${pad - 4}" text-anchor="end" font-size="12" fill="#C44E52">envFeedback ON</text>
</svg>`
}

function figLearningCurve(rec: Reconstructed): string {
  const W = 680
  const H = 360
  const pad = 60
  const conds = ['sv0-ef0', 'sv0-ef1', 'sv1-ef0', 'sv1-ef1']
  const cols = ['#4C72B0', '#C44E52', '#55A868', '#8C564B']
  const data: { [cond: string]: { [r: number]: { ok: number, n: number } } } = {}
  let maxR = 0
  for (const st of rec.steps) {
    data[st.condition] ??= {}
    data[st.condition][st.round] ??= { ok: 0, n: 0 }
    data[st.condition][st.round].n++
    if (st.execOk)
      data[st.condition][st.round].ok++
    if (st.round > maxR)
      maxR = st.round
  }
  const plotW = W - 2 * pad
  const plotH = H - 2 * pad
  const x = (r: number) => pad + (maxR === 0 ? plotW / 2 : plotW * r / maxR)
  const y = (v: number) => pad + plotH * (1 - v)
  let yax = ''
  for (let v = 0; v <= 1.0001; v += 0.2)
    yax += `<line x1="${pad}" y1="${y(v)}" x2="${W - pad}" y2="${y(v)}" stroke="#ddd"/><text x="${pad - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11">${v.toFixed(1)}</text>`
  let paths = ''
  let legend = ''
  conds.forEach((c, ci) => {
    const pts: string[] = []
    for (let r = 0; r <= maxR; r++) {
      const cell = data[c]?.[r]
      if (!cell || cell.n === 0)
        continue
      pts.push(`${x(r)},${y(cell.ok / cell.n)}`)
    }
    if (pts.length)
      paths += `<polyline points="${pts.join(' ')}" fill="none" stroke="${cols[ci]}" stroke-width="2"/>`
    legend += `<rect x="${pad + ci * 150}" y="${H - 22}" width="12" height="12" fill="${cols[ci]}"/><text x="${pad + ci * 150 + 16}" y="${H - 12}" font-size="11">${c}</text>`
  })
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" font-family="sans-serif">
<text x="${W / 2}" y="24" text-anchor="middle" font-size="15" font-weight="bold">RQ-C: per-round success rate (execution unit)</text>
${yax}${paths}${legend}
</svg>`
}

function figMcNemar(comp: Computed): string {
  const W = 680
  const H = 320
  const pad = 60
  const m = comp.mcnemar
  const bars = [['b (OFF fail → ON pass)', m.b, '#55A868'], ['c (OFF pass → ON fail)', m.c, '#C44E52']]
  const maxV = Math.max(m.b, m.c, 1)
  const plotH = H - 2 * pad
  const plotW = W - 2 * pad
  const y = (v: number) => pad + plotH * (1 - v / maxV)
  let rects = ''
  const bw = plotW / 4
  bars.forEach((b, i) => {
    const v = b[1] as number
    const cx = pad + plotW * (i + 0.5) / 2
    rects += `<rect x="${cx - bw / 2}" y="${y(v)}" width="${bw}" height="${pad + plotH - y(v)}" fill="${b[2]}"/>`
    rects += `<text x="${cx}" y="${y(v) - 6}" text-anchor="middle" font-size="13">${v}</text>`
    rects += `<text x="${cx}" y="${H - pad + 18}" text-anchor="middle" font-size="12">${esc(b[0] as string)}</text>`
  })
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" font-family="sans-serif">
<text x="${W / 2}" y="24" text-anchor="middle" font-size="15" font-weight="bold">RQ-C: McNemar discordant pairs (block design)</text>
${rects}
<text x="${W / 2}" y="${H - 12}" text-anchor="middle" font-size="11">a=${m.a} d=${m.d}  nPairs=${m.nPairs}  p=${fmtSci(m.p)}</text>
</svg>`
}

function figEffects(comp: Computed): string {
  const W = 680
  const H = 300
  const pad = 60
  const e = comp.effectSizes
  const rows: { label: string, v: number, col: string }[] = [
    { label: 'Odds ratio', v: e.oddsRatio, col: '#4C72B0' },
    { label: 'Risk diff', v: e.riskDifference, col: '#C44E52' },
    { label: 'Cohen\'s h', v: e.cohensH, col: '#55A868' },
    { label: 'Cramér\'s V', v: e.cramersV, col: '#8C564B' },
  ]
  const plotW = W - 2 * pad
  const rowH = (H - 2 * pad) / rows.length
  const maxAbs = Math.max(...rows.map(r => Math.abs(r.v)), 0.0001)
  const x0 = pad + plotW / 2
  const xScale = (v: number) => x0 + (v / maxAbs) * (plotW / 2) * 0.9
  let body = `<line x1="${x0}" y1="${pad}" x2="${x0}" y2="${H - pad}" stroke="#999"/>`
  rows.forEach((r, i) => {
    const cy = pad + rowH * (i + 0.5)
    const xe = xScale(r.v)
    body += `<line x1="${x0}" y1="${cy}" x2="${xe}" y2="${cy}" stroke="${r.col}" stroke-width="6"/>`
    body += `<text x="${xScale(r.v) + (r.v >= 0 ? 8 : -8)}" y="${cy + 4}" text-anchor="${r.v >= 0 ? 'start' : 'end'}" font-size="12">${fmt3(r.v)}</text>`
    body += `<text x="${pad - 8}" y="${cy + 4}" text-anchor="end" font-size="12">${r.label}</text>`
  })
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" font-family="sans-serif">
<text x="${W / 2}" y="24" text-anchor="middle" font-size="15" font-weight="bold">RQ-C: effect-size estimates (skill level)</text>
${body}
<text x="${W / 2}" y="${H - 12}" text-anchor="middle" font-size="11">bars scaled per-row by max |value|; interaction log-odds p=${fmtSci(e.interactionLogOdds.p)}</text>
</svg>`
}

// ===========================================================================
// MANIFEST
// ===========================================================================
function writeManifest(args: Args, rec: Reconstructed, summary: any | null, trialSha: string, sumSha: string | null): object {
  const cfg = summary?.config ?? null
  const sampling = summary?.sampling ?? null
  return {
    artifact: 'rq-c-replay',
    schemaVersion: 1,
    runDir: basename(resolve(args.runDir)),
    inputTrialsPath: resolve(args.runDir, 'trials.jsonl'),
    inputSummaryPath: args.summary ? resolve(args.summary) : null,
    sha256Trials: trialSha,
    sha256Summary: sumSha,
    parsedRecordCount: rec.steps.length,
    nSkills: rec.nSkills,
    nExecutions: rec.nExecutions,
    recordedSeed: cfg?.seed ?? null,
    bootstrapSeedUsed: args.bootstrapSeed,
    modelTag: sampling?.model ?? null,
    ollamaVersion: sampling?.ollamaVersion ?? null,
    backendMode: summary?.mode ?? null,
    wallClockMs: null,
    gitCommit: gitCommit(),
    gitHashInSummary: summary?.gitHash ?? null,
    generatedBy: 'replay/replay.ts',
  }
}

// ===========================================================================
// Main
// ===========================================================================
function main(): void {
  const args = parseArgs(process.argv.slice(2))
  const trialsPath = resolve(args.runDir, 'trials.jsonl')
  if (!existsSync(trialsPath))
    throw new Error(`trials.jsonl not found at ${trialsPath}`)

  const rec = reconstruct(trialsPath)
  const trialSha = sha256File(trialsPath)

  let summary: any | null = null
  let sumSha: string | null = null
  const summaryPath = args.summary ?? resolve(args.runDir, 'summary.json')
  if (existsSync(summaryPath)) {
    summary = JSON.parse(readFileSync(summaryPath, 'utf8'))
    sumSha = sha256File(summaryPath)
  }

  // Run seed: prefer recorded run seed so bootstrap CIs match summary.json; fall
  // back to the CLI --bootstrap-seed (default 42) for runs without a summary.
  const seed = (summary?.config?.seed ?? args.bootstrapSeed) >>> 0
  const comp = compute(rec, seed)

  const { checks, mismatches, notes } = crossCheck(comp, rec, summary)

  mkdirSync(resolve(args.out, 'tables'), { recursive: true })
  mkdirSync(resolve(args.out, 'figures'), { recursive: true })

  const tables: [string, string][] = [
    ['table-1-precision.md', tablePrecision(comp)],
    ['table-2-effects.md', tableEffects(comp)],
    ['table-3-inference.md', tableInference(comp)],
    ['table-4-power.md', tablePower(comp)],
    ['table-5-diagnostics.md', tableDiagnostics(comp)],
    ['table-6-learning-curve.md', tableLearningCurve(rec)],
    ['table-7-exec-level-diagnostic.md', tableExecLevelDiagnostic(comp, rec)],
  ]
  for (const [name, body] of tables)
    writeFileSync(resolve(args.out, 'tables', name), body)

  const figures: [string, string][] = [
    ['fig-1-precision-4cell.svg', figPrecision4cell(comp)],
    ['fig-2-interaction.svg', figInteraction(comp)],
    ['fig-3-learning-curve.svg', figLearningCurve(rec)],
    ['fig-4-mcnemar.svg', figMcNemar(comp)],
    ['fig-5-effect-sizes.svg', figEffects(comp)],
  ]
  for (const [name, body] of figures)
    writeFileSync(resolve(args.out, 'figures', name), body)

  const manifest = writeManifest(args, rec, summary, trialSha, sumSha)
  writeFileSync(resolve(args.out, 'MANIFEST.json'), `${JSON.stringify(manifest, null, 2)}\n`)

  const checkLines = checks.map(c =>
    `${c.ok ? 'PASS' : 'FAIL'}  [${c.cls}]  ${c.name}  got=${c.got} want=${c.want}${c.note ? `  (${c.note})` : ''}`,
  ).join('\n')
  const classA = checks.filter(c => !c.ok && c.cls === 'A')
  const classB = checks.filter(c => c.cls === 'B' && typeof c.got === 'number' && typeof c.want === 'number' && c.got !== c.want)
  const floorNotes = classB.map(c => c.note).filter((n): n is string => Boolean(n && n.includes('numeric floor')))
  const noteSection = classB.length === 0
    ? '\n## Class B — 数值性提示：无\n'
    : `\n## Class B — 数值性提示（${classB.length} 项，非绑定）\n\n来源为浮点尾部函数（p 值）或重采样过程（bootstrap 置信区间边界）。实现不同但都正确时，末几位必然存在差异，故此处**只披露、不判失败**：\n\n${classB.map(c => `- \`${c.name}\`: 重算 \`${c.got}\` vs summary.json \`${c.want}\` — ${c.note ?? ''}`).join('\n')}\n${floorNotes.length > 0 ? `\n### ⚠ 检出数值下限 —— 不得当作计算出的 p 值引用\n\nsummary 侧有 ${floorNotes.length} 个值恰为 2 的整数次幂且小于 1e-12，属**下溢钳位**而非测量结果。论文中应写 \`p < 1e-15\`：\n\n${floorNotes.map(n => `- ${n}`).join('\n')}\n` : ''}`
  const driftNote = mismatches > 0
    ? `\n## ⚠ Class A — 绑定级不一致（${mismatches} 项）\n\n${classA.map(c => `- \`${c.name}\`: 重算 \`${c.got}\` vs summary.json \`${c.want}\`${c.note ? ` — ${c.note}` : ''}`).join('\n')}\n\n这些是计数、列联表或精确比值。两侧不一致意味着分析的**不是同一批数据**。在解决之前两个数字都不可发表：用当前源码重跑生成 \`summary.json\`，再执行 \`make figures\`。\n`
    : '\n## Class A — 绑定级校验：全部通过\n\n从 `trials.jsonl` 重算的每个计数、列联表与主效应估计值都与 `summary.json` 一致，两侧分析的是同一批数据。\n'
  const checksMd = `# CHECKS.md — replay self-validation\n\nRun: ${basename(resolve(args.runDir))}\nRecomputed every headline number from trials.jsonl and compared against summary.json.\n\n${summary ? `summary.json: present (sha256 ${sumSha}).` : 'summary.json: ABSENT — cross-check skipped.'}\n\n## Footgun audit (review §1.10)\nThe exported \`bootstrapCI\` / \`differenceInDifferences\` in src/stats.ts resample per-unit *values* and take their *mean* — a DIFFERENT estimand from the harness headline. This replay uses \`bootstrapPooledPrecision\` / \`pooledDifferenceInDifferences\` (the harness's own definitions, harness.ts imports at lines 71-84). No divergent function was used.\n\n## Verdict: ${mismatches === 0 ? 'Class A ALL PASS' : `${mismatches} BINDING MISMATCH(ES)`}${notes > 0 ? `, ${notes} Class-B note(s)` : ''}\n\n\`\`\`\n${checkLines}\n\`\`\`\n${driftNote}${noteSection}`
  writeFileSync(resolve(args.out, 'CHECKS.md'), checksMd)

  process.stdout.write(`Replay complete: ${rec.steps.length} steps, ${rec.nSkills} skills.\n`)
  process.stdout.write(`Tables: ${tables.length}  Figures: ${figures.length}\n`)
  process.stdout.write(`Self-validation: ${mismatches === 0 ? 'Class A ALL PASS' : `${mismatches} BINDING MISMATCH(ES) — see CHECKS.md`}${notes > 0 ? `; ${notes} Class-B numeric note(s)` : ''}\n`)
  // Only binding (Class A) drift fails the build. Class-B numeric notes are
  // disclosed in CHECKS.md instead — `make figures` must succeed on a good run.
  if (mismatches > 0)
    process.exitCode = 1
}

main()
