import type { BioticMemory, GatingCoefficients } from '../src/index'

import process from 'node:process'

/**
 * P2 · 算法优化验证：把剪枝判据从**绝对阈值**换成**排名分位**，并做三因子分解。
 *
 * ── 问题从哪来 ───────────────────────────────────────────────────────────
 * `eval/diag-oracle-vs-predicted-salience.ts`（10 对话全量）的结论：
 *
 *   · oracle 显著性下门控总效应 = **+0.1999**（K=8），其中**剪枝占 91.2%**（+0.1824），
 *     重加权只占 8.8%（+0.0176）。
 *   · 预测器（诚实 AUC 0.766）下门控总效应 = **−0.0114**，其中剪枝贡献**恰好 0**。
 *   · 剪枝贡献为 0 的原因**不是**预测器不够准，而是**阈值失配**：
 *     `consolidate` 判据是 `salience > 0.5`，而 `salience = sigmoid(score)`，
 *     等价于 `score > 0`；`predictSalienceV2` 的分数几乎恒为正，
 *     于是 LoCoMo 全量只剪掉 **4/5882** 条 —— 一个整机制被一个未校准的常数关掉了。
 *
 * ── 干预 ─────────────────────────────────────────────────────────────────
 * 保留判据从"绝对阈值"换成"**排名分位**"：保留显著性最高的前 `keepFraction` 比例。
 * "保留多少"因此成为显式的实验变量，与预测器的输出尺度解耦。
 *
 * ── 必须排除的混淆（本实验设计的核心）────────────────────────────────────
 * 剪枝会**改变词法索引的 IDF**（`ensureIndex` 只对存活项建索引）。
 * 池子变小 ⇒ IDF 变大 ⇒ 相似度分布改变 ⇒ 排序本身可能变容易。
 * 若不控制这一点，任何"剪枝后 recall 上升"都可能只是"池子小"的假象，
 * 而不是"显著性选得准"。因此三个效应分开测量：
 *
 *   A. 池子效应（纯规模）：`random-retain-q` —— 无重加权、随机保留 q 比例
 *   B. 选择质量效应：      `salience-retain-q` − `random-retain-q`
 *   C. 重加权效应：        `quantile-q` − `salience-retain-q`
 *
 * `salience-retain-q` / `random-retain-q` 都用 **NO_GATING + selective:true**：
 * 门控系数为 0（无重加权）但强制剪枝 —— 两臂差别**只**来自"按什么排序保留"。
 *
 * ── 预注册读法（先写下来再跑）────────────────────────────────────────────
 *   V1 若 `salience-retain-q*` 显著高于现状（绝对阈值）⇒ 阈值失配可修，优化有效。
 *   V2 若 `salience-retain-q` ≈ `random-retain-q`（选择质量效应 ≈ 0）
 *      ⇒ "优化"其实是池子效应在起作用，与显著性无关；**不得**声称是显著性选择的功劳。
 *   V3 若 `quantile-q` < `salience-retain-q`
 *      ⇒ 重加权在剪枝之上还有额外损害，应把两者拆成可独立开关的机制。
 *
 * ── 版本取代说明（引用前必读）──────────────────────────────────────────────
 * `eval/results/` 下存有本扫描的两次产物：**09-15 版已被 09-19 版取代**，
 * 引用一律以 09-19 版为准。取代原因与结论翻转的事实链：
 *
 *   · 09-15 版产物时间戳 `2026-09-15 12:17`，**早于** commit `014b17b`
 *     （`2026-09-15 13:39:32 +0900`，“make the retrieval score components
 *     commensurable, not the weights”）。该提交把 `retrievalScoreMode` 默认改为
 *     `standardized`、`dedupeByContent` 改为 `true` ⇒ **09-15 版的数字出自旧打分口径**。
 *   · 于是 V1 的判读在两版之间**翻转**：
 *       09-15 版：“V1 成立：…阈值失配确是可修的。”
 *       09-19 版：“V1 不成立或幅度不足：排名制保留未能显著超过现状。”
 *     同一实验、同一预测器，仅因打分口径不同即得到相反结论 —— 这正是本仓库要求
 *     产物必须携带 `scoreMode` / `weights` / `gitSha` 的原因（见 `./artifact-provenance`）。
 *   · 09-19 版：23 arms，~58 min，exit=0；**V1 阴性**（最优 q*=0.6 仅 **+0.0046@K=8**，
 *     噪声内），V2/V3 通过，oracle 缺口 0.1112。
 *   · **不得**把 09-15 版的“V1 成立”当作“排名制保留提升检索”的证据：该论断在
 *     09-19 版口径下不被支持，属**阴性结果**，须如实呈现，不得包装为收益。
 *
 * 用法：tsx eval/p2-quantile-retention-sweep.ts [path-to-locomo.json] [conv-limit]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { auc, buildMemory, DEFAULT_GATING, loadLocomo, NO_GATING, predictSalienceV2 } from '../src/index'
import { withProvenance } from './artifact-provenance'
import { avg, goldEvidenceIds, KS, measure, mulberry32 } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

const QS = [1, 0.6, 0.35, 0.25, 0.15]
const MAXK = Math.max(...KS)

type SalKind = 'predicted' | 'oracle' | 'random'

interface Arm {
  key: string
  sal: SalKind
  gating: GatingCoefficients
  /** 强制选择性剪枝（即便门控系数为 0）。 */
  selective?: boolean
  keepFraction?: number
  label: string
}

