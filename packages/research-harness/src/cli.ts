#!/usr/bin/env tsx
/**
 * RQ-C 2x2 experiment CLI.
 *
 * Usage:
 *   tsx src/cli.ts --trials 30 --seed 42 --backend mock --rounds 5 --out experiments/rq-c
 *
 * Automatically sweeps all four conditions (selfVerification x envFeedback), each
 * with a deterministic seed derived from the master seed. Writes:
 *   <out>/<runId>/trials.jsonl   — one line per execution step
 *   <out>/<runId>/summary.json   — 4-cell table + diagnostics + all CIs + fingerprint
 * and prints a human-readable summary to stdout.
 *
 * Honesty: when `--backend mock` the summary is stamped `"mode": "simulation"`
 * with an explicit note. Mock hallucination/miss rates validate the ESTIMATOR,
 * not the phenomenon — they must never be read as empirical results.
 *
 * Reproducibility: the Ollama backend locks sampling to temperature 0 + a seed
 * derived from `--seed` (see `createOllamaBackend`); the summary stamps
 * model / temperature / seed / ollamaVersion / git commit / config fingerprint
 * so a single run is uniquely identifiable (ACM "Reproduced" badge).
 */

import type { LLMBackend } from './backends'
import type { ExperimentResult, RunOptions } from './harness'

import process from 'node:process'

/// <reference types="node" />
import { execSync } from 'node:child_process'
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { createMockBackend, createOllamaBackend, ollamaVersion } from './backends'
import {
  conditionId,
  CONDITIONS,
  PREREGISTRATION,
  runExperiment,
} from './harness'
import { minDetectableEffectProportion, powerForEffectProportion } from './stats'

interface CliConfig {
  trials: number
  seed: number
  backend: 'mock' | 'ollama'
  model?: string
  rounds: number
  pCorrect: number
  tasks: number
  out: string
  pruneThreshold: number
  pruneMinCalls: number
  ollamaBaseUrl: string
}

function parseArgs(argv: string[]): CliConfig {
  const cfg: CliConfig = {
    trials: PREREGISTRATION.trials,
    seed: PREREGISTRATION.seed,
    backend: 'mock',
    rounds: PREREGISTRATION.rounds,
    pCorrect: 0.5,
    tasks: PREREGISTRATION.nTasks,
    out: 'experiments/rq-c',
    pruneThreshold: PREREGISTRATION.pruneThreshold,
    pruneMinCalls: PREREGISTRATION.pruneMinCalls,
    ollamaBaseUrl: 'http://localhost:11434',
  }
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]
    const next = () => {
      const v = argv[++i]
      if (v === undefined)
        throw new Error(`Missing value for ${a}`)
      return v
    }
    switch (a) {
      case '--trials':
        cfg.trials = Number.parseInt(next(), 10)
        break
      case '--seed':
        cfg.seed = Number.parseInt(next(), 10)
        break
      case '--backend':
        cfg.backend = next() as CliConfig['backend']
        break
      case '--model':
        cfg.model = next()
        break
      case '--rounds':
        cfg.rounds = Number.parseInt(next(), 10)
        break
      case '--p-correct':
        cfg.pCorrect = Number.parseFloat(next())
        break
      case '--tasks':
        cfg.tasks = Number.parseInt(next(), 10)
        break
      case '--out':
        cfg.out = next()
        break
      case '--prune-threshold':
        cfg.pruneThreshold = Number.parseFloat(next())
        break
      case '--min-calls':
        cfg.pruneMinCalls = Number.parseInt(next(), 10)
        break
      case '--ollama-base-url':
        cfg.ollamaBaseUrl = next()
        break
      case '--help':
      case '-h':
        printHelp()
        process.exit(0)
        break
      default:
        throw new Error(`Unknown argument: ${a}`)
    }
  }
  if (cfg.backend !== 'mock' && cfg.backend !== 'ollama')
    throw new Error(`--backend must be 'mock' or 'ollama'`)
  if (cfg.backend === 'ollama' && !cfg.model)
    throw new Error(`--backend ollama requires --model`)
  return cfg
}

