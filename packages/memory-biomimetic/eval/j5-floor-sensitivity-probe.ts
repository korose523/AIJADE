import type { GatingCoefficients, RetrievalScoreMode } from '../src/index'

/**
 * floor 敏感性探针：`retrievalFloor` 对recall@8 的影响，按打分模式分列。
 *
 * ── 为什么这个探针要长期留在仓库里 ─────────────────────────────────────
 * `retrievalFloor`（默认 0.02）在**三种打分模式下的量纲完全不同**：
 *
 * | 模式             | 分数量纲| 由什么决定|
 * |------------------|-----------------|--------------------------------------|
 * | `additive`       | ~O(0.5)      | 各分量饱和后按权重直接求和           |
 * | `standardized`   | ~O(1–5)      | 池内 z 分数，可正可负|
 * | `rrf`            | ~O(0.01–0.04)| 权重和 /(k + rank)，上限 2.3/61=0.0377 |
 *
 * 于是 **floor=0.02 对前两者是"几乎不起作用的低门槛"，对 RRF 却横切在分布中位**。
 * 实测（LoCoMo 2 对话，见 registry 的 `j5-e2e-causal-decomposition` notes）：
 * RRF 的top-8 分数 median≈0.0202，**48.3% 的候选 ≤ 0.02**，其中**21.9% 是金标准**
 * —— 也就是每5 个排进 top-8 的金标准就有 1 个被 floor 判成未命中。
 * 这就是 `rrf-e2e` 在端到端口径下塌到 0.0745 的原因，**而离线重排口径
 * （`j5-rrf-ablation.ts`）用四臂共用的 `storeScore` 过 floor，所以没踩这个坑**。
 *
 * ⚠️ 由此得到一条**推广性结论**（不限于 RRF）：
 * **任何跨 `retrievalScoreMode` 的 recall 比较，若命中判据用的是"臂自身分数"
 * 过 `retrievalFloor`，该比较无效。** 机制在 `src/locomo.ts:247`
 * （`c.score > mem.config.retrievalFloor`）——它不区分分数的量纲。
 *
 * ── 本脚本做什么 ────────────────────────────────────────────────────────
 * 对每个 (打分模式 × 去重) 组合，**只测 floor 判据的误杀情况**，不改任何产品代码：
 * · `top8BelowFloor`   —— top-8 中 score ≤ floor 的候选比例
 * · `goldBelowFloor`   —— 已排进 top-8 的金标准里，被 floor 判成未命中的比例
 *   （这一项才是真正���代价：候选被过滤只是"没被算进 top-8 的噪声"，
 *   而**已经排在第1 位却因分数不达floor 而不算命中**，是货真价实的假阴性）
 * · `median` / `max`   —— 该模式 top-8 分数的分布位置
 *
 * 判读：若某模式的 `goldBelowFloor ≈ 0` 且 median 远高于 floor，则该模式的
 * recall **不受 floor 影响**，该模式的数字可与其他模式同尺度比较。
 *
 * 用法：tsx eval/j5-floor-sensitivity-probe.ts [path-to-locomo.json] [conv-limit]
 * 默认语料与 `eval/data/locomo10.json` 一致；`conv-limit` 默认 2（探针只需看分数域，
 * 不需要全量；分数域由模式决定，2 个对话已足够稳定）。
 */
import process from 'node:process'

import { buildMemory, DEFAULT_MEMORY_CONFIG, loadLocomo, NO_GATING } from '../src/index'
import { resolveLocomoPath } from './locomo-path'

/** 默认只跑 2 个对话：探针看的是**分数域**，而非 recall 本身。 */
const DEFAULT_CONV_LIMIT = 2

interface Combo {
  mode: RetrievalScoreMode
  dedupe: boolean
}

/**
 * 覆盖 2×2 加 RRF 两臂。
 *
 * `rrf` 那一项是本探针存在的理由；前四项用于证明 **2×2 分解本身是 floor-clean 的**
 * （四格 `goldBelowFloor` 均为 0），从而"跨模式比较无效"这条结论**不会反过来
 * 侵蚀** 已入库的 2×2 数字。
 */
