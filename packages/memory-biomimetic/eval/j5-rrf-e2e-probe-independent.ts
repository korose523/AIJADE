import type { GatingCoefficients } from '../src/index'
import type { RawScoreRow } from '../src/retrieval'

/**
 * RRF 实现的**破坏性探针**（独立验证，非作者自测）。
 *
 * 覆盖三件事：
 *   A. 默认未变：`DEFAULT_MEMORY_CONFIG.retrievalScoreMode === 'standardized'`，
 *      且不显式给模式的 store 与显式给 `'standardized'` 的 store 逐位相同。
 *   B. 前缀不变式：真实问题上 `retrieve(q, 8)` 的前 4 项 == `retrieve(q, 4)`。
 *   C. 边界：全平局 / 单候选 / 空池 / NaN / ±Infinity / 负 strengthRaw / 全零权重。
 *
 * 用法：tsx eval/j5-rrf-e2e-probe-independent.ts [path-to-locomo.json]
 */
import process from 'node:process'

import {
  BioticMemory,
  buildMemory,
  competitionRanksDesc,
  DEFAULT_MEMORY_CONFIG,
  DEFAULT_RETRIEVAL_WEIGHTS,
  loadLocomo,
  NO_GATING,
  scoreCandidatesRRF,
} from '../src/index'
import { resolveLocomoPath } from './locomo-path'

const W = DEFAULT_RETRIEVAL_WEIGHTS
const ZERO = { similarity: 0, strength: 0, recency: 0, context: 0, affect: 0 }
const line = (s: string) => console.info(s)

function rows(n: number, f: (i: number) => Partial<RawScoreRow>): RawScoreRow[] {
  return Array.from({ length: n }, (_, i) => ({
    similarity: 0,
    strengthRaw: 0,
    recency: 0,
    context: 0,
    affect: 0,
    ...f(i),
  }))
}

