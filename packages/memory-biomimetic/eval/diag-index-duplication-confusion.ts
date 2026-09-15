import type { Distiller, GatingCoefficients } from '../src/index'

import process from 'node:process'

/**
 * P2 · 两个量级混淆的专项诊断：
 *   ① **事实重复副本** —— `LexicalDistiller` 产出的 `fact_<id>` 与源 episode **内容逐字相同**，
 *      且 `recall@K` 的命中集合同时包含 `e` 与 `fact_e`。于是每条被保留的记忆在索引里
 *      占**两个槽位**，`recall@8` 实质上是 `recall@4`。
 *   ② **池子规模的非线性** —— `p2-quantile-retention-sweep.ts` 观察到：oracle 显著性下
 *      证据存活率恒为 1.0（一条证据不丢），仅把池子从 1176 缩到 706，
 *      `recall@8` 就从 0.0993 跳到 0.2788。**+0.18 与"选了谁"无关，只与"池子多大"有关。**
 *
 * 这两个混淆直接决定"门控有效/无效"这类主张能不能成立：
 *   · 若 recall@K 主要由池子规模决定，那么"剪枝提升检索精度"就没有信息量 ——
 *     随机丢弃等量记忆也该有同样的收益，而 `random-retain` 臂已显示并非如此（见扫描脚本），
 *     所以必须把"规模"与"选择"分到足够细的粒度上。
 *   · 若重复副本显著压低 recall@K，则既有全部 recall@K 数字都**低估**了真实值，
 *     且不同实验之间的可比性存疑。
 *
 * 做法：固定显著性来源与保留比例 q，只切换两件事 ——
 *   A. 蒸馏器：默认 `LexicalDistiller`（产生重复副本） vs 空蒸馏器（不产生事实）
 *   B. q 的细网格（1.0 → 0.3），用于定位跳变发生的位置
 *
 * 用法：tsx eval/diag-index-duplication-confusion.ts [path-to-locomo.json] [conv-limit]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { buildMemory, DEFAULT_GATING, loadLocomo, predictSalienceV2 } from '../src/index'
import { avg, goldEvidenceIds, KS, measure } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

const QS = [1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
const MAXK = Math.max(...KS)

/** 不产出事实的蒸馏器 —— 用来把"重复副本"这一维度关掉。 */
const NULL_DISTILLER: Distiller = { distill: async () => [] }

type SalKind = 'predicted' | 'oracle'

interface Arm {
  key: string
  sal: SalKind
  q: number
  dedup: boolean
  label: string
}

