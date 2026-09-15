import type { BioticMemory, GatingCoefficients, LocomoConversation } from '../src/index'

/**
 * 诊断：`retrievalFloor` 是否让 ON/OFF 变得**不可比**。
 *
 * ── 假设 ────────────────────────────────────────────────────────────────
 * `evidenceRecall()` 的命中判据是：
 *     `candidates.has(c.id) && c.score > mem.config.retrievalFloor`   (floor = 0.02)
 *
 * 注意 floor 只在**指标层**生效，`store.retrieve()` 内部并不用它。
 * 而门控 ON 会**剪掉大量 trivial 记忆**，这会让记忆池的规模与词频统计发生变化，
 * 从而整体改变检索分数的尺度。
 *
 * ⇒ 若 ON 因池子变小而使分数整体下移，其证据项就更容易跌破 0.02；
 *   此时 ON 被记为"未命中"，**不是因为它没检索到，而是因为它的分数尺度变了**。
 *   于是 ON 反而低于 OFF —— 这与 2026-09-15 重跑观察到的符号反转一致。
 *
 * ── 本脚本做什么 ─────────────────────────────────────────────────────────
 * 对同一批 (condition, question) 同时算两种判据：
 *   A. 带 floor（现行指标，可复现 p1.5-recall.ts 的数）
 *   B. 不带 floor（纯 top-K 命中，秩判据）
 *
 * 若 A 下 ON < OFF 而 B 下 ON > OFF，则结论是：
 *   符号反转由**指标阈值**造成，而非检索能力或门控机制。
 *
 * 用法：tsx eval/diag-floor-effect.ts [path-to-locomo.json]
 */
import process from 'node:process'

import { buildMemory, DEFAULT_GATING, loadLocomo, NO_GATING } from '../src/index'
import { resolveLocomoPath, sha256File } from './locomo-path'

const path = resolveLocomoPath(process.argv[2]).path
const conversations = loadLocomo(path) as LocomoConversation[]
const K = 4

interface Acc { withFloorHit: number, noFloorHit: number, n: number, scoreSum: number, scoreMax: number, belowFloor: number }

function evaluate(conv: LocomoConversation, mem: BioticMemory, floor: number): Acc {
  const acc: Acc = { withFloorHit: 0, noFloorHit: 0, n: 0, scoreSum: 0, scoreMax: 0, belowFloor: 0 }
  for (const q of conv.qa) {
    const candidates = new Set<string>()
    for (const e of q.evidence ?? []) {
      if (!conv.evidenceIds.has(e))
        continue
      candidates.add(e)
      candidates.add(`fact_${e}`)
    }
    if (candidates.size === 0)
      continue
    const top = mem.retrieve(q.question, K, false)
    const inTop = top.filter(c => candidates.has(c.id))
    acc.n++
    if (inTop.length > 0) {
      acc.noFloorHit++ // B：只要进了 top-K 就算命中
      const s = Math.max(...inTop.map(c => c.score))
      acc.scoreSum += s
      acc.scoreMax = Math.max(acc.scoreMax, s)
      if (s > floor)
        acc.withFloorHit++ // A：还要超过 floor
      else
        acc.belowFloor++
    }
  }
  return acc
}

function merge(accs: Acc[]): Acc {
  return accs.reduce((a, b) => ({
    withFloorHit: a.withFloorHit + b.withFloorHit,
    noFloorHit: a.noFloorHit + b.noFloorHit,
    n: a.n + b.n,
    scoreSum: a.scoreSum + b.scoreSum,
    scoreMax: Math.max(a.scoreMax, b.scoreMax),
    belowFloor: a.belowFloor + b.belowFloor,
  }), { withFloorHit: 0, noFloorHit: 0, n: 0, scoreSum: 0, scoreMax: 0, belowFloor: 0 })
}

const floor = 0.02
const conds = [
  { name: 'ON ', gating: DEFAULT_GATING },
  { name: 'OFF', gating: NO_GATING },
]

console.info('=== retrievalFloor 对 ON/OFF 可比性的影响 ===')
console.info(`corpus : ${path}`)
console.info(`sha256 : ${sha256File(path)}`)
console.info(`K      : ${K}   floor : ${floor}`)
console.info()

const results: Record<string, Acc> = {}
for (const c of conds) {
  const per: Acc[] = []
  for (const conv of conversations) {
    const mem = await buildMemory(conv, c.gating as GatingCoefficients)
    per.push(evaluate(conv, mem, floor))
  }
  results[c.name] = merge(per)
}

function r(name: string) {
  const a = results[name]
  return {
    A: a.withFloorHit / a.n,
    B: a.noFloorHit / a.n,
    meanScore: a.scoreSum / a.noFloorHit,
    maxScore: a.scoreMax,
    below: a.belowFloor / a.noFloorHit,
    n: a.n,
  }
}

const on = r('ON ')
const off = r('OFF')

console.info('--- A. 带 floor（现行指标）---')
console.info(`  ON  recall@${K} = ${on.A.toFixed(3)}`)
console.info(`  OFF recall@${K} = ${off.A.toFixed(3)}`)
console.info(`  gap(ON-OFF)    = ${(on.A - off.A).toFixed(4)}`)
console.info()
console.info('--- B. 不带 floor（纯 top-K 命中）---')
console.info(`  ON  hit@${K} = ${on.B.toFixed(3)}`)
console.info(`  OFF hit@${K} = ${off.B.toFixed(3)}`)
console.info(`  gap(ON-OFF)  = ${(on.B - off.B).toFixed(4)}`)
console.info()
console.info('--- 分数尺度 ---')
console.info(`  ON  命中项平均分 = ${on.meanScore.toFixed(4)}   最大 ${on.maxScore.toFixed(4)}   跌破 floor 的比例 ${(on.below * 100).toFixed(1)}%`)
console.info(`  OFF 命中项平均分 = ${off.meanScore.toFixed(4)}   最大 ${off.maxScore.toFixed(4)}   跌破 floor 的比例 ${(off.below * 100).toFixed(1)}%`)
console.info(`  样本题数 ON=${on.n} OFF=${off.n}`)
console.info()
console.info('--- 判定 ---')
const aGap = on.A - off.A
const bGap = on.B - off.B
if (aGap < 0 && bGap > 0) {
  console.info('  🔴 符号反转确诊：带 floor 时 ON < OFF，不带 floor 时 ON > OFF。')
  console.info('     ⇒ recall 的方向由**指标阈值**决定，不由检索能力决定。')
  console.info('     ⇒ ON/OFF 在当前 floor 下**不可比**，因为门控改变了分数尺度。')
  console.info('     ⇒ 修法：要么去掉 floor（用秩判据），要么让 floor 随条件自适应，')
  console.info('        要么报告分数分布并证明两条件尺度可比。')
}
else if (aGap < 0 && bGap < 0) {
  console.info('  🟠 两种判据下 ON 都 ≤ OFF ⇒ 不是 floor 造成的，')
  console.info('     需回到 src/retrieval.ts 与 src/gating.ts 查真实检索/剪枝回归。')
}
else if (aGap > 0 && bGap > 0) {
  console.info('  🟢 两种判据下 ON 都 > OFF ⇒ 与 2026-09-09 报告方向一致；')
  console.info('     那么 09-15 重跑得到反号的原因另在别处（需查 buildMemory 的调用参数）。')
}
else {
  console.info(`  🟠 情形不明（A gap=${aGap.toFixed(4)}, B gap=${bGap.toFixed(4)}），需人工判读。`)
}
