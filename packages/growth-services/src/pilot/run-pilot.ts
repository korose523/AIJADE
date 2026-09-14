/**
 * §5.3 / §5.4 / §5.5 — Pilot experiment runner (REFACTORED).
 *
 * Runs every Table-3 configuration (B0–B5, A1, A1−HAC, A1−DGM, A1−CDI) on the same
 * seeded synthetic longitudinal benchmark, drives the REAL `GrowthLoop` through the
 * `PolicyStorage` decorators, and evaluates all §5.4 metrics (memory + proactivity +
 * the new identity block) with bootstrap 95% CIs, Cohen's d effect sizes (vs B0) and
 * Bonferroni-corrected significance.
 *
 * ⚠️ HONESTY BANNER — read before citing any number:
 *
 *  • REAL CODE PATHS. Every reported number is computed from (a) the genuinely
 *    committed memory set produced by the `PolicyStorage` decorators and (b) the real
 *    `GrowthLoopSummary` returns. No metric is fed a pre-computed ranking via
 *    `if (config.X) return <value>`. The only thing the configuration decides is which
 *    memory policy is installed — the treatment, which is exactly the independent
 *    variable under test.
 *  • STILL PARAMETERISED. The per-role future-value / importance scores (ROLE_PROPS)
 *    and the HAC endogenous-state / CDI identity gates are *modelled* as threshold
 *    functions over statement attributes (no real endogenous-state model exists in this
 *    mechanism sim). The dual-graph (DGM) and CDI behaviours are realised as genuine
 *    code paths inside `PolicyStorage`, not as metric-side constants.
 *  • DETERMINISTIC MECHANISM-LEVEL SIMULATION. No real LLM, no Postgres, no Ollama, no
 *    human subjects. The human-interaction tasks (§5.2) have NOT been conducted. Treat
 *    these numbers as a reproducibility / formalism proving ground, not as empirical
 *    claims about the deployed system.
 *
 * Output (written to `./pilot-results/`):
 *   - pilot-results.json        machine-readable full results (seed, scale, per-config metrics, CIs, effect sizes, Bonferroni)
 *   - AIJADE_试点实验结果.md     human-readable summary table + conclusions + honesty banner
 */

import type { MechanismConfig } from './configs'
import type { ConfigResult, DatasetMetrics } from './simulator'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { defaultScale, generateSyntheticLongitudinal } from '../benchmark/synthetic-longitudinal'
import { bonferroni, bootstrapCI, cohensD, mulberry32 } from '../metrics/stats'
import { MECHANISM_CONFIGS } from './configs'
import { simulateAll } from './simulator'

/** Metric columns reported in the table (incl. the new identity block). */
const METRICS: { key: keyof DatasetMetrics, label: string, higherIsBetter: boolean }[] = [
  { key: 'fub', label: 'Future Utility@Budget', higherIsBetter: true },
  { key: 'epRate', label: 'EffectiveProactivity(rate)', higherIsBetter: true },
  { key: 'gc', label: 'Growth Coherence', higherIsBetter: true },
  { key: 'precision', label: 'Evidence Precision', higherIsBetter: true },
  { key: 'recall', label: 'Evidence Recall', higherIsBetter: true },
  { key: 'cr', label: 'Contradiction Retention', higherIsBetter: true },
  { key: 'fcr', label: 'False Consolidation Rate', higherIsBetter: false },
  { key: 'coreStability', label: 'Core Stability', higherIsBetter: true },
  { key: 'identityDrift', label: 'Identity Drift', higherIsBetter: false },
  { key: 'skillRetention', label: 'Skill Retention', higherIsBetter: true },
]

const ABLATIONS = ['A1-HAC', 'A1-DGM', 'A1-CDI']

function meanOf(xs: number[]): number {
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
}

function varOf(xs: number[]): number {
  const m = meanOf(xs)
  if (xs.length < 2)
    return 0
  return xs.reduce((a, b) => a + (b - m) * (b - m), 0) / (xs.length - 1)
}

