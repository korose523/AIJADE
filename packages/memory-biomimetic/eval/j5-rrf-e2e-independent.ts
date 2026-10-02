/**
 * J5/P4 —— RRF 的**端到端**复核（独立验证脚本，非作者自测）。
 *
 * ── 为什么要再写一个脚本 ──────────────────────────────────────────────────
 * `j5-rrf-ablation.ts` 里的 `rrf` 臂是**离线重排**：它取 `mem.retrieve(q, 150)`
 * 返回的 150 条、读它们暴露的 `parts`、在脚本里自己调 `scoreCandidatesRRF` 重排。
 * 于是它有两个结构性限制：
 *   ① 从未走 `MemoryConfig.retrievalScoreMode === 'rrf'` 这条 store 路径；
 *   ② 名次只在「现行 standardized 打分的前 150 条」这个小池子里算，而不是 store
 *      的真实全池（≈1176 条）。
 * 本脚本把 rrf 真正接进 store，让 store 在全池上排名，再取回前 150 条。
 *
 * ── 与离线脚本共享的口径（逐位对齐，保证可比）──────────────────────────────
 * · 语料：`eval/data/locomo10.json`（sha256 由脚本自检，不匹配即抛错退出）。
 * · 条件：NO_GATING（不剪枝、不重加权）。
 * · rel_i = 1 ⟺ id 是金标准 **且** 该条在「store 默认（standardized + DEFAULT
 *   权重）」下的分数 > retrievalFloor。**各臂共用同一个 floor 判据**，与离线脚本
 *   一致 —— 比较的是排序能力，不是分数量级。
 * · DCG@K = Σ rel_i / log2(i+1)；IDCG@K = 前 min(K, 池中金标准条数) 项的理想 DCG；
 *   池中无金标准（IDCG=0）记 0；recall@K = DCG@K > 0。
 * · MRR = 1/(第一个过 floor 的金标准名次)，在 150 条窗口内找，未命中记 0。
 *
 * ── 不可避免的差异（如实记录，不掩饰）────────────────────────────────────
 * 离线脚本的 150 条窗口是「standardized 前 150」—— 四臂共用同一批候选。端到端
 * 下每臂拿到的是**自己排序的前 150**（rrf 可以把离线池子根本没收录的候选捞上来，
 * 这正是端到端要测的东西），故窗口成员不再共享。为量化这一点，本脚本同时报
 *    goldInPool = 窗口口径（≈离线）/ 全池口径（端到端真实上界）
 * 两套 IDCG。
 *
 * 另外 store 端到端还会吃到**冲突惩罚**（离线重排没有）与**检索噪声**，这是
 * 「真跑一遍」的一部分，不剥离。
 *
 * 用法：tsx eval/j5-rrf-e2e-independent.ts [path-to-locomo.json] [conv-limit]
 */
import type { GatingCoefficients, RetrievalWeights } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import {
  buildMemory,
  CORRECTED_RETRIEVAL_WEIGHTS,
  DEFAULT_MEMORY_CONFIG,
  DEFAULT_RETRIEVAL_WEIGHTS,
  loadLocomo,
  NO_GATING,
} from '../src/index'
import { withProvenance } from './artifact-provenance'
import { avg, KS } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

/** 与离线消融同值：取回窗口 = 150。 */
const WINDOW = 150
/** 取全池用（冲突扫描头是常数 150，故放大 topK 不带来 O(n²) 成本）。 */
const WHOLE_POOL = 1_000_000
const EXPECTED_SHA256 = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
const FLOOR = DEFAULT_MEMORY_CONFIG.retrievalFloor

interface Arm {
  key: string
  note: string
  mode: 'standardized' | 'rrf'
  weights: RetrievalWeights
}

const SIM_ONLY: RetrievalWeights = {
  similarity: 1,
  strength: 0,
  recency: 0,
  context: 0,
  affect: 0,
}

