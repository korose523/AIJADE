import type { GatingCoefficients, RetrievalScoreMode, RetrievalWeights } from '../src/index'

import process from 'node:process'

/**
 * J5/P4 四臂消融：RRF 是否修得好「量纲错配」？
 *
 * ── 背景 ────────────────────────────────────────────────────────────────
 * J5/P4 的核心发现是检索打分的**量纲错配**：`recency` 的原始量级远大于稀疏
 * TF-IDF 余弦 `similarity`，于是任何**线性加权和**都把排序交给了量级最大的那一
 * 项。`eval/diag-weight-ablation.ts` 已用权重消融证实了这一点（current 0.0906 vs
 * sim-only 0.3580）。
 *
 * 已有的两条修复基线是：① z-score 标准化（现行默认）；② 层次化检索。
 * 本脚本加第三条：**RRF（Reciprocal Rank Fusion）**。RRF 按**名次**而非量级融合，
 * 因此量纲错配在构造上就不可能发生 —— 一个分量无法通过"数值更大"来压过另一个。
 *
 * ── 设计：同一批候选，只换组合规则 ─────────────────────────────────────
 * 四臂跑在**完全相同**的候选集上（每题一次 `retrieve(q, RERANK_POOL)` 取回的
 * 前 150 条），只改「分量怎么合成一个分数」。这样排除了"换了检索器"这类混杂。
 *
 * 准入判据（`score > retrievalFloor`）在四臂间**共用同一个**——沿用候选在现行
 * 默认打分下由 store 给出的 `score`，而不是各臂自己算的分。理由：RRF 的分数量级
 * 天然很小（≈0.03），若各臂用自己的分数去过 floor=0.02 的门槛，比较的就不再是
 * "排序能力"而是"分数量级"，RRF 会被纯粹的数值尺度惩罚。这也是
 * `diag-weight-ablation.ts` 的既有口径。
 *
 * ── 四臂 ────────────────────────────────────────────────────────────────
 *   current     additive：DEFAULT_RETRIEVAL_WEIGHTS 的加权和（复刻既有消融口径）
 *   sim-only    只用 similarity
 *   no-recency  CORRECTED_RETRIEVAL_WEIGHTS（recency 置 0）
 *   rrf         RRF（k=60）+ DEFAULT_RETRIEVAL_WEIGHTS
 *
 * 另加三行**参考臂**（不是四臂之一，仅作定位）：
 *   current-standardized / no-recency-standardized  —— 同样的权重走 z-score 规则
 *   store-default                                   —— store 自己的默认排序，不重排
 *
 * ── 口径限制（与既有消融同一条）────────────────────────────────────────
 * 重排只在**现行打分的前 150 条**内进行，不是全池（冲突惩罚是 O(topK²)，全池
 * ≈1176 会跑爆）。故所有数字都只能当**下界**读；结论只依赖各臂之间的**相对**差。
 *
 * ── 指标 ────────────────────────────────────────────────────────────────
 * · recall@K  ：top-K 中存在金标准证据（且过 floor）的题目比例。
 * · MRR       ：第一个金标准证据名次的倒数，在**整个 150 条重排序列**上找，未命中记 0。
 * · NDCG@K    ：二元相关性。DCG@K = Σ rel_i / log2(i+1)；
 *               IDCG@K = 前 min(K, 池中金标准条数) 个位置的理想 DCG；
 *               池中无金标准（IDCG=0）时记 0。
 *               相关性 rel_i 同样要求过 floor，与 recall 口径一致。
 *
 * 用法：tsx eval/j5-rrf-ablation.ts [path-to-locomo.json] [conv-limit]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { buildMemory, CORRECTED_RETRIEVAL_WEIGHTS, DEFAULT_RETRIEVAL_WEIGHTS, loadLocomo, NO_GATING, scoreCandidatesRRF, scoreCandidatesStandardized } from '../src/index'
import { withProvenance } from './artifact-provenance'
import { avg, KS } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

/** 与 `diag-weight-ablation.ts` 同值，保证候选集一致、数字可比。 */
const RERANK_POOL = 150
const MAXK = Math.max(...KS)

/** 既有消融的权威基线（K=8 recall），用于校验本脚本的台架是否装对了。 */
const BASELINE_RECALL8: Record<string, number> = {
  'current': 0.0906,
  'sim-only': 0.3580,
  'no-recency': 0.3046,
}