const COMBOS: Combo[] = [
  { mode: 'additive', dedupe: true },
  { mode: 'additive', dedupe: false },
  { mode: 'standardized', dedupe: true },
  { mode: 'standardized', dedupe: false },
  { mode: 'rrf', dedupe: true },
  { mode: 'rrf', dedupe: false },
]

const fmtPct = (x: number) => `${(x * 100).toFixed(1)}%`

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : DEFAULT_CONV_LIMIT
  const convs = loadLocomo(path).slice(0, limit)
  const floor = DEFAULT_MEMORY_CONFIG.retrievalFloor

  console.info('=== retrievalFloor 敏感性探针（只读诊断，不改产品代码）===')
  console.info(`corpus   : ${path}`)
  console.info(`convs    : ${convs.length}（探针只看分数域，无需全量）`)
  console.info(`floor    : ${floor}（DEFAULT_MEMORY_CONFIG.retrievalFloor 的默认值）`)
  console.info()

  const rows: string[] = []
  for (const combo of COMBOS) {
    const scores: number[] = []
    let top8 = 0
    let top8Below = 0
    let goldInTop8 = 0
    let goldBelow = 0

    for (const conv of convs) {
      const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)
      mem.config.retrievalScoreMode = combo.mode
      mem.config.dedupeByContent = combo.dedupe
      mem.config.weights = { ...DEFAULT_MEMORY_CONFIG.weights }

      for (const q of conv.qa) {
        // 金标准集合与 `j5-rrf-e2e-decomposition.ts` 同构造：episode 与其派生 fact 都算。
        const cand = new Set<string>()
        for (const e of q.evidence ?? []) {
          if (!conv.evidenceIds.has(e))
            continue
          cand.add(e)
          cand.add(`fact_${e}`)
        }

        const ranking = mem.retrieve(q.question, 8, false)
        for (const c of ranking) {
          scores.push(c.score)
          top8++
          if (!(c.score > floor))
            top8Below++
          if (cand.has(c.id)) {
            goldInTop8++
            if (!(c.score > floor))
              goldBelow++
          }
        }
      }
    }

    scores.sort((a, b) => a - b)
    const median = scores.length ? scores[Math.floor(scores.length / 2)] : Number.NaN
    const max = scores.length ? scores[scores.length - 1] : Number.NaN
    const goldMissRate = goldInTop8 ? goldBelow / goldInTop8 : 0
    // 判据：金标准误杀率 0 且中位数远离 floor ⇒ 该组合的 recall 不受 floor 支配。
    const clean = goldMissRate === 0 && median > floor * 10
    const label = `${combo.mode} ${combo.dedupe ? '+ 去重' : '+ 不去重'}`
    rows.push(
      `  ${label.padEnd(26)}`
      + `top8≤floor ${fmtPct(top8Below / top8).padStart(7)}`
      + `   gold ${String(goldInTop8).padStart(4)} / 误杀 ${fmtPct(goldMissRate).padStart(6)}`
      + `   median=${median.toFixed(4).padStart(8)}  max=${max.toFixed(4).padStart(8)}`
      + `   ${clean ? '✅ floor-clean' : '⚠️ 受 floor 支配'}`,
    )
  }

  console.info(`  ${'组合'.padEnd(26)}${'top-8 中<=floor'.padStart(14)}   ${'金标准误杀率'.padStart(14)}   ${'分数分布'.padStart(26)}`)
  for (const r of rows) console.info(r)
  console.info()
  console.info('判读：')
  console.info('  · additive / standardized 两档分数远高于 floor，floor 对其recall 无实质作用；')
  console.info('    ⇒ 2×2 分解（j5-rrf-e2e-decomposition）的四格是 floor-clean 的，可同尺度比较。')
  console.info('  · rrf 分数域上限仅 2.3/(k+1)=0.0377，floor=0.02 横切其中位，')
  console.info('    ⇒ 大量**已排进 top-8** 的金标准被判未命中，rrf 的端到端 recall 严重偏低。')
  console.info('  · 跨模式比较必须声明 floor 判据；命中判据见 `src/locomo.ts:247`。')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
