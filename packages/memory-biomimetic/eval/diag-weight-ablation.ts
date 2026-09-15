import type { GatingCoefficients } from '../src/index'

import process from 'node:process'

/**
 * 权重消融：检索分数里的 `recency`(0.3) 与 `strength`(0.6) 是否让"新近"压过了"相关"？
 *
 * ── 问题从哪来 ───────────────────────────────────────────────────────────
 * `eval/diag-oracle-tiebreak.ts` 证实了一个 cliff：oracle 显著性下**证据一条不丢**，
 * 仅仅把"最近的干扰项"从池子里去掉，`recall@8` 就从 0.1123 跳到 0.3524。
 * 假设机制：证据记忆被**更近的干扰项**挤出了 top-K。
 * 这是**推断**，尚未逐条核验 —— 这正是《记忆线复现性核查报告》§7.8 列为
 * "下一步的第一件事"的那一项。
 *
 * ── 本脚本做两件事 ───────────────────────────────────────────────────────
 * **① 逐条核验偏置**：对每道题，取 top-8，数其中有多少条**比该题的金标准证据更晚**
 *    （createdAt 更大）。若无偏置，该数应接近"池子里更晚的项占比"；
 *    若系统性地高，则排序确实由"新近"驱动。
 *
 * **② 权重消融（决定性的、可行动的）**：
 *    `retrieve()` 返回的 `ScoredCandidate` 公开了 `parts = { similarity, strength, recency, context }`。
 *    于是可以对**同一批候选**用任意权重组合重新排序，测各自 `recall@K` ——
 *    这排除了"换了检索器"这类混杂，只动权重。
 *    若"只用相似度"远胜"现行权重"，那就不是"门控不好"，而是**打分函数本身把相关性压掉了**。
 *
 * ── 口径声明（重要）──────────────────────────────────────────────────────
 * 重排只在**现行打分的前 N 条**内进行（N = RERANK_POOL），不是全池。
 * 理由：`retrieve()` 的冲突惩罚是 O(topK²)，取全池(≈1176)会有 1.4M 次内层迭代/题 × 近 2000 题。
 * 代价：对与现行权重差异极大的组合（尤其"只用 recency"）存在选择偏差，其数字只能当**下界**读。
 * 结论只依赖"只用相似度"这一档 —— 而相似度正是现行分数里权重最高、最不会被前 N 条筛掉的项，
 * 故该档偏差最小。
 *
 * 用法：tsx eval/diag-weight-ablation.ts [path-to-locomo.json] [conv-limit]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { buildMemory, loadLocomo, NO_GATING } from '../src/index'
import { avg, goldEvidenceIds, KS } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

/**
 * 重排所用的候选池：现行打分的前 N 条。见文件头"口径声明"。
 *
 * 定这个数字的约束：`retrieve()` 的冲突惩罚是 O(topK²) 且每次配对都跑两个正则，
 * N=400 时单题就有 ~8 万次 `detectConflict` ⇒ 直接 SIGTERM（实测）。
 * N=150 时约 1.1 万次，整轮可跑完。代价是截断偏差变大，故结论只读**方向**与**下界**。
 */
const RERANK_POOL = 150
const MAXK = Math.max(...KS)

interface Weights {
  key: string
  similarity: number
  strength: number
  recency: number
  context: number
  note: string
}