const ARMS: Arm[] = [
  { key: 'e2e-rrf-default', note: 'store rrf + DEFAULT 权重（端到端，全池排名）', mode: 'rrf', weights: DEFAULT_RETRIEVAL_WEIGHTS },
  { key: 'e2e-std-default', note: 'store standardized + DEFAULT 权重', mode: 'standardized', weights: DEFAULT_RETRIEVAL_WEIGHTS },
  { key: 'e2e-std-sim-only', note: 'store standardized + similarity-only 权重', mode: 'standardized', weights: SIM_ONLY },
  { key: 'e2e-std-corrected', note: 'store standardized + CORRECTED 权重（recency=0）', mode: 'standardized', weights: CORRECTED_RETRIEVAL_WEIGHTS },
  { key: 'e2e-rrf-corrected', note: '【参考】store rrf + CORRECTED 权重', mode: 'rrf', weights: CORRECTED_RETRIEVAL_WEIGHTS },
]

interface Question {
  question: string
  gold: Set<string>
  floorScore: Map<string, number>
  goldInPoolWindow: number
  goldInPoolFull: number
}

/** 与 `j5-rrf-ablation.ts` 的 `measure()` 同定义。 */
function measure(
  ranking: { id: string, score: number }[],
  q: Question,
) {
  const hit: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  const ndcgW: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  const ndcgF: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  // 只用**本臂自己的分数**过 floor 的变体 —— 暴露「rrf 分数量级天然很小」这一事实。
  const hitOwn: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  let rr = 0

  const rel = (c: { id: string, score: number }, useOwn: boolean): boolean => {
    if (!q.gold.has(c.id))
      return false
    const s = useOwn ? c.score : (q.floorScore.get(c.id) ?? Number.NEGATIVE_INFINITY)
    return s > FLOOR
  }

  for (let pos = 0; pos < ranking.length; pos++) {
    if (rel(ranking[pos], false) && rr === 0)
      rr = 1 / (pos + 1)
  }

  for (const k of KS) {
    let dcg = 0
    let dcgOwn = 0
    for (let pos = 0; pos < k && pos < ranking.length; pos++) {
      if (rel(ranking[pos], false))
        dcg += 1 / Math.log2(pos + 2)
      if (rel(ranking[pos], true))
        dcgOwn += 1 / Math.log2(pos + 2)
    }
    const idcg = (n: number) => {
      let s = 0
      for (let pos = 0; pos < Math.min(k, n); pos++)
        s += 1 / Math.log2(pos + 2)
      return s
    }
    const iw = idcg(q.goldInPoolWindow)
    const ifull = idcg(q.goldInPoolFull)
    ndcgW[k] = iw > 0 ? dcg / iw : 0
    ndcgF[k] = ifull > 0 ? dcg / ifull : 0
    hit[k] = dcg > 0 ? 1 : 0
    hitOwn[k] = dcgOwn > 0 ? 1 : 0
  }
  return { hit, hitOwn, ndcgW, ndcgF, rr }
}

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const sha = sha256File(path)
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== J5/P4 RRF 端到端复核：走 store 的 retrievalScoreMode ===')
  console.info(`corpus   : ${path}`)
  console.info(`sha256   : ${sha}  ${sha === EXPECTED_SHA256 ? '✅ 与预期一致' : '❌ 与预期不一致'}`)
  console.info(`convs    : ${convs.length}`)
  console.info(`condition: NO_GATING；floor=${FLOOR}（共用 standardized 分数作判据）`)
  console.info(`window   : 每臂取自己排序的前 ${WINDOW} 条；排名在 store 全池上算`)
  console.info()

  if (sha !== EXPECTED_SHA256)
    throw new Error(`corpus sha256 mismatch: ${sha}`)

  const acc: Record<string, {
    recall: Record<number, number[]>
    recallOwn: Record<number, number[]>
    ndcgW: Record<number, number[]>
    ndcgF: Record<number, number[]>
    rr: number[]
  }> = {}
  for (const a of ARMS) {
    acc[a.key] = {
      recall: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      recallOwn: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      ndcgW: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      ndcgF: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      rr: [],
    }
  }
  let questions = 0
  const poolSizes: number[] = []

  for (const conv of convs) {
    const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)
    // 断言：buildMemory 不给显式模式 ⇒ 默认 standardized（第 4 项核验的一部分）。
    if (mem.config.retrievalScoreMode !== 'standardized')
      throw new Error(`默认模式不是 standardized：${String(mem.config.retrievalScoreMode)}`)

    const qs: Question[] = []

    for (const q of conv.qa) {
      const gold = new Set<string>()
      for (const e of q.evidence ?? []) {
        if (!conv.evidenceIds.has(e))
          continue
        gold.add(e)
        gold.add(`fact_${e}`)
      }

      // ── 参考跑：store 默认（standardized + DEFAULT）在**全池**上的排序与分数。
      // 这个分数就是各臂共用的 floor 判据（与离线脚本的 storeScore 同源）。
      mem.config.retrievalScoreMode = 'standardized'
      mem.config.weights = { ...DEFAULT_RETRIEVAL_WEIGHTS }
      const ref = mem.retrieve(q.question, WHOLE_POOL, false)
      poolSizes.push(ref.length)
      const floorScore = new Map<string, number>()
      for (const c of ref)
        floorScore.set(c.id, c.score)
      let goldInPoolWindow = 0
      let goldInPoolFull = 0
      for (let i = 0; i < ref.length; i++) {
        if (!gold.has(ref[i].id) || !(ref[i].score > FLOOR))
          continue
        if (i < WINDOW)
          goldInPoolWindow++
        goldInPoolFull++
      }
      qs.push({ question: q.question, gold, floorScore, goldInPoolWindow, goldInPoolFull })
    }

    for (const a of ARMS) {
      mem.config.retrievalScoreMode = a.mode
      mem.config.weights = { ...a.weights }
      for (const q of qs) {
        const ranking = mem.retrieve(q.question, WINDOW, false).map(c => ({ id: c.id, score: c.score }))
        const m = measure(ranking, q)
        for (const k of KS) {
          acc[a.key].recall[k].push(m.hit[k])
          acc[a.key].recallOwn[k].push(m.hitOwn[k])
          acc[a.key].ndcgW[k].push(m.ndcgW[k])
          acc[a.key].ndcgF[k].push(m.ndcgF[k])
        }
        acc[a.key].rr.push(m.rr)
      }
    }
    questions += qs.length
  }

  // ---------------------------------------------------- 可重复性自检
  // 同一 store 上把各臂连跑两轮，必须与第一轮逐位相同（证明 config 翻转没有
  // 状态残留，各臂确实跑在同一份记忆上）。
  {
    const conv0 = convs[0]
    const mem = await buildMemory(conv0, NO_GATING as GatingCoefficients)
    const q0 = conv0.qa[0].question
    const once = () => {
      const out: string[] = []
      for (const a of ARMS) {
        mem.config.retrievalScoreMode = a.mode
        mem.config.weights = { ...a.weights }
        out.push(mem.retrieve(q0, WINDOW, false).map(c => c.id).join(','))
      }
      return out.join('|')
    }
    const first = once()
    const second = once()
    console.info(`--- 可重复性自检：同一 store 连跑两轮各臂逐位相同？ ${first === second ? '✅ 是（无状态残留）' : '❌ 否'}`)
    if (first !== second)
      throw new Error('store 在重复 retrieve 之间发生了状态变化')
  }
  console.info()

  // ---------------------------------------------------- 输出
  const row = (a: Arm) => {
    const r = KS.map(k => avg(acc[a.key].recall[k]).toFixed(4).padStart(9)).join('')
    const mrr = avg(acc[a.key].rr).toFixed(4).padStart(9)
    const n = KS.map(k => avg(acc[a.key].ndcgW[k]).toFixed(4).padStart(9)).join('')
    return `  ${a.key.padEnd(20)}${r}${mrr}${n}`
  }
  console.info(`  ${'arm'.padEnd(20)}${KS.map(k => `R@${k}`.padStart(9)).join('')}${'MRR'.padStart(9)}${KS.map(k => `N@${k}`.padStart(9)).join('')}`)
  for (const a of ARMS)
    console.info(row(a))
  console.info()
  console.info('  同上，但 NDCG 用**全池**口径的 IDCG（端到端真实上界）：')
  console.info(`  ${'arm'.padEnd(20)}${KS.map(k => `N@${k}`.padStart(9)).join('')}`)
  for (const a of ARMS)
    console.info(`  ${a.key.padEnd(20)}${KS.map(k => avg(acc[a.key].ndcgF[k]).toFixed(4).padStart(9)).join('')}`)
  console.info()
  console.info('  「用本臂**自己的分数**过 floor=0.02」的 recall@K —— 分数量级效应：')
  console.info(`  ${'arm'.padEnd(20)}${KS.map(k => `R@${k}`.padStart(9)).join('')}`)
  for (const a of ARMS)
    console.info(`  ${a.key.padEnd(20)}${KS.map(k => avg(acc[a.key].recallOwn[k]).toFixed(4).padStart(9)).join('')}`)
  console.info()

  // ---------------------------------------------------- 判读
  const R = (k: string) => avg(acc[k].recall[8])
  const rrf = R('e2e-rrf-default')
  const sim = R('e2e-std-sim-only')
  const std = R('e2e-std-default')
  const cor = R('e2e-std-corrected')
  const rrfCor = R('e2e-rrf-corrected')
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`
  console.info('--- 判读 ---')
  console.info(`  离线重排 rrf（既有报告）  = 0.2422`)
  console.info(`  端到端 rrf                = ${rrf.toFixed(4)}   Δ ${fmt(rrf - 0.2422)}`)
  console.info(`  端到端 std-sim-only       = ${sim.toFixed(4)}   rrf − sim-only = ${fmt(rrf - sim)}`)
  console.info(`  端到端 std-default        = ${std.toFixed(4)} · std-corrected = ${cor.toFixed(4)} · rrf-corrected = ${rrfCor.toFixed(4)}`)
  console.info(`  平均池大小 = ${avg(poolSizes).toFixed(1)}（离线消融只在其中前 ${WINDOW} 条内排名）`)

  const stamp = new Date().toISOString().slice(0, 10)
  const outPath = join(dirname(new URL(import.meta.url).pathname), 'results', `j5-rrf-e2e-independent-${stamp}.json`)
  mkdirSync(dirname(outPath), { recursive: true })
  writeFileSync(outPath, `${JSON.stringify(withProvenance({
    generatedAt: new Date().toISOString(),
    experiment: 'j5-rrf-e2e-independent',
    corpus: { path, sha256: sha, conversations: convs.length },
    window: WINDOW,
    floor: FLOOR,
    floorCriterion: 'shared: store standardized+DEFAULT score over the whole pool',
    condition: 'NO_GATING',
    ks: KS,
    questions,
    poolSizeMean: avg(poolSizes),
    arms: ARMS.map(a => ({
      arm: a.key,
      note: a.note,
      scoreMode: a.mode,
      weights: a.weights,
      recall: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].recall[k])])),
      recallOwnScoreFloor: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].recallOwn[k])])),
      ndcgWindowIdcg: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].ndcgW[k])])),
      ndcgFullPoolIdcg: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].ndcgF[k])])),
      mrr: avg(acc[a.key].rr),
    })),
  }), null, 2)}\n`, 'utf8')
  console.info(`artifact: ${outPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
