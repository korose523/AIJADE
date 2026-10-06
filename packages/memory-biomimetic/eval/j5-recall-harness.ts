import type { BioticMemory, RetrievalWeights } from '../src/index'

/**
 * J5 / P4 —— 跨语料复现的**共享测量装置**。
 *
 * ── 为什么必须抽出来 ──────────────────────────────────────────────────────
 * 与 `eval-metrics.ts` 存在的同一个理由，只是更紧迫：现在有**两个语料**
 * （LoCoMo、LongMemEval）要产出互相比较的数字。若两侧各写一份 recall@K，
 * 必然在某次修改后悄悄分叉，而分叉后的数字还会被摆进同一张跨语料对照表 ——
 * 那正是 J5 自己点名的"看起来是结论、其实与代码无关"。
 *
 * 本模块因此是两侧唯一的指标实现入口。两个 runner 只负责建记忆与喂题。
 *
 * ── 两套口径，都必须产出（这是本轮的核心修正）──────────────────────────────
 * 历史产物里 LoCoMo 的三臂权重消融**只有 parts 离线重排轨**
 * （`p2-weight-ablation-*`，`rerankPool:150`），没有 store 端到端轨。
 * 而跨语料对照若拿两个不同口径的绝对值并列，就是在一篇**主题为"口径缺陷"**
 * 的论文里再制造一处口径缺陷。故本装置一次运行同时产出两套：
 *
 *   ① `e2e`   —— 真 `mem.retrieve()`（含检索噪声、冲突惩罚、全候选池）
 *   ② `parts` —— 离线重排：取现行打分前 150 条，用 `c.parts` 按各臂权重重排；
 *                floor 判定沿用**该候选在现行打分下的 store 分数**
 *                （与 `diag-weight-ablation.ts:157` 逐行一致，各臂准入条件才相同）
 *
 * 采信规则：与 LoCoMo 权威值 0.0906/0.3580/0.3046 比较时用 **①parts**；
 * 两语料之间互相比较时用 **①e2e 对 ①e2e / ②parts 对 ②parts**，绝不交叉。
 *
 * ── floor 双版 ────────────────────────────────────────────────────────────
 * 命中判定 `score > retrievalFloor`（默认 0.02）在跨**打分模式**比较时是个
 * 陷阱：RRF 的分数域只有约 0.010–0.038，与 standardized 不是同一量纲，
 * 同一个绝对阈值对两臂的杀伤率不同。故每臂同时算两版：
 *   `floor0`   —— 纯排序能力（`score > 0` 之外的排名命中）← **采信值**
 *   `floorCfg` —— 现口径 `score > config.retrievalFloor` ← 对照
 * 两者之差即"floor 伪影"。
 *
 * ── 一等字段 ──────────────────────────────────────────────────────────────
 *   poolSize           可检索候选数（端到端真正会考虑的条数）
 *   effectiveTruncation = min(150, poolSize) / poolSize
 *
 * 后者必须报：LongMemEval 每题池 38–62 ⇒ 150 截断是**空操作**；LoCoMo 池 ≈1176
 * ⇒ 截断是**实的**。即使 parts 口径对齐了，两语料的"被裁比例"仍差一个量级，
 * 这是两语料绝对值不可并列的**第三条**理由（前两条：粒度、e2e/parts 口径）。
 */
import {
  CORRECTED_RETRIEVAL_WEIGHTS,
  DEFAULT_RETRIEVAL_WEIGHTS,
} from '../src/index'

export const KS = [1, 2, 4, 8] as const
export const MAX_K = 8

/** 与 `diag-weight-ablation.ts:50` 同值 —— 跨语料对齐 parts 轨的前提。 */
export const RERANK_POOL = 150

/** 仅保留 similarity 项。 */
export const SIM_ONLY_WEIGHTS: RetrievalWeights = {
  similarity: 1,
  strength: 0,
  recency: 0,
  context: 0,
  affect: 0,
}

export type ArmName = 'current' | 'sim-only' | 'no-recency' | 'rrf'