const ARMS: Arm[] = (['oracle', 'predicted'] as SalKind[]).flatMap(sal =>
  QS.flatMap((q): Arm[] => [
    { key: `${sal}-q${q}-dup`, sal, q, dedup: false, label: `${sal} q=${q} 有重复副本` },
    { key: `${sal}-q${q}-nofact`, sal, q, dedup: true, label: `${sal} q=${q} 无重复副本` },
  ]),
)

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== 诊断：事实重复副本 + 池子规模非线性 ===')
  console.info(`corpus : ${path}`)
  console.info(`sha256 : ${sha256File(path)}`)
  console.info(`convs  : ${convs.length}`)
  console.info(`arms   : ${ARMS.length}`)
  console.info()

  const acc: Record<string, { recall: Record<number, number[]>, surv: number[], pool: number[], distinct: number[] }> = {}
  for (const a of ARMS)
    acc[a.key] = { recall: Object.fromEntries(KS.map(k => [k, [] as number[]])), surv: [], pool: [], distinct: [] }

  for (const conv of convs) {
    const gold = goldEvidenceIds(conv)
    const ctx = { priors: [] as string[], idf: new Map<string, number>(), nDocs: 1 }
    const predSal = conv.episodes.map(ep => 1 / (1 + Math.exp(-predictSalienceV2(ep.content, ctx).score)))
    const oracleSal = conv.episodes.map(ep => (gold.has(ep.id) ? 1 : 0))
    const idxOf = new Map(conv.episodes.map((ep, i) => [ep.id, i]))

    for (const arm of ARMS) {
      const mem = await buildMemory(
        conv,
        DEFAULT_GATING as GatingCoefficients,
        arm.dedup ? NULL_DISTILLER : undefined,
        {
          salienceOf: ({ id }) => {
            const i = idxOf.get(id)
            return i === undefined ? undefined : (arm.sal === 'oracle' ? oracleSal[i] : predSal[i])
          },
          keepFraction: arm.q,
        },
      )
      const m = measure(mem, conv, gold)
      for (const k of KS) acc[arm.key].recall[k].push(m.recall[k])
      acc[arm.key].surv.push(m.evidenceSurvival)
      acc[arm.key].pool.push(m.poolSize)
      acc[arm.key].distinct.push(mem.episodes.filter(e => !e.forgotten).length)
    }
  }

  const S: Record<string, { recall: Record<number, number>, evidenceSurvival: number, poolSize: number, distinct: number }> = {}
  for (const a of ARMS) {
    S[a.key] = {
      recall: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].recall[k])])),
      evidenceSurvival: avg(acc[a.key].surv),
      poolSize: avg(acc[a.key].pool),
      distinct: avg(acc[a.key].distinct),
    }
  }

  console.info(`  ${'arm'.padEnd(26)}${'K=1'.padStart(9)}${'K=2'.padStart(9)}${'K=4'.padStart(9)}${'K=8'.padStart(9)}${'evSurv'.padStart(9)}${'distinct'.padStart(10)}${'pool'.padStart(8)}`)
  for (const a of ARMS) {
    const s = S[a.key]
    console.info(
      `  ${a.label.padEnd(26)}${KS.map(k => s.recall[k].toFixed(4).padStart(9)).join('')}`
      + `${s.evidenceSurvival.toFixed(4).padStart(9)}${s.distinct.toFixed(0).padStart(10)}${s.poolSize.toFixed(0).padStart(8)}`,
    )
  }
  console.info()

  // ---------------------------------------------------------------- 判读
  const verdicts: string[] = []
  const R = (sal: SalKind, q: number, dedup: boolean) => S[`${sal}-q${q}-${dedup ? 'nofact' : 'dup'}`]

  verdicts.push('【① 事实重复副本的影响】（同 sal / 同 q，只切蒸馏器）')
  for (const sal of ['oracle', 'predicted'] as SalKind[]) {
    for (const q of [1, 0.6, 0.3]) {
      const dup = R(sal, q, false)
      const no = R(sal, q, true)
      verdicts.push(
        `  ${sal} q=${q}: 有副本 recall@8 ${dup.recall[MAXK].toFixed(4)}（池 ${dup.poolSize.toFixed(0)}）`
        + ` vs 无副本 ${no.recall[MAXK].toFixed(4)}（池 ${no.poolSize.toFixed(0)}）→ ${(no.recall[MAXK] - dup.recall[MAXK] >= 0 ? '+' : '')}${(no.recall[MAXK] - dup.recall[MAXK]).toFixed(4)}`,
      )
    }
  }
  const dedupGain = R('oracle', 1, true).recall[MAXK] - R('oracle', 1, false).recall[MAXK]
  verdicts.push(`  ⇒ 在"不剪枝"（q=1）下，去掉重复副本使 oracle 的 recall@8 变化 ${dedupGain >= 0 ? '+' : ''}${dedupGain.toFixed(4)}。`)
  verdicts.push(`     ${Math.abs(dedupGain) > 0.01
    ? '重复副本对 recall@K 有实质影响 ⇒ **既有全部 recall@K 数字都受此影响**，'
    + '报告时必须声明"命中集合含 fact_ 副本"，或统一改用无副本口径。'
    : '重复副本对 recall@K 影响很小 ⇒ 该混淆可以排除。'}`)
  verdicts.push('')
  verdicts.push('【② 池子规模的非线性】（oracle，证据存活率≈1 区间内，只变池子大小）')
  for (const q of QS) {
    const a = R('oracle', q, true)
    verdicts.push(`  q=${q}: distinct ${a.distinct.toFixed(0)}  evSurv ${a.evidenceSurvival.toFixed(4)}  recall@8 ${a.recall[MAXK].toFixed(4)}`)
  }
  const flat = QS.filter(q => R('oracle', q, true).evidenceSurvival > 0.99)
  if (flat.length >= 2) {
    const lo = flat[flat.length - 1]
    const hi = flat[0]
    const a = R('oracle', lo, true).recall[MAXK]
    const b = R('oracle', hi, true).recall[MAXK]
    verdicts.push(`  ⇒ 在证据一条不丢的区间（q ∈ [${lo}, ${hi}]）内，池子 ${R('oracle', lo, true).poolSize.toFixed(0)} → ${R('oracle', hi, true).poolSize.toFixed(0)}，`)
    verdicts.push(`     recall@8 从 ${a.toFixed(4)} 变到 ${b.toFixed(4)}（${b - a >= 0 ? '+' : ''}${(b - a).toFixed(4)}）。`)
    verdicts.push(`     ${Math.abs(b - a) > 0.05
      ? '⇒ **检索精度强烈依赖干扰项数量**，而与"选了哪条"无关。'
      + '任何"剪枝提升检索精度"的主张若不控制池子规模，都无法与"单纯减少干扰项"区分。'
      : '⇒ 池子规模在证据全保留区间内影响有限，非线性不构成主要混淆。'}`)
  }

  console.info('--- 判读（本段由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts) console.info(v)

  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })
  const jsonPath = join(outDir, `p2-index-duplication-confusion-${stamp}.json`)
  writeFileSync(jsonPath, `${JSON.stringify({
    generatedAt: new Date().toISOString(),
    corpus: { path, sha256: sha256File(path), conversations: convs.length },
    ks: KS,
    quantileGrid: QS,
    arms: Object.fromEntries(ARMS.map(a => [a.key, { ...S[a.key], label: a.label }])),
    verdicts,
  }, null, 2)}\n`, 'utf8')
  console.info()
  console.info(`artifact: ${jsonPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