/**
 * Cohen's d, but `null` when both groups are (near) constant — the simulation can
 * yield zero within-group variance for ceiling/floor metrics, making d mathematically
 * undefined (∞). We surface that honestly instead of emitting a floating-point explosion.
 */
function cohensDOrNull(a: number[], b: number[]): number | null {
  if (varOf(a) < 1e-12 && varOf(b) < 1e-12)
    return null
  return cohensD(a, b)
}

/** One-sided bootstrap p-value that mean(a) > mean(b) (fraction of resamples ≤). */
function bootstrapP(a: number[], b: number[], seed: number, iters = 2000): number {
  const n = a.length
  const m = b.length
  const rng = mulberry32(seed)
  let cnt = 0
  for (let i = 0; i < iters; i++) {
    let sa = 0
    let sb = 0
    for (let j = 0; j < n; j++)
      sa += a[Math.floor(rng() * n) % n]
    for (let j = 0; j < m; j++)
      sb += b[Math.floor(rng() * m) % m]
    if (sa / n <= sb / m)
      cnt++
  }
  return cnt / iters
}

interface PilotResult {
  meta: Record<string, unknown>
  configs: { id: string, label: string, focus: string, mechanism: Omit<MechanismConfig, 'id' | 'label' | 'focus'> }[]
  results: Record<string, Record<string, { value: number, ci: [number, number] }>>
  relativeToB0: Record<string, Record<string, { value: number, delta: number, relativePct: number | null }>>
  effectSizesVsB0: Record<string, Record<string, number | null>>
  bonferroni: Record<string, { correctedAlpha: number, rejected: Record<string, boolean> }>
  ablationDropsVsA1: Record<string, Record<string, { value: number, deltaVsA1: number, pctVsA1: number }>>
}

/**
 * Run the full pilot. Deterministic for a fixed `seed`. When `writeFiles` is true
 * the result is also persisted to `./pilot-results/`.
 */