type Combine = 'additive-parts' | 'standardized' | 'rrf' | 'store-order'

interface Arm {
  key: string
  note: string
  combine: Combine
  weights: RetrievalWeights
  /** 写入产物 provenance 的打分模式 —— 必须反映本臂实际跑的口径。 */
  scoreMode: RetrievalScoreMode
  /** 四臂之一 vs 参考臂。 */
  primary: boolean
}

const ZERO_W: RetrievalWeights = { similarity: 0, strength: 0, recency: 0, context: 0, affect: 0 }

const ARMS: Arm[] = [
  {
    key: 'current',
    note: 'DEFAULT 权重的加权和（复刻 diag-weight-ablation 口径）',
    combine: 'additive-parts',
    weights: DEFAULT_RETRIEVAL_WEIGHTS,
    scoreMode: 'additive',
    primary: true,
  },
  {
    key: 'sim-only',
    note: '只用 similarity',
    combine: 'additive-parts',
    weights: { ...ZERO_W, similarity: 1 },
    scoreMode: 'additive',
    primary: true,
  },
  {
    key: 'no-recency',
    note: 'CORRECTED_RETRIEVAL_WEIGHTS（recency 置 0）',
    combine: 'additive-parts',
    weights: CORRECTED_RETRIEVAL_WEIGHTS,
    scoreMode: 'additive',
    primary: true,
  },
  {
    key: 'rrf',
    note: 'RRF（k=60）+ DEFAULT 权重',
    combine: 'rrf',
    weights: DEFAULT_RETRIEVAL_WEIGHTS,
    scoreMode: 'rrf',
    primary: true,
  },
  {
    key: 'current-standardized',
    note: '【参考】DEFAULT 权重 + z-score 规则',
    combine: 'standardized',
    weights: DEFAULT_RETRIEVAL_WEIGHTS,
    scoreMode: 'standardized',
    primary: false,
  },
  {
    key: 'no-recency-standardized',
    note: '【参考】CORRECTED 权重 + z-score 规则',
    combine: 'standardized',
    weights: CORRECTED_RETRIEVAL_WEIGHTS,
    scoreMode: 'standardized',
    primary: false,
  },
  {
    key: 'rrf-no-recency',
    note: '【参考】RRF（k=60）+ CORRECTED 权重（recency 置 0）',
    combine: 'rrf',
    weights: CORRECTED_RETRIEVAL_WEIGHTS,
    scoreMode: 'rrf',
    primary: false,
  },
  {
    key: 'store-default',
    note: '【参考】store 默认（standardized）排序原样，不重排',
    combine: 'store-order',
    weights: DEFAULT_RETRIEVAL_WEIGHTS,
    scoreMode: 'standardized',
    primary: false,
  },
  // ── 溯源补跑臂（2026-10-03）────────────────────────────────────────────
  // 这 5 个权重组合的 recall@8 原本只存在于 `p2-weight-ablation-2026-09-19.json`，
  // 那份产物早于溯源机制（`30ffde2`），无 `provenance` 块 —— 数字无法归属到任何
  // commit。它们在 `diag-weight-ablation.ts` 的 `WCONFIGS` 里已有权威定义，此处
  // **逐字复刻**其权重，以补出带溯源的等价数字。口径与上方四臂完全一致：
  // 同一 `RERANK_POOL` 候选集、同一共用 `storeScore` floor 判据。
  // `str-only` / `rec-only` 支撑"单独 strength 或 recency 不携带相关性信息"这一
  // 结论性主张，因此必须有一份可溯源的数字来背书。
  {
    key: 'sim+ctx',
    note: '相似度 + 上下文（复刻 diag-weight-ablation 的 sim+ctx）',
    combine: 'additive-parts',
    weights: { ...ZERO_W, similarity: 1, context: 0.4 },
    scoreMode: 'additive',
    primary: true,
  },
  {
    key: 'sim+str',
    note: '相似度 + 强度（去新近项；复刻 diag-weight-ablation 的 sim+str）',
    combine: 'additive-parts',
    weights: { ...ZERO_W, similarity: 1, strength: 0.6 },
    scoreMode: 'additive',
    primary: true,
  },
  {
    key: 'sim-heavy',
    note: '相似度 ×3（复刻 diag-weight-ablation 的 sim-heavy）',
    combine: 'additive-parts',
    weights: { ...ZERO_W, similarity: 3, strength: 0.6, recency: 0.3, context: 0.4 },
    scoreMode: 'additive',
    primary: true,
  },
  {
    key: 'str-only',
    note: '只用强度（极端对照；复刻 diag-weight-ablation 的 str-only）',
    combine: 'additive-parts',
    weights: { ...ZERO_W, strength: 1 },
    scoreMode: 'additive',
    primary: true,
  },
  {
    key: 'rec-only',
    note: '只用新近（极端对照，受池截断影响最大；复刻 diag-weight-ablation 的 rec-only）',
    combine: 'additive-parts',
    weights: { ...ZERO_W, recency: 1 },
    scoreMode: 'additive',
    primary: true,
  },
]