function printHelp(): void {
  process.stdout.write(`RQ-C 2x2 harness

  --trials N        trials per condition (default ${PREREGISTRATION.trials})
  --seed N          master seed (default ${PREREGISTRATION.seed})
  --backend mock|ollama
  --model NAME      Ollama model (required for ollama)
  --rounds N        task-revisit rounds (default ${PREREGISTRATION.rounds})
  --p-correct P     mock P(correct generation) (default 0.5)
  --tasks N         distinct tasks per trial (default ${PREREGISTRATION.nTasks})
  --out DIR         output directory (default experiments/rq-c)
  --prune-threshold P   prune precision threshold (default ${PREREGISTRATION.pruneThreshold})
  --min-calls N     min calls before pruning (default ${PREREGISTRATION.pruneMinCalls})
  --ollama-base-url URL   (default http://localhost:11434)
`)
}

function gitHash(): string {
  try {
    return execSync('git rev-parse HEAD', { cwd: process.cwd() }).toString().trim()
  }
  catch {
    return 'unknown'
  }
}

function fingerprint(cfg: CliConfig): string {
  const payload = {
    trials: cfg.trials,
    seed: cfg.seed,
    backend: cfg.backend,
    model: cfg.model ?? null,
    rounds: cfg.rounds,
    pCorrect: cfg.pCorrect,
    tasks: cfg.tasks,
    pruneThreshold: cfg.pruneThreshold,
    pruneMinCalls: cfg.pruneMinCalls,
    domain: 'executable',
  }
  // Stable, order-independent serialization -> stable fingerprint.
  const json = JSON.stringify(payload, Object.keys(payload).sort())
  let h = 0x811C9DC5
  for (let i = 0; i < json.length; i++) {
    h ^= json.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/** Deterministic seed handed to Ollama so a given `--seed` is reproducible. */
function deriveSamplingSeed(seed: number): number {
  return (Math.imul(seed ^ 0x9E3779B9, 0x85EBCA6B) >>> 0)
}

function buildBackend(cfg: CliConfig): { backend: LLMBackend, samplingSeed: number } {
  if (cfg.backend === 'ollama') {
    return {
      backend: createOllamaBackend({
        model: cfg.model!,
        baseUrl: cfg.ollamaBaseUrl,
        sampling: { temperature: 0, seed: deriveSamplingSeed(cfg.seed) },
      }),
      samplingSeed: deriveSamplingSeed(cfg.seed),
    }
  }
  return {
    backend: createMockBackend(cfg.seed, { pCorrect: cfg.pCorrect, hallucination: 0.3, miss: 0.1, seed: cfg.seed }),
    samplingSeed: cfg.seed,
  }
}

function ciStr(ci: { mean: number, lo: number, hi: number }): string {
  if (!Number.isFinite(ci.mean))
    return 'NaN [NaN, NaN]'
  return `${ci.mean.toFixed(3)} [${ci.lo.toFixed(3)}, ${ci.hi.toFixed(3)}]`
}

function printSummary(
  cfg: CliConfig,
  result: ExperimentResult,
  runId: string,
  outDir: string,
  sampling: { model: string | null, temperature: number | null, seed: number, ollamaVersion: string | null },
): void {
  const mode = cfg.backend === 'mock' ? 'simulation' : 'live'
  const lines: string[] = []
  lines.push('')
  lines.push('════════════════════════════════════════════════════════════════════')
  lines.push(' RQ-C 2×2 — selfVerification × envFeedback (domain: executable)')
  lines.push(` runId=${runId}`)
  lines.push(` MODE: ${mode.toUpperCase()}${mode === 'simulation'
    ? '  ⚠ mock backend — numbers validate the MECHANISM/ESTIMATOR, NOT the phenomenon.'
    : ''}`)
  if (mode === 'simulation') {
    lines.push('   The reported hallucinationRate / missRate are INJECTED simulation params;')
    lines.push('   do NOT cite them as empirical findings. Use --backend ollama for real rates.')
  }
  lines.push(` fingerprint=${fingerprint(cfg)}  git=${gitHash()}`)
  lines.push(` sampling: model=${sampling.model ?? 'n/a'} temperature=${sampling.temperature ?? 'n/a'}`
    + ` seed=${sampling.seed} ollamaVersion=${sampling.ollamaVersion ?? 'n/a'}`)
  lines.push(` analysisUnit=${result.analysisUnit}  nSkills=${result.nSkills}  nExecutions=${result.nExecutions}`)
  lines.push('────────────────────────────────────────────────────────────────────')

  // 4-cell table. Order: [sv0ef0, sv0ef1, sv1ef0, sv1ef1]
  const cell = (sv: boolean, ef: boolean) => result.table.find(c => c.selfVerificationEnabled === sv && c.envFeedbackEnabled === ef)!
  const ci = (sv: boolean, ef: boolean) => result.perCellCI.find(c => c.sv === sv && c.ef === ef)!.ci

  lines.push('')
  lines.push(' Precision (cumulative success rate) — point estimate [95% bootstrap CI]')
  lines.push('                          envFeedback OFF              envFeedback ON')
  lines.push(` selfVerification OFF    ${ciStr(ci(false, false)).padEnd(28)} ${ciStr(ci(false, true))}`)
  lines.push(` selfVerification ON     ${ciStr(ci(true, false)).padEnd(28)} ${ciStr(ci(true, true))}`)

  lines.push('')
  lines.push(' Full 4-cell table (count | precision | retiredRate | meanCalls)')
  for (const sv of [false, true]) {
    for (const ef of [false, true]) {
      const c = cell(sv, ef)
      lines.push(
        `   ${conditionId({ selfVerification: sv, envFeedback: ef }).padEnd(10)}`
        + ` n=${String(c.count).padEnd(5)} prec=${c.precision.toFixed(3).padEnd(7)}`
        + ` retired=${c.retiredRate.toFixed(3).padEnd(7)} calls=${c.meanCallsPerSkill.toFixed(2)}`,
      )
    }
  }

  lines.push('')
  lines.push(' Self-verification diagnostics (selfVerification = ON row only)')
  const d = result.diagnostics
  lines.push(`   n=${d.n}  hallucinationRate=${Number.isNaN(d.hallucinationRate) ? 'NaN' : d.hallucinationRate.toFixed(3)}`
    + `  missRate=${Number.isNaN(d.missRate) ? 'NaN' : d.missRate.toFixed(3)}`
    + `  agreement=${Number.isNaN(d.agreement) ? 'NaN' : d.agreement.toFixed(3)}`)
  if (mode === 'simulation')
    lines.push('   (simulation: expected ≈ injected hallucination=0.30, miss=0.10)')

  lines.push('')
  lines.push(' 2×2 factorial interaction (log-odds scale) — HEADLINE EFFECT')
  const fi = result.factorialInteraction
  lines.push(`   log-odds interaction = ${fi.estimate.toFixed(4)}  se=${fi.se.toFixed(4)}`
    + `  z=${fi.z.toFixed(3)}  p=${fi.p.toFixed(4)}`)
  lines.push(`   (old "DiD" on pooled precision kept for reference: ${ciStr(result.diffInDiff.ci)})`)

  lines.push('')
  lines.push(' Effect sizes — envFeedback (ON vs OFF) at skill level')
  const e = result.effectSizes
  lines.push(`   oddsRatio=${e.oddsRatio.toFixed(3)}  riskDifference=${e.riskDifference.toFixed(3)}`
    + `  Cramér's V=${e.cramersV.toFixed(3)}  Cohen's h=${e.cohensH.toFixed(3)}`)

  lines.push('')
  lines.push(' Holm step-down correction (alpha=0.05) over primary inferences')
  for (const s of result.multiplicity.adjusted) {
    lines.push(`   ${s.label.padEnd(34)} p=${s.p.toFixed(4)}  adjP=${s.adjustedP.toFixed(4)}`
      + `  reject=${s.reject}`)
  }

  lines.push('')
  lines.push(' Chi-square: envFeedback (rows) × outcome (cols) — SKILL-LEVEL (primary)')
  lines.push(`   χ²=${result.chiSquare.statistic.toFixed(3)}  p=${result.chiSquare.p.toFixed(4)}`
    + `  table=${JSON.stringify(result.chiSquare.table)}`)
  lines.push('   [DIAGNOSTIC ONLY — NOT for inference] execution-level chi-square (pseudo-replication):')
  lines.push(`   χ²=${result.chiSquareExecutionLevel.statistic.toFixed(3)}`
    + `  p=${result.chiSquareExecutionLevel.p.toFixed(4)}  table=${JSON.stringify(result.chiSquareExecutionLevel.table)}`)

  lines.push('')
  lines.push(' McNemar paired test — envFeedback ON vs OFF (skills paired by trial × task)')
  const m = result.mcnemarEnvFeedback
  lines.push(`   a(fail/fail)=${m.a} b(offFail/onPass)=${m.b} c(offPass/onFail)=${m.c} d(pass/pass)=${m.d}`
    + ` nPairs=${m.nPairs}`)
  lines.push(`   χ²=${m.chiSquare.toFixed(3)}  pChiSq=${m.pChiSquare.toFixed(4)}`
    + `  p${m.usedExact ? '(exact)' : '(chiSq)'}=${m.p.toFixed(4)}`)

  lines.push('')
  lines.push(' Declared power (skill-level, α=0.05, 80% power, p0=0.5)')
  lines.push(`   minDetectableEffectAt80 = ${result.power.minDetectableEffectAt80.toFixed(2)} pp`
    + `  nSkillsPerCell=${result.power.nSkillsPerCell}`)
  lines.push(`   achieved power: Δ=10pp -> ${result.power.powerAtDelta10pp.toFixed(2)}`
    + `   Δ=5pp -> ${result.power.powerAtDelta5pp.toFixed(2)}`)
  lines.push('   Reference grid (derived, not hand-typed — see stats.powerForEffectProportion):')
  for (const n of [240, 360]) {
    const mde = minDetectableEffectProportion(n) * 100
    const p10 = powerForEffectProportion(0.10, n)
    const p5 = powerForEffectProportion(0.05, n)
    lines.push(`     n/cell=${n}: MDE=${mde.toFixed(1)}pp  power(Δ10pp)=${p10.toFixed(2)}`
      + `  power(Δ5pp)=${p5.toFixed(2)}`)
  }
  lines.push('   CONCLUSION: at the registered scale the design can only resolve effects of ~>=10pp.')

  lines.push('')
  lines.push(' Loop liveness (regeneration -> recovery) — CAUSAL-PATH EVIDENCE')
  for (const l of result.loopDiagnostics) {
    lines.push(`   ${l.condition.padEnd(10)} regenerations=${String(l.loop.regenerations).padEnd(5)}`
      + ` withSignal=${String(l.loop.regenerationsWithSignal).padEnd(5)}`
      + ` recoveries=${String(l.loop.recoveries).padEnd(5)}`
      + ` recoveredRate=${Number.isNaN(l.loop.recoveredRate) ? 'n/a' : l.loop.recoveredRate.toFixed(3)}`)
  }
  const dg = result.degeneracy
  lines.push(`   degeneracy: allCellsIdentical=${dg.allCellsIdenticalPrecision}`
    + ` manipulationReachable=${dg.manipulationReachable}`)
  lines.push(`   -> ${dg.note}`)
  if (!dg.manipulationReachable) {
    lines.push('   ⚠⚠⚠ THIS RUN CARRIES NO INFORMATION ABOUT THE 2x2. Do not report it as a null result.')
  }

  if (result.preregistrationDeviation.length > 0) {
    lines.push('')
    lines.push(' ⚠ PREREGISTRATION DEVIATION (selective-inference guard, B3):')
    for (const d of result.preregistrationDeviation)
      lines.push(`     - ${d}`)
  }

  lines.push('════════════════════════════════════════════════════════════════════')
  lines.push(` artifacts: ${resolve(outDir)}/{trials.jsonl,summary.json}`)
  lines.push('')
  process.stdout.write(lines.join('\n'))
}

async function main(): Promise<void> {
  const cfg = parseArgs(process.argv.slice(2))

  const runId = `rq-c-s${cfg.seed}-${cfg.backend}-t${cfg.trials}-r${cfg.rounds}`
  const outDir = resolve(cfg.out, runId)
  mkdirSync(outDir, { recursive: true })

  // trials.jsonl 采用逐条追加写（checkpoint）：真实 LLM 后端一次全量运行要数千次
  // 请求、耗时以小时计，中途崩溃若只在结尾落盘会丢失全部已完成样本。
  const trialsPath = resolve(outDir, 'trials.jsonl')
  writeFileSync(trialsPath, '')
  let nSteps = 0
  const t0 = Date.now()
  const { backend, samplingSeed } = buildBackend(cfg)
  const version = cfg.backend === 'ollama' ? await ollamaVersion(cfg.ollamaBaseUrl) : null

  const runOpts: RunOptions = {
    backend,
    trials: cfg.trials,
    rounds: cfg.rounds,
    seed: cfg.seed,
    nTasks: cfg.tasks,
    pruneThreshold: cfg.pruneThreshold,
    pruneMinCalls: cfg.pruneMinCalls,
    now: () => 0,
    onStep: (step) => {
      const line = JSON.stringify(step)
      appendFileSync(trialsPath, `${line}\n`)
      if (++nSteps % 200 === 0) {
        const secs = (Date.now() - t0) / 1000
        process.stdout.write(`[progress] ${nSteps} steps  ${secs.toFixed(0)}s  ${(nSteps / secs).toFixed(2)} steps/s\n`)
      }
    },
  }

  const result = await runExperiment(runOpts)

  // trials.jsonl 已由 onStep 逐条追加写入，此处不再重复落盘。
  const sampling = {
    mode: cfg.backend === 'mock' ? 'simulation' : 'live',
    model: cfg.backend === 'ollama' ? cfg.model ?? null : null,
    temperature: cfg.backend === 'ollama' ? 0 : null,
    seed: samplingSeed,
    ollamaVersion: version,
  }
  const summary = {
    mode: cfg.backend === 'mock' ? 'simulation' : 'live',
    simulationNote: cfg.backend === 'mock'
      ? 'Mock backend: injected hallucination=0.30, miss=0.10. These validate the estimator, not the phenomenon. Do not cite as empirical.'
      : undefined,
    config: {
      trials: cfg.trials,
      seed: cfg.seed,
      backend: cfg.backend,
      model: cfg.model ?? null,
      rounds: cfg.rounds,
      pCorrect: cfg.pCorrect,
      tasks: cfg.tasks,
      pruneThreshold: cfg.pruneThreshold,
      pruneMinCalls: cfg.pruneMinCalls,
      domain: 'executable',
    },
    sampling,
    analysisUnit: result.analysisUnit,
    nSkills: result.nSkills,
    nExecutions: result.nExecutions,
    fingerprint: fingerprint(cfg),
    gitHash: gitHash(),
    conditions: CONDITIONS.map(c => conditionId(c)),
    table: result.table,
    perCellCI: result.perCellCI,
    diagnostics: result.diagnostics,
    diffInDiff: result.diffInDiff,
    effectSizes: result.effectSizes,
    multiplicity: result.multiplicity,
    factorialInteraction: result.factorialInteraction,
    chiSquare: result.chiSquare,
    chiSquareSelfVerification: result.chiSquareSelfVerification,
    chiSquareExecutionLevel: result.chiSquareExecutionLevel,
    mcnemarEnvFeedback: result.mcnemarEnvFeedback,
    power: result.power,
    powerReference: [240, 360].map(n => ({
      nPerCell: n,
      minDetectableEffectAt80pp: Number((minDetectableEffectProportion(n) * 100).toFixed(2)),
      powerAtDelta10pp: Number(powerForEffectProportion(0.10, n).toFixed(4)),
      powerAtDelta5pp: Number(powerForEffectProportion(0.05, n).toFixed(4)),
    })),
    preregistrationDeviation: result.preregistrationDeviation,
    degeneracy: result.degeneracy,
    loopDiagnostics: result.loopDiagnostics,
  }
  writeFileSync(resolve(outDir, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`)

  printSummary(cfg, result, runId, outDir, { model: sampling.model, temperature: sampling.temperature, seed: sampling.seed, ollamaVersion: sampling.ollamaVersion })
}

main().catch((err) => {
  process.stderr.write(`FATAL: ${err instanceof Error ? err.stack ?? err.message : String(err)}\n`)
  process.exit(1)
})