const WCONFIGS: Weights[] = [
  { key: 'current', similarity: 1, strength: 0.6, recency: 0.3, context: 0.4, note: '现行 DEFAULT_RETRIEVAL_WEIGHTS' },
  { key: 'sim-only', similarity: 1, strength: 0, recency: 0, context: 0, note: '只用相似度（相关性优先）' },
  { key: 'sim+ctx', similarity: 1, strength: 0, recency: 0, context: 0.4, note: '相似度 + 上下文' },
  { key: 'sim+str', similarity: 1, strength: 0.6, recency: 0, context: 0, note: '相似度 + 强度（去新近项）' },
  { key: 'no-recency', similarity: 1, strength: 0.6, recency: 0, context: 0.4, note: '现行权重但把 recency 置 0' },
  { key: 'sim-heavy', similarity: 3, strength: 0.6, recency: 0.3, context: 0.4, note: '相似度 ×3' },
  { key: 'str-only', similarity: 0, strength: 1, recency: 0, context: 0, note: '只用强度（极端对照）' },
  { key: 'rec-only', similarity: 0, strength: 0, recency: 1, context: 0, note: '只用新近（极端对照，受池截断影响最大）' },
]

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== 权重消融 + 新近偏置逐条核验 ===')
  console.info(`corpus : ${path}`)
  console.info(`sha256 : ${sha256File(path)}`)
  console.info(`convs  : ${convs.length}`)
  console.info(`condition: NO_GATING（不剪枝、不重加权，隔离出纯检索器行为）`)
  console.info()

  const recall: Record<string, Record<number, number[]>> = {}
  for (const w of WCONFIGS)
    recall[w.key] = Object.fromEntries(KS.map(k => [k, [] as number[]]))

  // 新近偏置统计
  const newerCounts: number[] = [] // top-8 中比金标准证据更晚的条数
  const poolNewerShare: number[] = [] // 池子里比金标准证据更晚的项占比（作参照基线）
  const slotAge: number[] = [] // top-8 的年龄分位均值
  let scanned = 0
  let evidenceMissing = 0

  for (const conv of convs) {
    const gold = goldEvidenceIds(conv)
    const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)
    const floor = mem.config.retrievalFloor
    const createdById = new Map(conv.episodes.map(e => [e.id, e.createdAt]))
    const allCreatedAt = conv.episodes.map(e => e.createdAt).sort((a, b) => a - b)
    const agePercentile = (t: number): number => {
      // 二分找 t 在全集中的分位
      let lo = 0
      let hi = allCreatedAt.length
      while (lo < hi) {
        const mid = (lo + hi) >> 1
        if (allCreatedAt[mid] < t)
          lo = mid + 1
        else hi = mid
      }
      return allCreatedAt.length ? lo / allCreatedAt.length : 0
    }

    // 先给每道题拿一次候选（按现行分数排的前 RERANK_POOL 条）
    const perQuestion: { cands: { id: string, score: number, similarity: number, strength: number, recency: number, context: number }[], ev: Set<string>, evTs: number | null }[] = []

    for (const q of conv.qa) {
      const cands = mem.retrieve(q.question, RERANK_POOL, false).map(c => ({
        id: c.id,
        score: c.score,
        similarity: c.parts.similarity,
        strength: c.parts.strength,
        recency: c.parts.recency,
        context: c.parts.context,
      }))
      const ev = new Set<string>()
      for (const e of q.evidence ?? []) {
        if (!conv.evidenceIds.has(e))
          continue
        ev.add(e)
        ev.add(`fact_${e}`)
      }
      // 用最早的那条金标准证据作为"该题证据时间"
      let evTs: number | null = null
      for (const e of q.evidence ?? []) {
        const t = createdById.get(e)
        if (t !== undefined && (evTs === null || t > evTs))
          evTs = t
      }
      perQuestion.push({ cands, ev, evTs })
    }

    for (const w of WCONFIGS) {
      const key = w.key
      for (const pq of perQuestion) {
        const ranked = pq.cands
          .map(c => ({
            id: c.id,
            score: c.score,
            v: w.similarity * c.similarity + w.strength * c.strength + w.recency * c.recency + w.context * c.context,
          }))
          .sort((a, b) => b.v - a.v)
        for (const k of KS) {
          // floor 判据沿用该候选在**现行打分**下的分数，使各权重档的准入条件一致
          const hit = ranked.slice(0, k).some(c => pq.ev.has(c.id) && c.score > floor)
          recall[key][k].push(hit ? 1 : 0)
        }
      }
    }

    // 新近偏置：只看现行权重的 top-8
    const cur = WCONFIGS.find(w => w.key === 'current')!
    for (const pq of perQuestion) {
      scanned++
      if (pq.evTs === null) {
        evidenceMissing++
        continue
      }
      const ranked = pq.cands
        .map(c => ({ id: c.id, v: cur.similarity * c.similarity + cur.strength * c.strength + cur.recency * c.recency + cur.context * c.context }))
        .sort((a, b) => b.v - a.v)
        .slice(0, MAXK)

      let newer = 0
      for (const c of ranked) {
        const t = createdById.get(c.id) ?? createdById.get(c.id.replace(/^fact_/, ''))
        if (t !== undefined && t > pq.evTs)
          newer++
      }
      newerCounts.push(newer)
      slotAge.push(avg(ranked.map(c => agePercentile(createdById.get(c.id) ?? createdById.get(c.id.replace(/^fact_/, '')) ?? 0))))
      // 无偏置时的期望：top-8 中"比证据更晚"的条数 = 池里更新项占比 × K
      poolNewerShare.push(1 - agePercentile(pq.evTs))
    }
  }

  // ---------------------------------------------------------------- 输出
  console.info(`  ${'weights'.padEnd(12)}${'sim'.padStart(5)}${'str'.padStart(5)}${'rec'.padStart(5)}${'ctx'.padStart(5)}${KS.map(k => `K=${k}`.padStart(9)).join('')}   note`)
  for (const w of WCONFIGS) {
    console.info(
      `  ${w.key.padEnd(12)}${String(w.similarity).padStart(5)}${String(w.strength).padStart(5)}${String(w.recency).padStart(5)}${String(w.context).padStart(5)}`
      + `${KS.map(k => avg(recall[w.key][k]).toFixed(4).padStart(9)).join('')}   ${w.note}`,
    )
  }
  console.info()
  console.info('--- 新近偏置逐条核验（现行权重的 top-8）---')
  const biasTop8 = avg(newerCounts)
  const biasBaseline = avg(poolNewerShare) * MAXK
  console.info(`  已扫描题目                 : ${scanned}`)
  console.info(`  无证据时间戳（跳过）        : ${evidenceMissing}`)
  console.info(`  top-8 中比金标准证据更晚的条数 : 实测均值 ${biasTop8.toFixed(2)} / ${MAXK}`)
  console.info(`  若无偏置的期望基线          : 分位 × ${MAXK} ≈ ${biasBaseline.toFixed(2)}`)
  console.info(`  top-8 的年龄分位均值        : ${avg(slotAge).toFixed(3)}（愈大愈"新"）`)
  console.info()

  // ---------------------------------------------------------------- 判读
  const R = (k: string) => avg(recall[k][MAXK])
  const curR = R('current')
  const simR = R('sim-only')
  const noRecR = R('no-recency')
  const simHeavyR = R('sim-heavy')
  const recR = R('rec-only')
  const verdicts: string[] = []
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`

  verdicts.push('【① 新近偏置是否存在】')
  verdicts.push(`  top-8 中"比证据更晚"的条数 ${biasTop8.toFixed(2)} vs 无偏置基线 ${biasBaseline.toFixed(2)}`)
  verdicts.push(`  ⇒ ${biasTop8 > biasBaseline * 1.15
    ? '✅ 偏置存在：top-8 显著偏向"更晚"的记忆，超过池子的自然分位。'
    : biasTop8 > biasBaseline
      ? '🟠 偏置方向存在但幅度有限，不足以单独解释 cliff。'
      : '❌ 未见偏置：top-8 的"更晚"条数不高于自然基线。'}`)
  verdicts.push('')
  verdicts.push(`【② 权重消融】(K=${MAXK}，候选池固定为现行打分前 ${RERANK_POOL} 条)`)
  verdicts.push(`  current   ${curR.toFixed(4)}   （基准）`)
  verdicts.push(`  sim-only  ${simR.toFixed(4)}   ${fmt(simR - curR)}`)
  verdicts.push(`  no-recency${noRecR.toFixed(4)}   ${fmt(noRecR - curR)}`)
  verdicts.push(`  sim-heavy ${simHeavyR.toFixed(4)}   ${fmt(simHeavyR - curR)}`)
  verdicts.push(`  rec-only  ${recR.toFixed(4)}   ${fmt(recR - curR)}  ← 受池截断影响最大，只当下界读`)
  verdicts.push('')
  verdicts.push('【③ 结论】')
  if (simR - curR > 0.02 || noRecR - curR > 0.02) {
    verdicts.push(`  ⇒ 只用相似度 ${simR.toFixed(4)} / 去掉 recency ${noRecR.toFixed(4)} **都优于**现行权重 ${curR.toFixed(4)}。`)
    verdicts.push('     即：**打分函数里的非相关性项（recency / strength）在系统性地损害检索**。')
    verdicts.push('     这把"门控失效"的归因再向下推了一层 —— 真正的瓶颈是**打分函数的权重配比**，')
    verdicts.push('     门控只是被它放大的表象。')
    verdicts.push(`  ⇒ 可行动的改动：把 recency 权重调低或置 0，或对 similarity 做加权归一（sim-heavy ${simHeavyR.toFixed(4)}）。`)
  }
  else {
    verdicts.push(`  ⇒ 消融未见改善（最佳 ${Math.max(simR, noRecR, simHeavyR).toFixed(4)} vs 现行 ${curR.toFixed(4)}）。`)
    verdicts.push('     权重配比不是瓶颈，须回到池子构成与指标口径上找原因。')
  }
  verdicts.push('')
  verdicts.push(`⚠️ 口径限制：重排仅在现行打分的前 ${String(RERANK_POOL)} 条内进行，`)
  verdicts.push('   故与现行权重差异极大的组合（rec-only 尤甚）的数字只能当作**下界**。')
  verdicts.push('   结论只依赖 sim-only / no-recency 两档 —— 相似度是现行分数权重最高的项，受截断影响最小。')

  console.info('--- 判读（本段由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts) console.info(v)

  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })
  const jsonPath = join(outDir, `p2-weight-ablation-${stamp}.json`)
  writeFileSync(jsonPath, `${JSON.stringify({
    generatedAt: new Date().toISOString(),
    corpus: { path, sha256: sha256File(path), conversations: convs.length },
    rerankPool: RERANK_POOL,
    condition: 'NO_GATING',
    ks: KS,
    weights: WCONFIGS,
    recallByWeights: Object.fromEntries(WCONFIGS.map(w => [w.key, Object.fromEntries(KS.map(k => [k, avg(recall[w.key][k])]))])),
    recencyBias: {
      scanned,
      evidenceMissing,
      meanNewerInTopK: biasTop8,
      baselineIfUnbiased: biasBaseline,
      meanSlotAgePercentile: avg(slotAge),
    },
    verdicts,
  }, null, 2)}\n`, 'utf8')
  console.info()
  console.info(`artifact: ${jsonPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