export interface ArmSpec {
  name: ArmName
  description: string
  weights: RetrievalWeights
  /**
   * 端到端模式下要切到的打分模式。`undefined` = 沿用 store 默认（standardized）。
   * `'rrf'` 臂靠它，因为 `retrieve()` 没有 per-call 的 mode 入参。
   */
  scoreMode?: 'standardized' | 'rrf'
}

export const E2E_ARMS: ArmSpec[] = [
  { name: 'current', description: 'DEFAULT_RETRIEVAL_WEIGHTS（现状）', weights: DEFAULT_RETRIEVAL_WEIGHTS },
  { name: 'sim-only', description: '仅 similarity（相关性上界参照）', weights: SIM_ONLY_WEIGHTS },
  { name: 'no-recency', description: 'CORRECTED_RETRIEVAL_WEIGHTS（recency=0）', weights: CORRECTED_RETRIEVAL_WEIGHTS },
  { name: 'rrf', description: 'retrievalScoreMode=\'rrf\'（名次融合修复基线）', weights: DEFAULT_RETRIEVAL_WEIGHTS, scoreMode: 'rrf' },
]

/** parts 离线重排轨：与 LoCoMo 权威消融**同法**，故不含 rrf（rrf 无 parts 线性组合语义）。 */
export const PARTS_ARMS: ArmSpec[] = E2E_ARMS.filter(a => a.name !== 'rrf')

export interface Question {
  id: string
  text: string
  /** 金标准候选 id 集合（已含 `fact_` 变体）。 */
  gold: Set<string>
  /** 池中未被遗忘的金标准条数 —— NDCG 的 IDCG 分母。 */
  relevantTotal: number
}

export interface ArmHit {
  /** floor=0 口径（纯排名）：每个 K 是否命中。 */
  recallFloor0: Record<number, number>
  /** floor=config.retrievalFloor 口径（现口径）：每个 K 是否命中。 */
  recallFloorCfg: Record<number, number>
  mrr: number
  ndcg: Record<number, number>
  firstHitRank: number
}

export interface MeasureResult {
  arms: Record<string, ArmHit>
  poolSize: number
  effectiveTruncation: number
}

function idcg(r: number, k: number): number {
  let s = 0
  for (let i = 1; i <= Math.min(r, k); i++)
    s += 1 / Math.log2(i + 1)
  return s
}

/**
 * 由一个**已排好序**的候选列表算单臂指标。
 * `floorScore(i)` 返回该位次用于过 floor 判据的分数 —— e2e 轨是本臂自身分数，
 * parts 轨是候选在**现行打分**下的 store 分数（各臂共用，见文件头）。
 */
function scoreRanking(
  ranking: { id: string, floorScore: number }[],
  q: Question,
  floor: number,
): ArmHit {
  const hitRanks: number[] = []
  const hitRanksFloor0: number[] = []
  ranking.forEach((c, i) => {
    if (!q.gold.has(c.id))
      return
    hitRanksFloor0.push(i + 1)
    if (c.floorScore > floor)
      hitRanks.push(i + 1)
  })

  const firstHitRank = hitRanks.length ? hitRanks[0] : 0
  const recallFloorCfg: Record<number, number> = {}
  const recallFloor0: Record<number, number> = {}
  const ndcg: Record<number, number> = {}
  for (const k of KS) {
    recallFloorCfg[k] = firstHitRank > 0 && firstHitRank <= k ? 1 : 0
    recallFloor0[k] = hitRanksFloor0.some(r => r <= k) ? 1 : 0
    let dcg = 0
    for (const r of hitRanks) {
      if (r <= k)
        dcg += 1 / Math.log2(r + 1)
    }
    const ideal = idcg(q.relevantTotal, k)
    ndcg[k] = ideal > 0 ? dcg / ideal : 0
  }
  return {
    recallFloor0,
    recallFloorCfg,
    mrr: firstHitRank > 0 ? 1 / firstHitRank : 0,
    ndcg,
    firstHitRank,
  }
}

/** 可检索池大小，口径同 `eval-metrics.ts::measure`。 */
export function poolSizeOf(mem: BioticMemory): number {
  return mem.episodes.filter(e => !e.forgotten).length
    + mem.facts.length + mem.procedural.length + mem.working.length
}