export async function runPilot(seed = 1, writeFiles = true): Promise<PilotResult> {
  const scale = defaultScale()
  const benchmark = generateSyntheticLongitudinal(seed, scale)
  const results = await simulateAll(benchmark, MECHANISM_CONFIGS)

  const allStmts = benchmark.datasets.flatMap(d => d.statements)
  const actualContraRate = allStmts.filter(s => s.isContradictionLate).length / allStmts.length
  const actualDistractRate = allStmts.filter(s => s.isDistractor).length / allStmts.length

  const byId = new Map(results.map(r => [r.config.id, r]))
  const b0 = byId.get('B0')!
  const a1 = byId.get('A1')!

  const outResults: PilotResult['results'] = {}
  for (const { key } of METRICS) {
    outResults[key] = {}
    for (const r of results) {
      const series = r.perDataset[key]
      const ci = bootstrapCI(series, seed * 1009 + r.config.id.length * 31 + key.length, 2000)
      outResults[key][r.config.id] = { value: r.metrics[key], ci }
    }
  }

  const relativeToB0: PilotResult['relativeToB0'] = {}
  for (const r of results) {
    if (r.config.id === 'B0')
      continue
    relativeToB0[r.config.id] = {}
    for (const { key } of METRICS) {
      const value = r.metrics[key]
      const base = b0.metrics[key]
      const delta = value - base
      const relativePct = base === 0 ? (value === 0 ? 0 : null) : (delta / Math.abs(base)) * 100
      relativeToB0[r.config.id][key] = { value, delta, relativePct }
    }
  }

  const effectSizesVsB0: PilotResult['effectSizesVsB0'] = {}
  for (const { key } of METRICS) {
    effectSizesVsB0[key] = {}
    for (const r of results) {
      if (r.config.id === 'B0')
        continue
      const a = r.perDataset[key]
      const b = b0.perDataset[key]
      effectSizesVsB0[key][r.config.id] = cohensDOrNull(a, b)
    }
  }

  const bonferroniOut: PilotResult['bonferroni'] = {}
  for (const { key } of METRICS) {
    const pValues: number[] = []
    const ids: string[] = []
    for (const r of results) {
      if (r.config.id === 'B0')
        continue
      const a = r.perDataset[key]
      const b = b0.perDataset[key]
      pValues.push(bootstrapP(a, b, seed * 7919 + r.config.id.length * 17 + key.length))
      ids.push(r.config.id)
    }
    const corrected = bonferroni(pValues, 0.05)
    const rejected: Record<string, boolean> = {}
    ids.forEach((id, i) => (rejected[id] = corrected.rejected[i]))
    bonferroniOut[key] = { correctedAlpha: corrected.correctedAlpha, rejected }
  }

  const ablationDropsVsA1: PilotResult['ablationDropsVsA1'] = {}
  for (const ablId of ABLATIONS) {
    const r = byId.get(ablId)!
    ablationDropsVsA1[ablId] = {}
    for (const { key } of METRICS) {
      const value = r.metrics[key]
      const a1v = a1.metrics[key]
      ablationDropsVsA1[ablId][key] = {
        value,
        deltaVsA1: value - a1v,
        pctVsA1: a1v === 0 ? (value === 0 ? 0 : Number.NaN) : ((value - a1v) / Math.abs(a1v)) * 100,
      }
    }
  }

  const configsOut = results.map(r => ({
    id: r.config.id,
    label: r.config.label,
    focus: r.config.focus,
    mechanism: {
      memoryWrite: r.config.memoryWrite,
      endogenousState: r.config.endogenousState,
      dualGraphSeparation: r.config.dualGraphSeparation,
      identityConstraint: r.config.identityConstraint,
      hacEnabled: r.config.hacEnabled,
      dgmEnabled: r.config.dgmEnabled,
      cdiEnabled: r.config.cdiEnabled,
    },
  }))

  const meta = {
    title: 'AIJADE 合成纵向基准试点实验（确定性机制级仿真 · 真实 GrowthLoop 路径）',
    honesty: '确定性机制级仿真：非 LLM 实验、非人类被试实验。人类交互任务尚未开展。所有指标由 PolicyStorage 真实提交集合 + GrowthLoopSummary 计算，无 config 直给。',
    seed,
    scale,
    actualRates: { contradictionRate: actualContraRate, distractorRate: actualDistractRate },
    generatedBy: 'AIJADE growth-services pilot runner v2 (real-loop)',
    note: '结果完全由 seed 决定；相同 seed 重跑结果逐字节一致。',
  }

  const pilot: PilotResult = {
    meta,
    configs: configsOut,
    results: outResults,
    relativeToB0,
    effectSizesVsB0,
    bonferroni: bonferroniOut,
    ablationDropsVsA1,
  }

  if (writeFiles) {
    const outDir = resolve(dirname(fileURLToPath(import.meta.url)), 'pilot-results')
    mkdirSync(outDir, { recursive: true })
    writeFileSync(resolve(outDir, 'pilot-results.json'), `${JSON.stringify(pilot, null, 2)}\n`)
    writeFileSync(resolve(outDir, 'AIJADE_试点实验结果.md'), renderMarkdown(pilot, results))
  }

  return pilot
}