async function main(): Promise<void> {
  // ─────────────────────────────────────────────── A. 默认未变
  line('=== A. 默认未变 ===')
  line(`  DEFAULT_MEMORY_CONFIG.retrievalScoreMode = ${JSON.stringify(DEFAULT_MEMORY_CONFIG.retrievalScoreMode)}  ${DEFAULT_MEMORY_CONFIG.retrievalScoreMode === 'standardized' ? '✅' : '❌'}`)
  line(`  DEFAULT_MEMORY_CONFIG.retrievalFloor     = ${DEFAULT_MEMORY_CONFIG.retrievalFloor}`)

  const path = resolveLocomoPath(process.argv[2]).path
  const conv = loadLocomo(path)[0]
  const q0 = conv.qa[0].question

  const memDefault = await buildMemory(conv, NO_GATING as GatingCoefficients)
  line(`  buildMemory() 得到的 store.config.retrievalScoreMode = ${JSON.stringify(memDefault.config.retrievalScoreMode)}  ${memDefault.config.retrievalScoreMode === 'standardized' ? '✅' : '❌'}`)

  // 不显式给模式（连字段都删掉，模拟「'rrf' 出现之前写下的快照」）
  const memNoField = await buildMemory(conv, NO_GATING as GatingCoefficients)
  delete (memNoField.config as { retrievalScoreMode?: string }).retrievalScoreMode
  const memExplicit = await buildMemory(conv, NO_GATING as GatingCoefficients)
  memExplicit.config.retrievalScoreMode = 'standardized'

  const dump = (m: BioticMemory) => m.retrieve(q0, 20, false).map(c => `${c.id}:${c.score.toFixed(12)}`).join('|')
  const a = dump(memNoField)
  const b = dump(memExplicit)
  const c = dump(memDefault)
  line(`  字段缺失（旧快照） == 显式 'standardized' ? ${a === b ? '✅ 逐位相同' : '❌ 不同'}`)
  line(`  默认（未改配置） == 显式 'standardized'     ? ${c === b ? '✅ 逐位相同' : '❌ 不同'}`)
  if (a !== b || c !== b) {
    line(`    缺失: ${a.slice(0, 200)}`)
    line(`    显式: ${b.slice(0, 200)}`)
  }
  line()

  // ─────────────────────────────────────────────── B. 前缀不变式（真实问题）
  line('=== B. 前缀不变式（真实问题，rrf 模式）===')
  const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)
  mem.config.retrievalScoreMode = 'rrf'
  const NQ = Math.min(199, conv.qa.length)
  let violations = 0
  const examples: string[] = []
  for (let qi = 0; qi < NQ; qi++) {
    const q = conv.qa[qi].question
    const r8 = mem.retrieve(q, 8, false).map(x => x.id)
    for (const k of [1, 2, 4]) {
      const rk = mem.retrieve(q, k, false).map(x => x.id)
      const prefix = r8.slice(0, k)
      if (rk.join(',') !== prefix.join(',')) {
        violations++
        if (examples.length < 3)
          examples.push(`q#${qi} K=${k}\n      retrieve(q,${k}) = ${rk.join(',')}\n      retrieve(q,8)[:${k}] = ${prefix.join(',')}`)
      }
    }
  }
  line(`  问题数 ${NQ} × K∈{1,2,4} = ${NQ * 3} 次比对；违反 ${violations} 次  ${violations === 0 ? '✅' : '❌'}`)
  for (const e of examples) line(`    ${e}`)

  // 顺带看 standardized 与 rrf 在 K=1..8 上的 recall 是否单调（违反单调=前缀破了）
  line()

  // ─────────────────────────────────────────────── C. 边界
  line('=== C. 边界 ===')
  const show = (label: string, rs: RawScoreRow[], w = W) => {
    try {
      const out = scoreCandidatesRRF(rs, w)
      const scores = out.map(o => (Number.isFinite(o.score) ? o.score.toFixed(6) : String(o.score)))
      const anyBad = out.some(o => !Number.isFinite(o.score))
      line(`  ${label.padEnd(34)} n=${String(rs.length).padEnd(3)} scores=[${scores.join(', ')}]${anyBad ? '  ❌ 出现非有限值' : ''}`)
    }
    catch (e) {
      line(`  ${label.padEnd(34)} ❌ 抛出：${(e as Error).message}`)
    }
  }

  show('全平局（5 条，每个分量都相等）', rows(5, () => ({ similarity: 0.5, strengthRaw: 1, recency: 1, context: 1 })))
  show('单候选', rows(1, () => ({ similarity: 0.9, strengthRaw: 2, recency: 0.5, context: 0.3 })))
  show('空池', rows(0, () => ({})))
  show('similarity 含 NaN', rows(4, i => ({ similarity: i === 1 ? Number.NaN : i / 4, strengthRaw: i, recency: i / 4, context: i / 4 })))
  show('similarity 含 +Infinity', rows(4, i => ({ similarity: i === 0 ? Number.POSITIVE_INFINITY : i / 4, strengthRaw: i, recency: i / 4, context: i / 4 })))
  show('similarity 含 -Infinity', rows(4, i => ({ similarity: i === 0 ? Number.NEGATIVE_INFINITY : i / 4, strengthRaw: i, recency: i / 4, context: i / 4 })))
  show('similarity 全 NaN', rows(3, () => ({ similarity: Number.NaN, strengthRaw: 1, recency: 1, context: 1 })))
  show('strengthRaw = -1（饱和后 -Inf）', rows(3, i => ({ similarity: i / 4, strengthRaw: -1, recency: i / 4, context: i / 4 })))
  show('strengthRaw = Infinity（饱和后 NaN）', rows(3, i => ({ similarity: i / 4, strengthRaw: Number.POSITIVE_INFINITY, recency: i / 4, context: i / 4 })))
  show('recency = NaN 且 context = -Infinity', rows(3, i => ({ similarity: i / 4, strengthRaw: i, recency: Number.NaN, context: Number.NEGATIVE_INFINITY })))
  show('全零权重', rows(3, i => ({ similarity: i / 4, strengthRaw: i, recency: i / 3, context: i / 2 })), ZERO)
  show('负权重', rows(3, i => ({ similarity: i / 4, strengthRaw: i, recency: i / 3, context: i / 2 })), { ...W, similarity: -1 })

  // competitionRanksDesc 直接探针
  line('  competitionRanksDesc:')
  const cr = (xs: number[]) => `[${competitionRanksDesc(xs).join(', ')}]`
  line(`    [5,5,5,5]        -> ${cr([5, 5, 5, 5])}   （全平局：期望 [2.5,2.5,2.5,2.5]）`)
  line(`    [3,1,2]          -> ${cr([3, 1, 2])}   （期望 [1,3,2]）`)
  line(`    [1,2,2,3]        -> ${cr([1, 2, 2, 3])}   （期望 [4,2.5,2.5,1]）`)
  line(`    [NaN,1,2]        -> ${cr([Number.NaN, 1, 2])}`)
  line(`    [Inf,1,2]        -> ${cr([Number.POSITIVE_INFINITY, 1, 2])}`)
  line(`    []               -> ${cr([])}`)

  // 空池：store 端到端
  line('  store 端到端（空记忆）：')
  try {
    const empty = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG })
    const out = empty.retrieve('anything at all', 8, false)
    line(`    retrieve 返回 ${out.length} 条  ${out.length === 0 ? '✅' : '❌'}`)
  }
  catch (e) {
    line(`    ❌ 抛出：${(e as Error).message}`)
  }
  try {
    const emptyRrf = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, retrievalScoreMode: 'rrf' })
    const out = emptyRrf.retrieve('anything at all', 8, false)
    line(`    rrf 模式 retrieve 返回 ${out.length} 条  ${out.length === 0 ? '✅' : '❌'}`)
  }
  catch (e) {
    line(`    ❌ rrf 抛出：${(e as Error).message}`)
  }
  // 单条记忆
  try {
    const one = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, retrievalScoreMode: 'rrf' })
    one.encode({ id: 'e1', content: 'Caroline went to the LGBTQ support group on 7 May 2023', createdAt: Date.now(), context: { tags: ['x'] } })
    const out = one.retrieve('LGBTQ support group', 8, false)
    line(`    单条记忆 rrf retrieve 返回 ${out.length} 条 score=${out.map(o => o.score.toFixed(6)).join(',')}  ${out.length === 1 && Number.isFinite(out[0].score) ? '✅' : '❌'}`)
  }
  catch (e) {
    line(`    ❌ 单条记忆 rrf 抛出：${(e as Error).message}`)
  }
  // 全平局：多条内容相同、时间相同
  try {
    const tie = new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, retrievalScoreMode: 'rrf' })
    for (let i = 0; i < 5; i++)
      tie.encode({ id: `t${i}`, content: 'identical content here', createdAt: 1_700_000_000_000, context: { tags: ['a'] } })
    const out = tie.retrieve('identical', 8, false)
    const uniq = new Set(out.map(o => o.score.toFixed(12)))
    line(`    5 条全同记忆 rrf：返回 ${out.length} 条，不同分数个数 ${uniq.size}（全平局应为 1，去重后可能只剩 1 条）scores=${out.map(o => o.score.toFixed(6)).join(',')}`)
  }
  catch (e) {
    line(`    ❌ 全平局 rrf 抛出：${(e as Error).message}`)
  }
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
