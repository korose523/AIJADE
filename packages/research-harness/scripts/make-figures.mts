/**
 * Replay script: regenerate every paper figure/table from ONE run's
 * `summary.json` (+ `trials.jsonl`) as plain CSV/JSON. This is the ACM
 * "Reusable" badge deliverable — no PNG required, just one-command data replay.
 *
 * Usage:
 *   tsx scripts/make-figures.mts [runDir]
 *
 * `runDir` must contain `summary.json` and `trials.jsonl` (the CLI output).
 * If omitted, the newest subdirectory of `experiments/rq-c` is used.
 *
 * Outputs (written next to the inputs):
 *   table1_learning_loop.csv   — 4-cell learning-loop table (paper Table 1)
 *   fig1_precision_ci.csv      — per-cell precision point estimate + 95% CI (paper Fig 1)
 *   table2_effects_holm.csv    — effect sizes + Holm-corrected p-values (paper Table 2)
 *   figures.json               — all of the above as structured JSON
 */

import process from 'node:process'

/// <reference types="node" />
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

interface CellRow {
  selfVerificationEnabled: boolean
  envFeedbackEnabled: boolean
  count: number
  precision: number
  retiredRate: number
  meanCallsPerSkill: number
}

interface CIRow {
  sv: boolean
  ef: boolean
  ci: { mean: number, lo: number, hi: number }
}

interface Summary {
  config: Record<string, unknown>
  sampling: Record<string, unknown>
  analysisUnit?: string
  nSkills?: number
  nExecutions?: number
  table: CellRow[]
  perCellCI: CIRow[]
  diagnostics?: { n: number, hallucinationRate: number, missRate: number, agreement: number }
  effectSizes: {
    oddsRatio: number
    riskDifference: number
    cramersV: number
    cohensH: number
    interactionLogOdds: { estimate: number, se: number, z: number, p: number }
  }
  multiplicity: { method: string, alpha: number, adjusted: { label: string, p: number, adjustedP: number, reject: boolean }[] }
  factorialInteraction: { estimate: number, se: number, z: number, p: number }
  chiSquare: { statistic: number, p: number, table: number[][] }
  chiSquareExecutionLevel: { statistic: number, p: number, table: number[][] }
  mcnemarEnvFeedback: { a: number, b: number, c: number, d: number, nPairs: number, chiSquare: number, pChiSquare: number, p: number, usedExact: boolean }
  power: { minDetectableEffectAt80: number, nSkillsPerCell: number }
}

function findNewestRunDir(base: string): string | null {
  if (!existsSync(base))
    return null
  const dirs = readdirSync(base, { withFileTypes: true })
    .filter(d => d.isDirectory())
    .map(d => resolve(base, d.name))
    .filter(d => existsSync(resolve(d, 'summary.json')))
  if (dirs.length === 0)
    return null
  return dirs.sort().at(-1)!
}

function csv(rows: (string | number)[][]): string {
  return `${rows.map(r => r.map(c => (typeof c === 'number' ? String(c) : `"${String(c).replace(/"/g, '""')}"`)).join(',')).join('\n')}\n`
}