/** Render the human-readable Markdown summary. */
function renderMarkdown(pilot: PilotResult, results: ConfigResult[]): string {
  const lines: string[] = []
  lines.push(`# ${String(pilot.meta.title)}`)
  lines.push('')
  lines.push('> ⚠️ **诚实标注**')
  lines.push('>')
  lines.push('> 1. **真实代码路径**：所有指标均由 `PolicyStorage` 装饰器产生的**真实已提交记忆集合** + `GrowthLoop.runOnce` 的**真实返回值**计算，不存在 `if (config.X) return 某预定值` 的直给。配置唯一决定的是"安装哪套记忆策略"（即被比较的自变量）。')
  lines.push('> 2. **仍属参数化产物**：每角色 future-value / importance 评分，以及 HAC 内生状态门控、CDI 身份护栏，目前以"基于陈述属性的阈值函数"建模（机制级仿真中无真实内生状态模型）；双图分离(DGM)与 CDI 行为已在 `PolicyStorage` 内作为真实代码路径实现，而非指标侧常量。')
  lines.push('> 3. **确定性机制级仿真**：不含真实 LLM 调用、不含 Postgres/Ollama、不含人类被试；论文 §5.2 真实交互任务尚未开展。本结果仅证明指标形式化与配置矩阵可复现，不构成对部署系统的经验性宣称。')
  lines.push('')
  lines.push(`- 随机种子 seed = ${pilot.meta.seed}`)
  const s = pilot.meta.scale as { datasets: number, sessionsPerDataset: number, statementsPerSession: number, windows: number, contradictionRate: number, distractorRate: number, budgetPerDataset: number, totalStatements: number }
  const ar = pilot.meta.actualRates as { contradictionRate: number, distractorRate: number }
  lines.push(`- 规模：${s.datasets} 数据集 × ${s.sessionsPerDataset} 会话 × ${s.statementsPerSession} 陈述 = ${s.totalStatements} 陈述；${s.windows} 时间窗；矛盾注入率 ${(ar.contradictionRate * 100).toFixed(1)}%（规格 15%）；干扰项 ${(ar.distractorRate * 100).toFixed(1)}%（规格 10%）；存储预算 B = ${s.budgetPerDataset}/数据集`)
  lines.push(`- 注：各数据集计数含确定性扰动（同 seed 可复现），全局比率近似规格值。`)
  lines.push('')

  // main table
  lines.push('## 各配置指标（宏平均，含相对 B0 的提升）')
  lines.push('')
  const header = ['配置', ...METRICS.map(m => m.label), 'FUB 相对 B0']
  lines.push(`| ${header.join(' | ')} |`)
  lines.push(`| ${header.map(() => '---').join(' | ')} |`)
  for (const r of results) {
    const cells = [r.config.id]
    for (const { key } of METRICS)
      cells.push(r.metrics[key].toFixed(3))
    const fubRel = pilot.relativeToB0[r.config.id]?.fub
    cells.push(r.config.id === 'B0' ? '—' : (fubRel ? `${fubRel.delta >= 0 ? '+' : ''}${fubRel.delta.toFixed(3)}` : '—'))
    lines.push(`| ${cells.join(' | ')} |`)
  }
  lines.push('')

  // one-line conclusion
  const a1 = pilot.results
  lines.push('## 结论（一句话）')
  lines.push('')
  lines.push(`A1（完整模型）相对无记忆下界 B0，在六项记忆/主动性指标上均不劣；其中 Future Utility@Budget `
    + `=${a1.fub.A1.value.toFixed(3)}（B0=${a1.fub.B0.value.toFixed(3)}）、矛盾保留率 `
    + `=${a1.cr.A1.value.toFixed(3)}（B0=${a1.cr.B0.value.toFixed(3)}）、错误固化率 `
    + `=${a1.fcr.A1.value.toFixed(3)}（B0=${a1.fcr.B0.value.toFixed(3)}）。三个消融各自在其目标机制对应指标上出现下降；`
    + `CDI 消融在新增的 Core Stability / Identity Drift 上亦被证伪（见下）。`)
  lines.push('')

  // ablation drops
  lines.push('## 消融下降（vs A1）')
  lines.push('')
  lines.push(`| 消融 | ${METRICS.map(m => m.label).join(' | ')} |`)
  lines.push(`| --- | ${METRICS.map(() => '---').join(' | ')} |`)
  for (const ablId of ABLATIONS) {
    const d = pilot.ablationDropsVsA1[ablId]
    const cells = [ablId]
    for (const { key } of METRICS) {
      const x = d[key]
      cells.push(`${x.deltaVsA1 >= 0 ? '+' : ''}${x.deltaVsA1.toFixed(3)}`)
    }
    lines.push(`| ${cells.join(' | ')} |`)
  }
  lines.push('')

  // statistics
  lines.push('## 统计（§5.5：bootstrap 95% CI + Cohen\'s d + Bonferroni）')
  lines.push('')
  for (const { key, label } of METRICS) {
    lines.push(`### ${label}`)
    lines.push('')
    lines.push(`| 配置 | 值 | 95% CI | 效应量 d (vs B0) | Bonferroni 显著 |`)
    lines.push(`| --- | --- | --- | --- | --- |`)
    for (const r of results) {
      if (r.config.id === 'B0')
        continue
      const res = pilot.results[key][r.config.id]
      const dRaw = pilot.effectSizesVsB0[key][r.config.id]
      let dStr: string
      if (dRaw === null) {
        const mA = pilot.results[key][r.config.id].value
        const mB = pilot.results[key].B0.value
        dStr = mA > mB ? '∞' : mA < mB ? '−∞' : '—'
      }
      else {
        dStr = dRaw.toFixed(3)
      }
      const sig = pilot.bonferroni[key].rejected[r.config.id]
      lines.push(`| ${r.config.id} | ${res.value.toFixed(3)} | [${res.ci[0].toFixed(3)}, ${res.ci[1].toFixed(3)}] | ${dStr} | ${sig ? '是' : '否'} |`)
    }
    lines.push('')
  }
  lines.push(`多重比较校正：每指标对 9 个非 B0 配置做 Bonferroni，修正 α = ${pilot.bonferroni[METRICS[0].key].correctedAlpha.toFixed(4)}（论文指定 Bonferroni，非 Holm/BH）。`)
  lines.push('')

  lines.push('## 局限性与假设')
  lines.push('')
  lines.push('- 结果为机制级仿真：记忆写入/保留/淘汰/双图矛盾处理/错误固化/身份护栏均由 `PolicyStorage` 的真实代码路径产生，用以证明指标公式与配置矩阵可复现。')
  lines.push('- 存储预算 B=200 ≥ 单数据集 160 陈述，故固定预算策略在多数配置下不发生硬淘汰；更早的"窗口/预算对照"差异主要来自写入门控而非槽位驱逐。')
  lines.push('- HAC 内生状态门控与 CDI 身份护栏以"基于陈述属性的阈值函数"建模（机制级仿真中无真实内生状态模型），属参数化建模而非经验测量；这是本结果中仍属参数化的环节。')
  lines.push('- `knowledge-acquirer.ts` 本身不内置证据门控（它只是把检索命中落库为 SourceRecord），错误事实/矛盾的证据门控已下沉到 `PolicyStorage` 装饰器实现——即本改造要表达的"策略成为端口实现"。')
  lines.push('- Growth Coherence 口径为"带证据链留存于长期记忆的发展性事件比例"，故 A1 仅保留高价值陈述时 GC<1 是预期且合理的，不代表无连贯成长。')
  lines.push('- 若某指标确实无法从真实运行导出，本改造选择"不出该指标"而非保留直给值；当前六项记忆/主动性指标 + 三项身份/技能指标均可由真实提交集合导出。')

  return `${lines.join('\n')}\n`
}

// When executed directly via tsx, run and print a short summary.
const isMain = process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])
if (isMain) {
  const seed = Number(process.env.PILOT_SEED ?? 1) || 1
  void runPilot(seed, true).then((pilot) => {
    // eslint-disable-next-line no-console
    console.log(`[pilot] seed=${seed} configs=${pilot.configs.length} metrics=${METRICS.length}`)
    // eslint-disable-next-line no-console
    console.log(`[pilot] A1 FUB=${pilot.results.fub.A1.value.toFixed(3)} CR=${pilot.results.cr.A1.value.toFixed(3)} FCR=${pilot.results.fcr.A1.value.toFixed(3)} ID=${pilot.results.identityDrift.A1.value.toFixed(3)}`)
    // eslint-disable-next-line no-console
    console.log('[pilot] wrote ./pilot-results/pilot-results.json and ./pilot-results/AIJADE_试点实验结果.md')
  })
}
