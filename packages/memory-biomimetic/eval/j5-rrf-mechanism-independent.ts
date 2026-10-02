/**
 * 机制拆解：端到端 RRF 的缺口，是不是由**非 similarity 分量**造成的？
 *
 * 若 RRF + similarity-only 权重 ≈ standardized + similarity-only 的召回，
 * 而 RRF + DEFAULT 权重远低于它，则缺口来自 strength/recency/context 在
 * `w/(k+rank)` 下的名次噪声，而不是 RRF 这个融合规则本身。
 *
 * 用法：tsx eval/j5-rrf-mechanism-independent.ts [path] [conv-limit]
 */
import type { GatingCoefficients, RetrievalWeights } from '../src/index'

import process from 'node:process'

import { buildMemory, DEFAULT_MEMORY_CONFIG, DEFAULT_RETRIEVAL_WEIGHTS, loadLocomo, NO_GATING } from '../src/index'
import { avg, KS } from './eval-metrics'
import { resolveLocomoPath } from './locomo-path'

const FLOOR = DEFAULT_MEMORY_CONFIG.retrievalFloor
const SIM_ONLY: RetrievalWeights = { similarity: 1, strength: 0, recency: 0, context: 0, affect: 0 }
const SIM_STR: RetrievalWeights = { similarity: 1, strength: 0.6, recency: 0, context: 0, affect: 0 }

const ARMS: { key: string, mode: 'standardized' | 'rrf', w: RetrievalWeights }[] = [
  { key: 'std / sim-only', mode: 'standardized', w: SIM_ONLY },
  { key: 'rrf / sim-only', mode: 'rrf', w: SIM_ONLY },
  { key: 'rrf / sim+strength', mode: 'rrf', w: SIM_STR },
  { key: 'rrf / DEFAULT', mode: 'rrf', w: DEFAULT_RETRIEVAL_WEIGHTS },
  { key: 'std / DEFAULT', mode: 'standardized', w: DEFAULT_RETRIEVAL_WEIGHTS },
]

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : 2
  const convs = loadLocomo(path).slice(0, limit)

  const acc: Record<string, Record<number, number[]>> = {}
  for (const a of ARMS)
    acc[a.key] = Object.fromEntries(KS.map(k => [k, [] as number[]]))
  let n = 0
  const pools: number[] = []

  for (const conv of convs) {
    const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)
    const qs = conv.qa.map((q) => {
      const gold = new Set<string>()
      for (const e of q.evidence ?? []) {
        if (!conv.evidenceIds.has(e))
          continue
        gold.add(e)
        gold.add(`fact_${e}`)
      }
      return { question: q.question, gold }
    })

    // 共享 floor 判据：store 默认（standardized + DEFAULT）全池分数。
    // **必须逐题建表** —— 噪声与冲突惩罚依赖 query，同一 id 在不同题下分数不同。
    mem.config.retrievalScoreMode = 'standardized'
    mem.config.weights = { ...DEFAULT_RETRIEVAL_WEIGHTS }
    const floorScores: Map<string, number>[] = []
    for (const q of qs) {
      const ref = mem.retrieve(q.question, 1_000_000, false)
      pools.push(ref.length)
      const m = new Map<string, number>()
      for (const c of ref)
        m.set(c.id, c.score)
      floorScores.push(m)
    }

    for (const a of ARMS) {
      mem.config.retrievalScoreMode = a.mode
      mem.config.weights = { ...a.w }
      for (let qi = 0; qi < qs.length; qi++) {
        const q = qs[qi]
        const floorScore = floorScores[qi]
        const r = mem.retrieve(q.question, 8, false)
        for (const k of KS) {
          const hit = r.slice(0, k).some(c => q.gold.has(c.id) && (floorScore.get(c.id) ?? -Infinity) > FLOOR) ? 1 : 0
          acc[a.key][k].push(hit)
        }
      }
    }
    n += qs.length
  }

  console.info(`机制拆解：${convs.length} 个对话 / ${n} 题 / 平均池 ${avg(pools).toFixed(1)}   （共享 floor = store 默认 standardized 分数）`)
  console.info(`  ${'arm'.padEnd(20)}${KS.map(k => `R@${k}`.padStart(9)).join('')}`)
  for (const a of ARMS)
    console.info(`  ${a.key.padEnd(20)}${KS.map(k => avg(acc[a.key][k]).toFixed(4).padStart(9)).join('')}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