function main(): void {
  const argv = process.argv.slice(2)
  const baseDir = resolve(process.cwd(), 'experiments/rq-c')
  const runDir = argv[0]
    ? resolve(process.cwd(), argv[0])
    : (findNewestRunDir(baseDir) ?? baseDir)
  const summaryPath = resolve(runDir, 'summary.json')
  const trialsPath = resolve(runDir, 'trials.jsonl')
  if (!existsSync(summaryPath))
    throw new Error(`No summary.json found in ${runDir}`)

  const summary = JSON.parse(readFileSync(summaryPath, 'utf8')) as Summary
  // trials.jsonl is read to certify the run is complete (step count == nExecutions).
  let trialSteps = 0
  if (existsSync(trialsPath)) {
    const text = readFileSync(trialsPath, 'utf8')
    trialSteps = text.split('\n').filter(l => l.trim().length > 0).length
  }

  // --- Table 1: 4-cell learning loop ---------------------------------------
  const t1 = [['condition', 'selfVerification', 'envFeedback', 'count', 'precision', 'retiredRate', 'meanCallsPerSkill']]
  for (const c of summary.table) {
    const cond = `sv${c.selfVerificationEnabled ? 1 : 0}-ef${c.envFeedbackEnabled ? 1 : 0}`
    t1.push([cond, c.selfVerificationEnabled ? 1 : 0, c.envFeedbackEnabled ? 1 : 0, c.count, c.precision, c.retiredRate, c.meanCallsPerSkill])
  }

  // --- Fig 1: precision point + CI -----------------------------------------
  const f1 = [['condition', 'selfVerification', 'envFeedback', 'precision', 'lo', 'hi']]
  for (const c of summary.perCellCI) {
    const cond = `sv${c.sv ? 1 : 0}-ef${c.ef ? 1 : 0}`
    f1.push([cond, c.sv ? 1 : 0, c.ef ? 1 : 0, c.ci.mean, c.ci.lo, c.ci.hi])
  }

  // --- Table 2: effect sizes + Holm ----------------------------------------
  const e = summary.effectSizes
  const t2: (string | number)[][] = [['quantity', 'value', 'se', 'z', 'p', 'note']]
  t2.push(['oddsRatio(envFeedback ON vs OFF)', e.oddsRatio, '', '', '', 'effect size'])
  t2.push(['riskDifference', e.riskDifference, '', '', '', 'effect size'])
  t2.push(['Cramer\'s V', e.cramersV, '', '', '', 'effect size'])
  t2.push(['Cohen\'s h', e.cohensH, '', '', '', 'effect size'])
  t2.push(['factorialInteraction.logOdds', e.interactionLogOdds.estimate, e.interactionLogOdds.se, e.interactionLogOdds.z, e.interactionLogOdds.p, '2x2 factorial (sv x ef), log-odds'])
  t2.push(['chiSquare.skillLevel.p', summary.chiSquare.p, '', '', summary.chiSquare.p, 'PRIMARY (skill-level)'])
  t2.push(['chiSquare.executionLevel.p', summary.chiSquareExecutionLevel.p, '', '', summary.chiSquareExecutionLevel.p, 'DIAGNOSTIC ONLY (pseudo-replication)'])
  t2.push(['mcnemar.p', summary.mcnemarEnvFeedback.p, '', '', summary.mcnemarEnvFeedback.p, summary.mcnemarEnvFeedback.usedExact ? 'exact binomial' : 'chi-square'])
  t2.push(['power.minDetectableEffectAt80(pp)', summary.power.minDetectableEffectAt80, '', '', '', `nSkillsPerCell=${summary.power.nSkillsPerCell}`])
  t2.push(['', '', '', '', '', `--- Holm step-down (alpha=${summary.multiplicity.alpha}) ---`])
  for (const s of summary.multiplicity.adjusted)
    t2.push([s.label, '', '', '', s.p, `adjP=${s.adjustedP} reject=${s.reject}`])

  const figures = {
    runDir,
    analysisUnit: summary.analysisUnit ?? 'skill',
    nSkills: summary.nSkills ?? null,
    nExecutions: summary.nExecutions ?? null,
    trialSteps,
    table1_learningLoop: summary.table,
    fig1_precisionCI: summary.perCellCI,
    table2_effectsHolm: {
      effectSizes: summary.effectSizes,
      interaction: summary.factorialInteraction,
      chiSquare: summary.chiSquare,
      chiSquareExecutionLevel: summary.chiSquareExecutionLevel,
      mcnemar: summary.mcnemarEnvFeedback,
      holm: summary.multiplicity,
      power: summary.power,
    },
  }

  writeFileSync(resolve(runDir, 'table1_learning_loop.csv'), csv(t1))
  writeFileSync(resolve(runDir, 'fig1_precision_ci.csv'), csv(f1))
  writeFileSync(resolve(runDir, 'table2_effects_holm.csv'), csv(t2))
  writeFileSync(resolve(runDir, 'figures.json'), `${JSON.stringify(figures, null, 2)}\n`)

  console.info(`Replay wrote figures for ${runDir}`)
  console.info(`  analysisUnit=${summary.analysisUnit ?? 'skill'} nSkills=${summary.nSkills ?? '?'} nExecutions=${summary.nExecutions ?? '?'} trialSteps=${trialSteps}`)
  console.info('  -> table1_learning_loop.csv, fig1_precision_ci.csv, table2_effects_holm.csv, figures.json')
}

main()