interface PoolItem {
  id: string
  /** store 在**默认**打分下给出的分数 —— 四臂共用的 floor 判据。 */
  storeScore: number
  similarity: number
  strength: number
  recency: number
  context: number
}

interface Question {
  pool: PoolItem[]
  /** 金标准证据 id（含 fact_ 前缀形式）。 */
  gold: Set<string>
  /** 池中过 floor 的金标准条数，用于 IDCG。 */
  goldInPool: number
}

/**
 * 反解饱和强度：store 暴露的 `parts.strength` 是 `r/(1+r)`，RRF / z-score 都期望
 * 原始值 `r`。严格反函数 `r = s/(1-s)`。
 *
 * （对 RRF 而言其实无所谓——`x → x/(1+x)` 单调递增，饱和前后名次相同——但按原始
 * 值喂进去，`rawParts` 才不会二次饱和，产物里的解释字段才是真的。）
 */
function unsaturated(s: number): number {
  if (!(s > 0))
    return 0
  if (s >= 1)
    return 1e9
  return s / (1 - s)
}

/** 按臂的组合规则给池中每项打分，返回与 `pool` 等长的分数数组。 */
function armScores(arm: Arm, q: Question): number[] {
  const pool = q.pool
  if (arm.combine === 'store-order') {
    // store 返回的已是降序，用下标当分数即可（越大越靠前）。
    return pool.map((_, i) => pool.length - i)
  }
  if (arm.combine === 'additive-parts') {
    const w = arm.weights
    return pool.map(c =>
      w.similarity * c.similarity
      + w.strength * c.strength
      + w.recency * c.recency
      + w.context * c.context)
  }
  const rows = pool.map(c => ({
    similarity: c.similarity,
    strengthRaw: unsaturated(c.strength),
    recency: c.recency,
    context: c.context,
    // affect 是 presentation-only，三个模式都给它 0 权重。
    affect: 0,
  }))
  const out = arm.combine === 'rrf'
    ? scoreCandidatesRRF(rows, arm.weights)
    : scoreCandidatesStandardized(rows, arm.weights)
  return out.map(s => s.score)
}

/** 按分数降序排出的下标；同分用原始下标稳定打破，保证可复现。 */
function order(scores: number[]): number[] {
  return scores
    .map((s, i) => ({ s, i }))
    .sort((a, b) => b.s - a.s || a.i - b.i)
    .map(x => x.i)
}

