import type { BioticMemory, LocomoConversation } from '../src/index'

/**
 * 记忆线评估脚本共用的指标实现。
 *
 * 存在的理由：`diag-oracle-vs-predicted-salience.ts` 与
 * `p2-quantile-retention-sweep.ts` 需要**逐位相同**的 recall@K 定义。
 * 各写一份必然在某次修改后悄悄分叉，而两个脚本的数字还要互相比较 ——
 * 这正是《记忆线复现性核查报告》点名的那类"看起来是结论、其实与代码无关"的隐患。
 */

export const KS = [1, 2, 4, 8]

export const avg = (a: number[]): number => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0)

export interface Metrics {
  /** recall@K：金标准证据出现在 top-K 且高于 `retrievalFloor` 的题目比例。 */
  recall: Record<number, number>
  /** 命中项平均分：出现证据候选的题目中，该候选最高分的均值。 */
  hitScoreMean: number
  /** 证据存活率：金标准证据 episode 中未被遗忘的比例。 */
  evidenceSurvival: number
  /** 被剪掉（forgotten）的 episode 总数。 */
  prunedTotal: number
  /** 可检索池大小：`retrieve()` 真正会考虑的候选数。 */
  poolSize: number
}

/** 所有题目引用的、且能在 `conv.evidenceIds` 中解析的金标准证据 id。 */
export function goldEvidenceIds(conv: LocomoConversation): Set<string> {
  const ids = new Set<string>()
  for (const q of conv.qa) {
    for (const e of q.evidence ?? []) {
      if (conv.evidenceIds.has(e))
        ids.add(e)
    }
  }
  return ids
}

/**
 * 测量一个已建好的记忆实例。
 *
 * 注意：只对每题调用 `retrieve` **一次**（取 `max(KS)` 的排序），再按位置还原各 K
 * 的命中。`retrieve` 总是给全量候选打分后截断，所以 top-k 就是该排序的前 k 项 ——
 * 逐 K 重调会把同一排序重复算 4 遍，且在大语料上会因稠密化内存被 SIGTERM。
 */
export function measure(mem: BioticMemory, conv: LocomoConversation, gold: Set<string>): Metrics {
  const floor = mem.config.retrievalFloor
  const maxK = Math.max(...KS)
  const covered: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  const hitScores: number[] = []

  for (const q of conv.qa) {
    const candidates = new Set<string>()
    for (const e of q.evidence ?? []) {
      if (!conv.evidenceIds.has(e))
        continue
      candidates.add(e)
      candidates.add(`fact_${e}`)
    }

    const ranking = mem.retrieve(q.question, maxK, false)
    const hitAtK: Record<number, boolean> = Object.fromEntries(KS.map(k => [k, false]))
    let best = Number.NEGATIVE_INFINITY

    for (let i = 0; i < ranking.length; i++) {
      const c = ranking[i]
      if (!candidates.has(c.id))
        continue
      if (c.score > best)
        best = c.score
      if (c.score > floor) {
        for (const k of KS) {
          if (i + 1 <= k)
            hitAtK[k] = true
        }
      }
    }

    for (const k of KS) {
      if (hitAtK[k])
        covered[k]++
    }
    if (best > Number.NEGATIVE_INFINITY)
      hitScores.push(best)
  }

  const forgotten = mem.episodes.filter(e => e.forgotten && gold.has(e.id)).length
  return {
    recall: Object.fromEntries(KS.map(k => [k, covered[k] / conv.qa.length])),
    hitScoreMean: avg(hitScores),
    evidenceSurvival: gold.size ? 1 - forgotten / gold.size : 1,
    prunedTotal: mem.episodes.filter(e => e.forgotten).length,
    poolSize:
      mem.episodes.filter(e => !e.forgotten).length + mem.facts.length + mem.procedural.length + mem.working.length,
  }
}

/** 确定性 PRNG（与仓库其他处同族）。 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296
  }
}

/** Fisher–Yates，用给定 rnd。返回新数组，不改原数组。 */
export function shuffledCopy<T>(src: T[], rnd: () => number): T[] {
  const a = src.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rnd() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}
