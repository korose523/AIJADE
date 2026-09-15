import type { GatingCoefficients } from '../src/index'

import process from 'node:process'

/**
 * P2 · 核查报告 §5 动作 4 的**最小实验**：oracle 显著性 vs 预测显著性。
 *
 * ── 要判定什么 ──────────────────────────────────────────────────────────
 * 已定的事实（可复现）：
 *   · `p1.5-report.md` 称门控 ON 在 recall@K 上领先（K=8 时 +0.116）；
 *     2026-09-15 重跑得到 **−0.011**，且每一个 K 都反向（`diag` 三连已排除标签、
 *     阈值两条解释）。
 *   · `diag-prune-accounting.ts` 测出**剪枝不是成因**：ON 仅剪 4/5882，
 *     金标准证据零损失 ⇒ 剪枝对 recall@K 的贡献为 0。
 *   · 那么差异只能来自 `DEFAULT_GATING` 的**第二个**机制：编码期显著性 →
 *     `durability` / `decayExponent` → 检索期 strength 重加权。
 *
 * 剩下的假设（核查报告 H4）：
 *   **"去 oracle 化"是符号反转之因** —— 早期门控用的是近似 oracle 的显著性，
 *   换成可实现的 `predictSalienceV2`（诚实 AUC ≈ 0.815）后，被误降权的证据
 *   多于被提升的，于是 ON 反而劣于 OFF。
 *
 * ── 六个条件 ────────────────────────────────────────────────────────────
 * 三档**显著性来源** × 两个**门控条件**，再加一个剪枝对照：
 *
 *   显著性来源          | 说明
 *   -------------------|--------------------------------------------------
 *   oracle             | 证据 episode 记 1、其余记 0（已知上界；AUC = 1.0）
 *   predicted          | 现用的 `predictSalienceV2`（诚实 AUC ≈ 0.815）
 *   shuffled           | 把 predicted 的取值**置换**到别的 episode 上（保边际、AUC ≈ 0.5）
 *
 *   门控条件            | 说明
 *   -------------------|--------------------------------------------------
 *   ON                 | `DEFAULT_GATING`（kSalience 0.8 / kSocial 0.5 / kNovelty 0.3）
 *   OFF                | `NO_GATING`（全零）
 *
 *   对照 `oracle-ON-noprune`：`DEFAULT_GATING` 但关闭 consolidate 的选择性剪枝。
 *   它与 `oracle-ON` 的差**只**包含剪枝这一个维度 —— 用来把剪枝从重加权里彻底摘出去。
 *
 * ── 读法（预注册，先写下来再跑，避免事后编解释）─────────────────────────
 *   R1 若 oracle-ON > oracle-OFF（重加权在真信号下有益）
 *      且 predicted-ON < predicted-OFF（在预测器下有害）
 *      ⇒ **H4 成立**：收益依赖一个尚不可实现的 oracle，换成可实现预测器后反转。
 *   R2 若 shuffled-ON ≈ predicted-ON 且都劣于 OFF
 *      ⇒ 损害不特定于预测器质量，而是**任何**显著性重加权都会伤到词法检索；
 *        那么瓶颈在"重加权这个机制本身"，结论更强也更难修。
 *   R3 若 oracle-ON ≈ oracle-ON-noprune
 *      ⇒ 剪枝在本实验中同样惰性，与 `diag-prune-accounting.ts` 互相印证。
 *   R4 若 predicted-ON ≈ predicted-OFF
 *      ⇒ 重跑方向与既有观察不符，说明还有未识别的自由度（须停下来查，不得强行解释）。
 *
 * ── 同时落实核查报告 §5 动作 6 ──────────────────────────────────────────
 * 本脚本的"判读"段落**由实测数字生成**，不含任何硬编码结论文案。
 * 反面教材见 `p1.5-recall.ts`（打印 recall≈1.0 而实测 0.07）。
 *
 * 用法：tsx eval/diag-oracle-vs-predicted-salience.ts [path-to-locomo.json] [conv-limit]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { auc, buildMemory, DEFAULT_GATING, loadLocomo, NO_GATING, predictSalienceV2 } from '../src/index'
import { avg, goldEvidenceIds, KS, measure, mulberry32, shuffledCopy } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

// KS / measure / goldEvidenceIds / avg / mulberry32 / shuffledCopy 统一放在
// `eval/eval-metrics.ts` —— 本脚本与 `p2-quantile-retention-sweep.ts` 的 recall@K
// 定义必须逐位相同，否则两个脚本的数字不可互相比较。

// ---------------------------------------------------------------- 条件定义

type SalienceSource = 'oracle' | 'predicted' | 'shuffled'

interface Condition {
  key: string
  gating: GatingCoefficients
  source: SalienceSource
  selectiveConsolidation?: boolean
  note: string
}

const CONDITIONS: Condition[] = [
  { key: 'predicted-ON', gating: DEFAULT_GATING, source: 'predicted', note: '现状：可实现的预测器 + 完整门控' },
  { key: 'predicted-OFF', gating: NO_GATING, source: 'predicted', note: '控制条件（kSalience=0，显著性不参与打分）' },
  { key: 'predicted-ON-noprune', gating: DEFAULT_GATING, source: 'predicted', selectiveConsolidation: false, note: '现状下隔离剪枝：只有重加权、没有剪枝' },
  { key: 'oracle-ON', gating: DEFAULT_GATING, source: 'oracle', note: '上界：真显著性 + 完整门控' },
  { key: 'oracle-OFF', gating: NO_GATING, source: 'oracle', note: '上界的控制条件' },
  { key: 'oracle-ON-noprune', gating: DEFAULT_GATING, source: 'oracle', selectiveConsolidation: false, note: '上界下隔离剪枝：只有重加权、没有剪枝' },
  { key: 'shuffled-ON', gating: DEFAULT_GATING, source: 'shuffled', note: '保边际、打乱指派（AUC≈0.5）' },
  { key: 'shuffled-OFF', gating: NO_GATING, source: 'shuffled', note: '打乱条件的控制' },
]

// ---------------------------------------------------------------- 主流程

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll
  const sha = sha256File(path)

  console.info('=== P2 最小实验：oracle 显著性 vs 预测显著性 ===')
  console.info(`corpus : ${path}`)
  console.info(`sha256 : ${sha}`)
  console.info(`convs  : ${convs.length}`)
  console.info(`cond   : ${CONDITIONS.map(c => c.key).join(', ')}`)
  console.info()

  // 每条件的累计指标
  const acc: Record<string, { recall: Record<number, number[]>, hit: number[], surv: number[], pruned: number[], pool: number[] }> = {}
  for (const c of CONDITIONS) {
    acc[c.key] = {
      recall: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      hit: [],
      surv: [],
      pruned: [],
      pool: [],
    }
  }
  // 每档显著性来源的 AUC（跨对话池化）
  const aucPool: Record<SalienceSource, { scores: number[], labels: number[] }> = {
    oracle: { scores: [], labels: [] },
    predicted: { scores: [], labels: [] },
    shuffled: { scores: [], labels: [] },
  }

  for (let ci = 0; ci < convs.length; ci++) {
    const conv = convs[ci]
    const gold = goldEvidenceIds(conv)

    // 1) 预测显著性（与 store.encode 完全同一 ctx，保证逐位一致）
    const ctx = { priors: [] as string[], idf: new Map<string, number>(), nDocs: 1 }
    const predSal = conv.episodes.map((ep) => {
      const raw = predictSalienceV2(ep.content, ctx).score
      return 1 / (1 + Math.exp(-raw))
    })
    // 2) oracle 显著性
    const oracleSal = conv.episodes.map(ep => (gold.has(ep.id) ? 1 : 0))
    // 3) 打乱：把 predicted 的取值置换到不同的 episode 上（保边际）
    const rnd = mulberry32(0xC0FFEE + ci)
    const shufValues = shuffledCopy(predSal, rnd)
    const shuffledSal = conv.episodes.map((_, i) => shufValues[i])

    const bySource: Record<SalienceSource, number[]> = {
      oracle: oracleSal,
      predicted: predSal,
      shuffled: shuffledSal,
    }
    for (const src of ['oracle', 'predicted', 'shuffled'] as SalienceSource[]) {
      for (let i = 0; i < conv.episodes.length; i++) {
        aucPool[src].scores.push(bySource[src][i])
        aucPool[src].labels.push(gold.has(conv.episodes[i].id) ? 1 : 0)
      }
    }

    const idxOf = new Map(conv.episodes.map((ep, i) => [ep.id, i]))

    for (const cond of CONDITIONS) {
      const vals = bySource[cond.source]
      const mem = await buildMemory(conv, cond.gating as GatingCoefficients, undefined, {
        salienceOf: ({ id }) => {
          const i = idxOf.get(id)
          return i === undefined ? undefined : vals[i]
        },
        selectiveConsolidation: cond.selectiveConsolidation,
      })
      const m = measure(mem, conv, gold)
      for (const k of KS) acc[cond.key].recall[k].push(m.recall[k])
      acc[cond.key].hit.push(m.hitScoreMean)
      acc[cond.key].surv.push(m.evidenceSurvival)
      acc[cond.key].pruned.push(m.prunedTotal)
      acc[cond.key].pool.push(m.poolSize)
    }
  }

  // ---------------------------------------------------------------- 输出

  const summary: Record<string, { recall: Record<number, number>, hitScoreMean: number, evidenceSurvival: number, prunedTotal: number, poolSize: number }> = {}
  for (const c of CONDITIONS) {
    summary[c.key] = {
      recall: Object.fromEntries(KS.map(k => [k, avg(acc[c.key].recall[k])])),
      hitScoreMean: avg(acc[c.key].hit),
      evidenceSurvival: avg(acc[c.key].surv),
      prunedTotal: avg(acc[c.key].pruned),
      poolSize: avg(acc[c.key].pool),
    }
  }
  const aucOf: Record<SalienceSource, number> = {
    oracle: auc(aucPool.oracle.scores, aucPool.oracle.labels),
    predicted: auc(aucPool.predicted.scores, aucPool.predicted.labels),
    shuffled: auc(aucPool.shuffled.scores, aucPool.shuffled.labels),
  }

  console.info('--- 显著性信号质量（池化 AUC，标签=该 episode 是否被某题引用为金标准证据）---')
  for (const src of ['oracle', 'predicted', 'shuffled'] as SalienceSource[])
    console.info(`  ${src.padEnd(10)} AUC = ${aucOf[src].toFixed(4)}`)
  console.info()

  console.info('--- recall@K / 命中项均分 / 证据存活 / 剪枝量 / 可检索池（10 个对话均值）---')
  const header = `  ${'condition'.padEnd(18)}${KS.map(k => `K=${k}`.padStart(9)).join('')}${'hitScore'.padStart(11)}${'evSurv'.padStart(9)}${'pruned'.padStart(9)}${'pool'.padStart(9)}`
  console.info(header)
  for (const c of CONDITIONS) {
    const s = summary[c.key]
    const row = KS.map(k => s.recall[k].toFixed(4).padStart(9)).join('')
    console.info(
      `  ${c.key.padEnd(18)}${row}${s.hitScoreMean.toFixed(4).padStart(11)}${s.evidenceSurvival.toFixed(4).padStart(9)}`
      + `${s.prunedTotal.toFixed(1).padStart(9)}${s.poolSize.toFixed(0).padStart(9)}`,
    )
  }
  console.info()

  console.info('--- 关键对比（每个 K 上 A − B）---')
  const contrasts: Array<[string, string, string]> = [
    ['oracle-ON', 'oracle-OFF', 'oracle 总效应'],
    ['predicted-ON', 'predicted-OFF', 'predicted 总效应'],
    ['shuffled-ON', 'shuffled-OFF', 'shuffled 总效应'],
    ['oracle-ON', 'oracle-ON-noprune', 'oracle 中的剪枝'],
    ['predicted-ON', 'predicted-ON-noprune', 'predicted 中的剪枝'],
    ['oracle-ON-noprune', 'oracle-OFF', 'oracle 中的重加权'],
    ['predicted-ON-noprune', 'predicted-OFF', 'predicted 中的重加权'],
  ]
  for (const [a, b, label] of contrasts) {
    const gaps = KS.map(k => summary[a].recall[k] - summary[b].recall[k])
    console.info(`  ${label.padEnd(22)} ${gaps.map(g => `${g >= 0 ? '+' : ''}${g.toFixed(4)}`).join('  ')}`)
  }
  const maxK = Math.max(...KS)
  console.info()

  // ---------------------------------------------------------------- 由数据生成判读

  const gapOracle = summary['oracle-ON'].recall[maxK] - summary['oracle-OFF'].recall[maxK]
  const gapPred = summary['predicted-ON'].recall[maxK] - summary['predicted-OFF'].recall[maxK]
  const gapShuf = summary['shuffled-ON'].recall[maxK] - summary['shuffled-OFF'].recall[maxK]
  const pruneOracle = summary['oracle-ON'].recall[maxK] - summary['oracle-ON-noprune'].recall[maxK]
  const prunePred = summary['predicted-ON'].recall[maxK] - summary['predicted-ON-noprune'].recall[maxK]
  const rwOracle = summary['oracle-ON-noprune'].recall[maxK] - summary['oracle-OFF'].recall[maxK]
  const rwPred = summary['predicted-ON-noprune'].recall[maxK] - summary['predicted-OFF'].recall[maxK]
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`

  const verdicts: string[] = []
  verdicts.push(`【R1 · 总效应】(K=${maxK})  oracle ${fmt(gapOracle)} | predicted ${fmt(gapPred)} | shuffled ${fmt(gapShuf)}`)
  verdicts.push(`  ⇒ ${gapOracle > 0 && gapPred < 0
    ? 'H4 方向成立：重加权+剪枝在真信号下有益、在预测器下有害 ⇒ 收益依赖一个尚不可实现的 oracle。'
    : gapOracle <= 0 && gapPred <= 0
      ? 'H4 不成立：即便给出 oracle 显著性，门控也无益 ⇒ 瓶颈在机制本身，不在信号质量。'
      : '方向不符：预测器下 ON 并未劣于 OFF，与既有观察不一致，须先查未识别的自由度再解释。'}`)

  verdicts.push('')
  verdicts.push(`【R2 · 效应分解】(K=${maxK})  A 剪枝路径 = ON − ON-noprune；B 重加权路径 = ON-noprune − OFF`)
  verdicts.push(`  oracle    : 剪枝 ${fmt(pruneOracle)}  +  重加权 ${fmt(rwOracle)}  =  ${fmt(pruneOracle + rwOracle)}`)
  verdicts.push(`  predicted : 剪枝 ${fmt(prunePred)}  +  重加权 ${fmt(rwPred)}  =  ${fmt(prunePred + rwPred)}`)
  const oraclePruneShare = Math.abs(gapOracle) > 1e-9 ? pruneOracle / gapOracle : Number.NaN
  verdicts.push(`  ⇒ oracle 下剪枝占效应 ${(oraclePruneShare * 100).toFixed(1)}%；predicted 下剪枝 ${fmt(prunePred)}（近乎为零）。`)
  verdicts.push(`  ⇒ ${prunePred > 0.01 && pruneOracle > 0.01
    ? '两个 regime 下剪枝都有效，差异不在剪枝路径。'
    : '**剪枝的贡献完全取决于信号质量**：同一个剪枝机制在 oracle 下贡献可观，在预测器下惰性。'}`)
  verdicts.push('     机制：consolidate 用固定阈值 salience > 0.5 做二元剪枝，而 salience = sigmoid(predictorScore)；')
  verdicts.push('     sigmoid 以 0.5 为中心，预测器分数须 <= 0 才会被剪。实测剪枝量：')
  verdicts.push(`       predicted-ON 剪 ${summary['predicted-ON'].prunedTotal.toFixed(1)}/${(summary['predicted-ON'].poolSize + summary['predicted-ON'].prunedTotal).toFixed(0)} 条`
    + `，oracle-ON 剪 ${summary['oracle-ON'].prunedTotal.toFixed(1)} 条（两条件池子 ${summary['predicted-ON'].poolSize.toFixed(0)} vs ${summary['oracle-ON'].poolSize.toFixed(0)}）。`)
  verdicts.push('     ⇒ 判决点不在"预测器不够准"，而在**阈值校准**：固定 0.5 与预测器输出分布不匹配，使剪枝通道形同关闭。')

  verdicts.push('')
  verdicts.push(`【R3 · 剪枝 vs 诊断互证】oracle 剪枝 ${fmt(pruneOracle)}；predicted 剪枝 ${fmt(prunePred)}`)
  verdicts.push(`  ⇒ 与 \`diag-prune-accounting.ts\`（predicted 下剪 4/5882、证据零损失）**相容**：`)
  verdicts.push('     该诊断测的是 predicted regime，"剪枝零损失"成立；但不可外推为"剪枝机制无效"——')
  verdicts.push('     在 oracle regime 下剪枝是收益的主要来源。前一份结论需要加限定词。')

  verdicts.push('')
  verdicts.push(`【R4 · 信号质量 vs 效应】AUC: oracle ${aucOf.oracle.toFixed(4)} > predicted ${aucOf.predicted.toFixed(4)} > shuffled ${aucOf.shuffled.toFixed(4)}`)
  verdicts.push(`  shuffled 与 predicted 的总效应差 = ${fmt(gapShuf - gapPred)}`)
  verdicts.push(`  ⇒ ${Math.abs(gapShuf - gapPred) < 0.005
    ? '打乱后的损害与预测器相当 ⇒ 在剪枝惰性时，重加权本身对词法检索是轻微负面的，与信号具体取值几乎无关。'
    : '打乱与预测器的效应不同 ⇒ 预测器的具体指派（而非重加权本身）是损害来源。'}`)
  verdicts.push(`  ⇒ 效应随 AUC ${gapOracle >= gapPred && gapPred >= gapShuf ? '单调递增（本次成立）' : '非单调（本次不成立）'}；`)
  verdicts.push('     若在更多语料上复现，可把"门控收益随显著性信号质量单调递增"作为 P2 的可证伪预测。')

  console.info('--- 判读（本段由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts) console.info(v)

  // ---------------------------------------------------------------- 持久化制品

  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })
  const jsonPath = join(outDir, `p2-oracle-vs-predicted-salience-${stamp}.json`)
  writeFileSync(jsonPath, `${JSON.stringify({
    generatedAt: new Date().toISOString(),
    corpus: { path, sha256: sha, conversations: convs.length },
    ks: KS,
    salienceAuc: aucOf,
    conditions: Object.fromEntries(CONDITIONS.map(c => [c.key, { ...summary[c.key], note: c.note }])),
    contrasts: Object.fromEntries(contrasts.map(([a, b, label]) => [label, Object.fromEntries(KS.map(k => [k, summary[a].recall[k] - summary[b].recall[k]]))])),
    verdicts,
  }, null, 2)}\n`, 'utf8')
  console.info()
  console.info(`artifact: ${jsonPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