/** 逐题指标。 */
function measure(ord: number[], q: Question, floor: number) {
  const hit: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  const ndcg: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  let rr = 0

  for (let pos = 0; pos < ord.length; pos++) {
    const c = q.pool[ord[pos]]
    if (!q.gold.has(c.id) || !(c.storeScore > floor))
      continue
    if (rr === 0)
      rr = 1 / (pos + 1)
  }

  for (const k of KS) {
    let dcg = 0
    for (let pos = 0; pos < k && pos < ord.length; pos++) {
      const c = q.pool[ord[pos]]
      if (q.gold.has(c.id) && c.storeScore > floor)
        dcg += 1 / Math.log2(pos + 2)
    }
    let idcg = 0
    const ideal = Math.min(k, q.goldInPool)
    for (let pos = 0; pos < ideal; pos++)
      idcg += 1 / Math.log2(pos + 2)
    ndcg[k] = idcg > 0 ? dcg / idcg : 0
    // recall@K 与既有消融逐位同定义：top-K 里有金标准且过 floor。
    if (dcg > 0)
      hit[k] = 1
  }
  return { hit, ndcg, rr }
}

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== J5/P4 四臂消融：RRF vs z-score vs 现行加权和 ===')
  console.info(`corpus   : ${path}`)
  console.info(`sha256   : ${sha256File(path)}`)
  console.info(`convs    : ${convs.length}`)
  console.info(`condition: NO_GATING（不剪枝、不重加权，隔离纯检索器行为）`)
  console.info(`pool     : 每题取现行打分前 ${RERANK_POOL} 条，四臂共用；floor 判据共用 store 分数`)
  console.info()

  const acc: Record<string, {
    recall: Record<number, number[]>
    ndcg: Record<number, number[]>
    rr: number[]
  }> = {}
  for (const a of ARMS) {
    acc[a.key] = {
      recall: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      ndcg: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      rr: [],
    }
  }
  let questions = 0

  for (const conv of convs) {
    const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)
    const floor = mem.config.retrievalFloor

    const qs: Question[] = []
    for (const q of conv.qa) {
      const gold = new Set<string>()
      for (const e of q.evidence ?? []) {
        if (!conv.evidenceIds.has(e))
          continue
        gold.add(e)
        gold.add(`fact_${e}`)
      }
      const pool = mem.retrieve(q.question, RERANK_POOL, false).map(c => ({
        id: c.id,
        storeScore: c.score,
        similarity: c.parts.similarity,
        strength: c.parts.strength,
        recency: c.parts.recency,
        context: c.parts.context,
      }))
      let goldInPool = 0
      for (const c of pool) {
        if (gold.has(c.id) && c.storeScore > floor)
          goldInPool++
      }
      qs.push({ pool, gold, goldInPool })
    }

    for (const a of ARMS) {
      for (const q of qs) {
        const m = measure(order(armScores(a, q)), q, floor)
        for (const k of KS) {
          acc[a.key].recall[k].push(m.hit[k])
          acc[a.key].ndcg[k].push(m.ndcg[k])
        }
        acc[a.key].rr.push(m.rr)
      }
    }
    questions += qs.length
  }

  // ---------------------------------------------------------------- 输出
  const row = (a: Arm) => {
    const r = KS.map(k => avg(acc[a.key].recall[k]).toFixed(4).padStart(9)).join('')
    const n = KS.map(k => avg(acc[a.key].ndcg[k]).toFixed(4).padStart(9)).join('')
    const mrr = avg(acc[a.key].rr).toFixed(4).padStart(9)
    return `  ${a.key.padEnd(24)}${r}${mrr}${n}`
  }
  console.info(`  ${'arm'.padEnd(24)}${KS.map(k => `R@${k}`.padStart(9)).join('')}${'MRR'.padStart(9)}${KS.map(k => `N@${k}`.padStart(9)).join('')}`)
  for (const a of ARMS) {
    if (!a.primary)
      continue
    console.info(row(a))
  }
  console.info(`  ${'— 参考臂 —'.padEnd(24)}`)
  for (const a of ARMS) {
    if (a.primary)
      continue
    console.info(row(a))
  }
  console.info()

  // ---------------------------------------------------------------- 台架自检
  console.info('--- 台架自检：本脚本的 current/sim-only/no-recency 须复现既有消融 ---')
  let harnessOk = true
  for (const [key, expected] of Object.entries(BASELINE_RECALL8)) {
    const got = avg(acc[key].recall[MAXK])
    const delta = got - expected
    const ok = Math.abs(delta) <= 0.005
    if (!ok)
      harnessOk = false
    console.info(`  ${key.padEnd(14)} 实测 ${got.toFixed(4)}  基线 ${expected.toFixed(4)}  Δ ${delta >= 0 ? '+' : ''}${delta.toFixed(4)}  ${ok ? '✅' : '❌ 台架可能有误'}`)
  }
  console.info()

  // ---------------------------------------------------------------- 判读
  const R = (key: string) => avg(acc[key].recall[MAXK])
  const MRR = (key: string) => avg(acc[key].rr)
  const curR = R('current')
  const simR = R('sim-only')
  const noRecR = R('no-recency')
  const rrfR = R('rrf')
  const best = Math.max(simR, noRecR, rrfR)
  const bestName = rrfR === best ? 'rrf' : simR >= noRecR ? 'sim-only' : 'no-recency'
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`

  const verdicts: string[] = []
  verdicts.push(`【① 台架】${harnessOk ? '✅ 三条既有基线全部复现，本脚本的候选集与判据与 diag-weight-ablation 一致。' : '❌ 既有基线未复现，下方数字不可信。'}`)
  verdicts.push(`【② 四臂 recall@${MAXK}】current ${curR.toFixed(4)} · sim-only ${simR.toFixed(4)} · no-recency ${noRecR.toFixed(4)} · rrf ${rrfR.toFixed(4)}`)
  verdicts.push(`    rrf vs sim-only ${fmt(rrfR - simR)}   rrf vs current ${fmt(rrfR - curR)}`)
  verdicts.push(`【③ 结论】`)
  if (!harnessOk) {
    verdicts.push('  ⇒ 台架自检未通过，不下结论。')
  }
  else if (rrfR > simR + 0.005) {
    verdicts.push(`  ⇒ RRF ${rrfR.toFixed(4)} **优于** sim-only ${simR.toFixed(4)}（${fmt(rrfR - simR)}）。`)
    verdicts.push('     名次融合确实比"只用相似度"更能修好量纲错配。')
  }
  else {
    verdicts.push(`  ⇒ RRF ${rrfR.toFixed(4)} **未能超过** sim-only ${simR.toFixed(4)}（${fmt(rrfR - simR)}）。`)
    verdicts.push('     这是一个**负面结果**，如实记录：名次融合并没有提供超出"干脆只用相似度"的收益。')
    verdicts.push('     可写入论文 limitations —— "我们试过 RRF，它没能胜过 z-score 修正 / 纯相似度"。')
  }
  verdicts.push(`  ⇒ 四臂最佳：${bestName} ${best.toFixed(4)}（MRR ${MRR(bestName).toFixed(4)}）。`)
  verdicts.push('')
  verdicts.push(`⚠️ 口径限制：重排仅在现行打分的前 ${String(RERANK_POOL)} 条内进行，所有数字只当下界读；`)
  verdicts.push('   floor 判据四臂共用 store 在默认（standardized）打分下的分数，故比较的是排序能力而非分数量级。')

  console.info('--- 判读（由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts) console.info(v)

  // ---------------------------------------------------------------- 产物
  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })

  const payloadFor = (a: Arm) => ({
    arm: a.key,
    note: a.note,
    primary: a.primary,
    combine: a.combine,
    questions,
    recall: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].recall[k])])),
    ndcg: Object.fromEntries(KS.map(k => [k, avg(acc[a.key].ndcg[k])])),
    mrr: avg(acc[a.key].rr),
  })

  const written: string[] = []
  // 每臂一个产物：provenance 的 scoreMode / weights 必须反映**该臂**的口径。
  for (const a of ARMS) {
    if (!a.primary)
      continue
    const p = join(outDir, `j5-rrf-ablation-${a.key}-${stamp}.json`)
    writeFileSync(p, `${JSON.stringify(withProvenance({
      generatedAt: new Date().toISOString(),
      experiment: 'j5-rrf-ablation',
      corpus: { path, sha256: sha256File(path), conversations: convs.length },
      rerankPool: RERANK_POOL,
      condition: 'NO_GATING',
      ks: KS,
      ...payloadFor(a),
    }, { scoreMode: a.scoreMode, weights: a.weights }), null, 2)}\n`, 'utf8')
    written.push(p)
  }

  // 汇总产物：provenance 记 store 实际运行的模式（standardized + 默认权重），
  // 每臂自带自己的 scoreMode / weights，避免"一个数字不知道属于哪次口径"。
  const summaryPath = join(outDir, `j5-rrf-ablation-${stamp}.json`)
  writeFileSync(summaryPath, `${JSON.stringify(withProvenance({
    generatedAt: new Date().toISOString(),
    experiment: 'j5-rrf-ablation',
    corpus: { path, sha256: sha256File(path), conversations: convs.length },
    rerankPool: RERANK_POOL,
    condition: 'NO_GATING',
    ks: KS,
    questions,
    arms: ARMS.map(a => ({
      ...payloadFor(a),
      scoreMode: a.scoreMode,
      weights: a.weights,
    })),
    harnessSanity: Object.fromEntries(Object.entries(BASELINE_RECALL8).map(([k, v]) => [k, { expected: v, measured: avg(acc[k].recall[MAXK]) }])),
    verdicts,
  }), null, 2)}\n`, 'utf8')
  written.push(summaryPath)

  console.info()
  for (const p of written) console.info(`artifact: ${p}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