interface ArmSpec {
  kind: string
  sal: SalKind
  selective?: boolean
  gating: GatingCoefficients
  label: (q: number) => string
}

const Q_SPECS: ArmSpec[] = [
  { kind: 'quantile', sal: 'predicted', gating: DEFAULT_GATING, label: q => `预测显著性·分位+重加权 q=${q}` },
  { kind: 'salience-retain', sal: 'predicted', selective: true, gating: NO_GATING, label: q => `预测显著性·分位(无重加权) q=${q}` },
  { kind: 'random-retain', sal: 'random', selective: true, gating: NO_GATING, label: q => `随机保留(无重加权) q=${q}` },
  { kind: 'oracle-quantile', sal: 'oracle', gating: DEFAULT_GATING, label: q => `oracle·分位 q=${q}（上界）` },
]

const ARMS: Arm[] = [
  { key: 'baseline-nogating', sal: 'predicted', gating: NO_GATING, label: '基线：无门控、不剪枝' },
  { key: 'absolute-threshold', sal: 'predicted', gating: DEFAULT_GATING, selective: true, label: '现状：绝对阈值 salience>0.5' },
  ...Q_SPECS.flatMap(spec =>
    QS.map<Arm>(q => ({
      key: `${spec.kind}-${q}`,
      sal: spec.sal,
      gating: spec.gating,
      selective: spec.selective,
      keepFraction: q,
      label: spec.label(q),
    })),
  ),
  { key: 'oracle-absolute', sal: 'oracle', gating: DEFAULT_GATING, selective: true, label: 'oracle·绝对阈值（上界）' },
]

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll
  const sha = sha256File(path)

  console.info('=== P2 算法优化：排名制保留扫描 + 池子/选择/重加权三因子分解 ===')
  console.info(`corpus : ${path}`)
  console.info(`sha256 : ${sha}`)
  console.info(`convs  : ${convs.length}`)
  console.info(`arms   : ${ARMS.length}`)
  console.info()

  const acc: Record<string, { recall: Record<number, number[]>, surv: number[], pool: number[] }> = {}
  for (const a of ARMS)
    acc[a.key] = { recall: Object.fromEntries(KS.map(k => [k, [] as number[]])), surv: [], pool: [] }

  const aucPool: Record<'predicted' | 'oracle', { scores: number[], labels: number[] }> = {
    predicted: { scores: [], labels: [] },
    oracle: { scores: [], labels: [] },
  }

  for (let ci = 0; ci < convs.length; ci++) {
    const conv = convs[ci]
    const gold = goldEvidenceIds(conv)

    const ctx = { priors: [] as string[], idf: new Map<string, number>(), nDocs: 1 }
    const predSal = conv.episodes.map(ep => 1 / (1 + Math.exp(-predictSalienceV2(ep.content, ctx).score)))
    const oracleSal = conv.episodes.map(ep => (gold.has(ep.id) ? 1 : 0))
    const rnd = mulberry32(0xC0FFEE + ci)
    const randSal = conv.episodes.map(() => rnd())

    for (let i = 0; i < conv.episodes.length; i++) {
      const label = gold.has(conv.episodes[i].id) ? 1 : 0
      aucPool.predicted.scores.push(predSal[i])
      aucPool.predicted.labels.push(label)
      aucPool.oracle.scores.push(oracleSal[i])
      aucPool.oracle.labels.push(label)
    }

    const idxOf = new Map(conv.episodes.map((ep, i) => [ep.id, i]))
    const valueOf = (sal: SalKind, i: number): number =>
      sal === 'oracle' ? oracleSal[i] : sal === 'random' ? randSal[i] : predSal[i]

    for (const arm of ARMS) {
      const mem: BioticMemory = await buildMemory(conv, arm.gating as GatingCoefficients, undefined, {
        salienceOf: ({ id }) => {
          const i = idxOf.get(id)
          return i === undefined ? undefined : valueOf(arm.sal, i)
        },
        selectiveConsolidation: arm.selective,
        keepFraction: arm.keepFraction,
      })
      const m = measure(mem, conv, gold)
      for (const k of KS) acc[arm.key].recall[k].push(m.recall[k])
      acc[arm.key].surv.push(m.evidenceSurvival)
      acc[arm.key].pool.push(m.poolSize)
    }
  }

  const summary: Record<string, { recall: Record<number, number>, evidenceSurvival: number, poolSize: number }> = {}
  for (const a of ARMS) {
    summary[a.key] = {
      recall: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].recall[k])])),
      evidenceSurvival: avg(acc[a.key].surv),
      poolSize: avg(acc[a.key].pool),
    }
  }
  const aucOf = {
    predicted: auc(aucPool.predicted.scores, aucPool.predicted.labels),
    oracle: auc(aucPool.oracle.scores, aucPool.oracle.labels),
  }

  console.info('--- 显著性信号质量（池化 AUC）---')
  console.info(`  predicted ${aucOf.predicted.toFixed(4)} | oracle ${aucOf.oracle.toFixed(4)} | random 0.5000（构造值）`)
  console.info()
  const head = `  ${'arm'.padEnd(34)}${KS.map(k => `K=${k}`.padStart(9)).join('')}${'condR@8'.padStart(9)}${'evSurv'.padStart(9)}${'pool'.padStart(8)}`
  console.info(head)
  for (const a of ARMS) {
    const s = summary[a.key]
    const condR = s.evidenceSurvival > 0 ? s.recall[MAXK] / s.evidenceSurvival : 0
    console.info(
      `  ${a.label.padEnd(34)}${KS.map(k => s.recall[k].toFixed(4).padStart(9)).join('')}`
      + `${condR.toFixed(4).padStart(9)}${s.evidenceSurvival.toFixed(4).padStart(9)}${s.poolSize.toFixed(0).padStart(8)}`,
    )
  }
  console.info()
  console.info('  注：condR@8 = recall@8 ÷ 证据存活率，即"在仍可检索的证据中真正找到的比例"。')
  console.info('      剪枝会改变 IDF（ensureIndex 只对存活项建索引），池子大小本身会影响排序难度 ——')
  console.info('      这正是下面必须对照 random-retain 的原因。')
  console.info()

  // ---------------------------------------------------------------- 三因子分解
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`
  const R = (k: string) => summary[k].recall[MAXK]
  const base = R('baseline-nogating')
  const cur = R('absolute-threshold')

  console.info(`--- 三因子分解（K=${MAXK}，全部相对基线 ${base.toFixed(4)}）---`)
  console.info(`  ${'q'.padEnd(7)}${'随机保留'.padStart(12)}${'显著性保留'.padStart(13)}${'选择质量'.padStart(11)}${'分位+重加权'.padStart(13)}${'重加权代价'.padStart(12)}`)
  for (const q of QS) {
    const rand = R(`random-retain-${q}`)
    const salR = R(`salience-retain-${q}`)
    const full = R(`quantile-${q}`)
    console.info(
      `  ${String(q).padEnd(7)}${fmt(rand - base).padStart(12)}${fmt(salR - base).padStart(13)}`
      + `${fmt(salR - rand).padStart(11)}${fmt(full - base).padStart(13)}${fmt(full - salR).padStart(12)}`,
    )
  }
  console.info()

  // ---------------------------------------------------------------- 由数据生成判读
  const predBest = QS.reduce((b, q) => (R(`salience-retain-${q}`) > R(`salience-retain-${b}`) ? q : b), QS[0])
  const randAtBest = R(`random-retain-${predBest}`)
  const salAtBest = R(`salience-retain-${predBest}`)
  const fullAtBest = R(`quantile-${predBest}`)
  const oracleAtBestQ = R(`oracle-quantile-${predBest}`)
  const oracleBest = QS.reduce((b, q) => (R(`oracle-quantile-${q}`) > R(`oracle-quantile-${b}`) ? q : b), QS[0])

  const verdicts: string[] = []
  verdicts.push('【V1 · 优化是否有效】')
  verdicts.push(`  基线（无门控）             ${base.toFixed(4)}`)
  verdicts.push(`  现状（绝对阈值）           ${cur.toFixed(4)}   [门控当前效应 ${fmt(cur - base)}]`)
  verdicts.push(`  显著性保留最优 q*=${predBest}     ${salAtBest.toFixed(4)}   [相对基线 ${fmt(salAtBest - base)}，相对现状 ${fmt(salAtBest - cur)}]`)
  verdicts.push(`  ⇒ ${salAtBest - cur > 0.01
    ? 'V1 成立：把判据换成排名分位后，用**同一个预测器**即可取得正收益 —— 阈值失配确是可修的。'
    : 'V1 不成立或幅度不足：排名制保留未能显著超过现状，须重新定位瓶颈。'}`)
  verdicts.push('')
  verdicts.push('【V2 · 增益来自"选择质量"还是"池子变小"？（关键对照）】')
  verdicts.push(`  同 q*=${predBest}：随机保留 ${randAtBest.toFixed(4)}（${fmt(randAtBest - base)}） vs 显著性保留 ${salAtBest.toFixed(4)}（${fmt(salAtBest - base)}）`)
  verdicts.push(`  选择质量效应 = ${fmt(salAtBest - randAtBest)}`)
  verdicts.push(`  池子效应占比 = ${Math.abs(salAtBest - base) > 1e-9 ? `${(Math.abs(randAtBest - base) / Math.abs(salAtBest - base) * 100).toFixed(0)}%` : 'n/a'}`)
  verdicts.push(`  ⇒ ${salAtBest - randAtBest > 0.02
    ? 'V2 通过：显著性排序确实优于随机排序，增益不能归因于池子变小。'
    : '⚠️ V2 **未通过**：显著性保留与随机保留效果相近 ⇒ 观察到的增益主要来自**池子变小/IDF 变化**，"按显著性选择"本身贡献有限。**不得**把该增益声称为显著性机制的功劳。'}`)
  verdicts.push('')
  verdicts.push('【V3 · 重加权是否额外有害】')
  verdicts.push(`  同 q*=${predBest}：分位+重加权 ${fullAtBest.toFixed(4)} vs 仅分位 ${salAtBest.toFixed(4)} → ${fmt(fullAtBest - salAtBest)}`)
  verdicts.push(`  ⇒ ${fullAtBest < salAtBest - 0.005
    ? '重加权在剪枝之上还有额外损害 ⇒ 应把重加权与剪枝拆成两个可独立开关的机制。'
    : '重加权在剪枝之上不构成额外损害（或差异在噪声内）。'}`)
  verdicts.push('')
  verdicts.push('【V4 · 排名质量的上限】')
  verdicts.push(`  同 q*=${predBest}：predicted ${salAtBest.toFixed(4)} vs oracle ${oracleAtBestQ.toFixed(4)} → ${fmt(oracleAtBestQ - salAtBest)}`)
  verdicts.push(`  oracle 自身最优 q*=${oracleBest} → ${R(`oracle-quantile-${oracleBest}`).toFixed(4)}（较基线 ${fmt(R(`oracle-quantile-${oracleBest}`) - base)}）`)
  verdicts.push(`  ⇒ 即便阈值修好，预测器与 oracle 之间仍差 ${(oracleAtBestQ - salAtBest).toFixed(4)}；`)
  verdicts.push('     该缺口只能靠提升显著性 AUC 弥合 ⇒ 若要把"优化"做成完整主张，须同时给出预测器改进。')

  console.info('--- 判读（本段由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts) console.info(v)

  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })
  const jsonPath = join(outDir, `p2-quantile-retention-sweep-${stamp}.json`)
  writeFileSync(jsonPath, `${JSON.stringify(withProvenance({
    generatedAt: new Date().toISOString(),
    corpus: { path, sha256: sha, conversations: convs.length },
    ks: KS,
    quantileGrid: QS,
    salienceAuc: aucOf,
    arms: Object.fromEntries(ARMS.map(a => [a.key, { ...summary[a.key], label: a.label }])),
    verdicts,
  }), null, 2)}\n`, 'utf8')
  console.info()
  console.info(`artifact: ${jsonPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