/**
 * 对**一个已建好的记忆**与**一组题**测量全部臂。
 *
 * 打分页宽与 K 无关（`store.ts` 的 `CONFLICT_RERANK_POOL` 是常数），故
 * `retrieve(q, MAX_K)` 的前缀即各 K 的 top-K，无需逐 K 重调。
 */
export function measureArms(mem: BioticMemory, questions: Question[]): MeasureResult[] {
  const floor = mem.config.retrievalFloor
  const poolSize = poolSizeOf(mem)
  const effectiveTruncation = Math.min(RERANK_POOL, poolSize) / poolSize
  const originalMode = mem.config.retrievalScoreMode

  const out: MeasureResult[] = []

  for (const q of questions) {
    // ── ① e2e 轨 ────────────────────────────────────────────────────────
    const e2e: Record<string, ArmHit> = {}
    for (const arm of E2E_ARMS) {
      if (arm.scoreMode)
        mem.config.retrievalScoreMode = arm.scoreMode
      else if (originalMode)
        mem.config.retrievalScoreMode = originalMode
      const ranking = mem.retrieve(q.text, MAX_K, false, arm.weights).map(c => ({
        id: c.id,
        floorScore: c.score,
      }))
      e2e[arm.name] = scoreRanking(ranking, q, floor)
    }
    mem.config.retrievalScoreMode = originalMode

    // ── ② parts 轨：与 diag-weight-ablation.ts:120-158 逐行同法 ──────────
    const cands = mem.retrieve(q.text, RERANK_POOL, false).map(c => ({
      id: c.id,
      score: c.score,
      similarity: c.parts.similarity,
      strength: c.parts.strength,
      recency: c.parts.recency,
      context: c.parts.context,
    }))
    const parts: Record<string, ArmHit> = {}
    for (const arm of PARTS_ARMS) {
      const ranked = cands
        .map(c => ({
          id: c.id,
          floorScore: c.score, // ← 沿用 store 分数，使各臂准入条件一致
          v: arm.weights.similarity * c.similarity
            + arm.weights.strength * c.strength
            + arm.weights.recency * c.recency
            + arm.weights.context * c.context,
        }))
        .sort((a, b) => b.v - a.v)
      parts[arm.name] = scoreRanking(ranked, q, floor)
    }

    out.push({
      arms: {
        ...Object.fromEntries(Object.entries(e2e).map(([k, v]) => [`e2e:${k}`, v])),
        ...Object.fromEntries(Object.entries(parts).map(([k, v]) => [`parts:${k}`, v])),
      },
      poolSize,
      effectiveTruncation,
    })
  }

  return out
}

export const ARM_KEYS = [
  ...E2E_ARMS.map(a => `e2e:${a.name}`),
  ...PARTS_ARMS.map(a => `parts:${a.name}`),
]

/** 对一臂在多题上的结果求均值。 */
export function aggregate(
  rows: MeasureResult[],
  key: string,
): {
  recallFloor0: Record<number, number>
  recallFloorCfg: Record<number, number>
  mrr: number
  ndcg: Record<number, number>
} {
  const n = rows.length
  const mean = (f: (r: MeasureResult) => number): number => (n ? rows.reduce((s, r) => s + f(r), 0) / n : 0)
  const recallFloor0: Record<number, number> = {}
  const recallFloorCfg: Record<number, number> = {}
  const ndcg: Record<number, number> = {}
  for (const k of KS) {
    recallFloor0[k] = mean(r => r.arms[key].recallFloor0[k])
    recallFloorCfg[k] = mean(r => r.arms[key].recallFloorCfg[k])
    ndcg[k] = mean(r => r.arms[key].ndcg[k])
  }
  return { recallFloor0, recallFloorCfg, mrr: mean(r => r.arms[key].mrr), ndcg }
}

/** 池规模分层边界（team-lead 指定）。 */
export const POOL_STRATA: { label: string, lo: number, hi: number }[] = [
  { label: '[0,50)', lo: 0, hi: 50 },
  { label: '[50,100)', lo: 50, hi: 100 },
  { label: '[100,200)', lo: 100, hi: 200 },
  { label: '[200,400)', lo: 200, hi: 400 },
  { label: '[400,+∞)', lo: 400, hi: Number.POSITIVE_INFINITY },
]
