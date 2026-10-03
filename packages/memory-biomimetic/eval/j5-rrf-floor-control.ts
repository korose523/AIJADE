/**
 * J5/P4 —— RRF 端到端**floor 对照**（三档判据 × 四臂）。
 *
 * ── 要判定的那个污染 ──────────────────────────────────────────────────────
 * `j5-rrf-e2e-decomposition.ts` 报出的 `rrf-e2e` = 0.0745 远低于基线
 * `store-default` = 0.2064。但那个 0.0745 **不是排序能力的差距**，而是判据被
 * 污染了：脚本对**每个臂用自己的分数**过同一个阈值
 * `c.score > mem.config.retrievalFloor`（默认 0.02），而三种打分模式的分数量级
 * 根本不可比：
 *
 *   · `standardized` 是 z 分加权和，量级 ~N(0, 1)；
 *   · `additive` 是饱和分量加权和，上界 = 权重和；
 *   · `rrf` 是 Σ w_c/(60 + rank_c)，**上界 = Σw / 61**。参与 RRF 的四个分量
 *     {sim:1, str:0.6, rec:0.3, ctx:0.4}（`affect` 不是 RRF 分量，恒为 0）
 *     之和 = 2.30 ⇒ 理论上限 0.03770；若只有 similarity 命中而其余 rank≈500，
 *     则约1/(60+1) + 1.3/560 ≈ 0.0187——
 *     **默认 floor = 0.02 落在 RRF 的分数域内部**。
 *
 * 于是 floor 会把大量**排位很高**的 RRF 候选判成"未命中"。反证已在
 * `results/j5-rrf-e2e-independent-2026-10-02.json` 里：改用**共享 floor 判据**
 * （store standardized 打分的全池分数）后 `e2e-rrf-default` 的 recall@8 是 0.1536
 * 而非 0.0745，而 standardized 各臂在两种判据下逐位相同 —— 污染只打在 RRF 上。
 *
 * ── 本脚本做什么 ──────────────────────────────────────────────────────────
 * 同一语料、同一题目、同一去重配置（每对话只 build 一次），跑四个臂，**每臂同时
 * 报三档判据**的 recall@1/2/4/8，让污染量可以直接读出来：
 *
 *   (A) rank-only            —— `rel = 金标准 ∈ top-K`，**完全不看分数**。
 *                               这是**采用口径**：跨打分模式比较时 floor 本就不是
 *                               可比判据，必须关掉。
 *   (B) shared-standardized  —— `rel = 金标准 且 store-standardized 全池分数 > 0.02`。
 *                               **对照口径**，判据构造复用
 *                               `j5-rrf-e2e-independent.ts` 的 `floorScore`，
 *                               不另造。
 *   (C) own-score            —— `rel = 金标准 且 本臂自己的分数 > 0.02`。
 *                               复现现有污染条件，仅供对照，**不作结论依据**。
 *
 * 另记每臂**自己分数**在检索窗口内的实测分布（min/p25/median/p75/max）与
 * `≤ 0.02`、`≤ 0` 的占比，让读者能自行判断 floor 是否落在域内 —— 不必相信本脚本
 * 的任何一句话。
 *
 * ── 聚合口径（跨脚本相减前必须对齐）────────────────────────────────────
 * 本脚本的 recall 是**微平均**：逐题 0/1 pooled 后除以总题数（1986），
 * 即 `j5-rrf-e2e-decomposition.ts` 的口径。产物同时给出**宏平均**
 * （每对话先算 hits/qa 再对对话取均值，`p2-quantile` 口径）——
 * 各对话题数不相等（199/105/193/260/242/158/190/239/196/204），
 * 故两者不等（基线臂差约 0.0079）。**引用本表数字时必须声明用哪个口径**，
 * 否则与报宏平均的另一份产物相减会得到一个纯口径artifact 的假差。
 *
 * ── 臂 ──────────────────────────────────────────────────────────────────
 *   store-default      standardized + 去重 + DEFAULT 权重   ← 基线
 *   rrf-default        rrf+ 去重 + DEFAULT 权重
 *   rrf-corrected      rrf          + 去重 + CORRECTED 权重（recency = 0）
 *   additive-default   additive     + 去重 + DEFAULT 权重   ← 分数量级参照
 *
 * `store-default` 与 (B) 的参考跑**是同一次调用**（同 config、fused 模式
 * K 无关），故基线臂不额外跑 retrieve；脚本每 50 题对每个窗口大于 MAXK 的臂断言
 * 一次 `retrieve(q, 8)` 的 id 序列 == `retrieve(q, 150)` 的前 8，防止将来有人把
 * fused 路径改成 K 依赖时静默失效（`additive` 因legacy K 依赖头不参与此断言）。
 *
 * ── 口径边界（如实记录）──────────────────────────────────────────────────
 * · `retrievalFloor` **不被 `retrieve()` 读取**（只在 `eval` 侧与
 *   `src/locomo.ts` 用），故臂内把它设成 0 不改变排序；判据 (C) 用的 0.02 是
 *   脚本内的显式常量 `FLOOR`，不读那个字段。
 * · (A) 与 `retrievalFloor = 0` **不是同一件事**：`standardized` / `additive`
 *   的分数可以是零或负，floor = 0 仍会剔掉它们；(A) 是纯排名。脚本记录
 *   `top-8 非正分数个数` 与窗口 `≤0%`，使两者的差异可查。
 * · `additive` 沿用 legacy 的 **K 依赖**冲突重排头（`penaltyHead = topK`），
 *   故其窗口只能取 8，且 R@1/2/4 是"从一次 topK=8 的检索里按位置还原"。
 *   这是 legacy 路径的固有性质，不是脚本缺陷。
 *
 * 用法：tsx eval/j5-rrf-floor-control.ts [path-to-locomo.json] [conv-limit]
 */
import type { BioticMemory, GatingCoefficients, RetrievalScoreMode, RetrievalWeights } from '../src/index'

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
import { avg, goldEvidenceIds, KS, measure } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

const MAXK = Math.max(...KS)
/** (B)/(C) 共用的阈值，取 shipped 默认值，本脚本不调它。 */
const FLOOR = DEFAULT_MEMORY_CONFIG.retrievalFloor
/** fused 模式的检索窗口。取 150 兼作分数域取样窗（其 R@K 取前 MAXK 项）。 */
const FUSED_WINDOW = 150
/** 每 N 题做一次「topK=8 前缀 == 全池前 8」断言。 */
const PREFIX_ASSERT_EVERY = 50

/** RRF 权重和（affect 不参与 RRF，故只累加四个component）。 */
const RRF_SUM_W = (w: RetrievalWeights) => w.similarity + w.strength + w.recency + w.context

interface Arm {
  key: string
  note: string
  scoreMode: RetrievalScoreMode
  weights: RetrievalWeights
  /** fused 模式 K 无关，窗口可放大；additive 的冲突重排头 K 依赖，只能取 MAXK。 */
  window: number
  /** 是否为族 B 的唯一基线（同时是 (B) 的参考跑，故不额外跑 retrieve）。 */
  baseline?: boolean
}

const ARMS: Arm[] = [
  {
    key: 'store-default',
    note: '【基线】standardized + 去重 + DEFAULT 权重（= (B) 的参考跑，同一次调用）',
    scoreMode: 'standardized',
    weights: DEFAULT_RETRIEVAL_WEIGHTS,
    window: FUSED_WINDOW,
    baseline: true,
  },
  {
    key: 'rrf-default',
    note: 'rrf(k=60) + 去重 + DEFAULT 权重',
    scoreMode: 'rrf',
    weights: DEFAULT_RETRIEVAL_WEIGHTS,
    window: FUSED_WINDOW,
  },
  {
    key: 'rrf-corrected',
    note: 'rrf + 去重 + CORRECTED 权重（recency 置 0）',
    scoreMode: 'rrf',
    weights: CORRECTED_RETRIEVAL_WEIGHTS,
    window: FUSED_WINDOW,
  },
  {
    key: 'additive-default',
    note: 'additive + 去重 + DEFAULT 权重（分数量级参照；legacy K 依赖冲突头）',
    scoreMode: 'additive',
    weights: DEFAULT_RETRIEVAL_WEIGHTS,
    window: MAXK,
  },
]

type Criterion = 'rankOnly' | 'sharedStandardized' | 'ownScore'

const CRITERIA: Criterion[] = ['rankOnly', 'sharedStandardized', 'ownScore']

const CRITERION_LABEL: Record<Criterion, string> = {
  rankOnly: '(A) rank-only',
  sharedStandardized: '(B) shared-standardized',
  ownScore: '(C) own-score',
}

const CRITERION_NOTE: Record<Criterion, string> = {
  rankOnly: '(A) rank-only：只看排名，完全不看分数 —— 采用口径',
  sharedStandardized: `(B) shared-standardized：金标准 且 store-standardized 全池分数 > ${FLOOR} —— 对照口径`,
  ownScore: `(C) own-score：金标准 且 本臂自己的分数 > ${FLOOR} —— 复现现有污染条件，不作结论依据`,
}

/** 把 store 的检索配置切成某一臂。就地改，保证"同 build"。 */
function applyArm(mem: BioticMemory, arm: Arm): void {
  mem.config.retrievalScoreMode = arm.scoreMode
  mem.config.dedupeByContent = true
  mem.config.weights = { ...arm.weights }
  // 采用口径：臂内一律关掉 floor。它不参与 retrieve()，只影响读它的人；
  // 判据 (C) 用的是下面显式写死的 FLOOR，不读这个字段。
  mem.config.retrievalFloor = 0
}

interface Candidate {
  id: string
  score: number
}

/** (B) 的判据来源：store 默认（standardized + DEFAULT）在**全池**上的分数。 */
class SharedFloor {
  private readonly m = new Map<string, number>()

  set(id: string, score: number): void {
    this.m.set(id, score)
  }

  /** 池里没有该 id ⇒ 判为未过 floor（与 `j5-rrf-e2e-independent.ts` 同处理）。 */
  above(id: string): boolean {
    return (this.m.get(id) ?? Number.NEGATIVE_INFINITY) > FLOOR
  }
}

function rel(c: Candidate, gold: Set<string>, criterion: Criterion, shared: SharedFloor): boolean {
  if (!gold.has(c.id))
    return false
  if (criterion === 'rankOnly')
    return true
  if (criterion === 'sharedStandardized')
    return shared.above(c.id)
  return c.score > FLOOR
}

interface ArmAcc {
  recall: Record<Criterion, Record<number, number[]>>
  /**
   * 逐对话的命中数与题数 —— 用于**宏平均**（每对话先算比例再对对话取均值）。
   * 与 `recall`（逐题 pooled 数组的均值，即**微平均**）并存，两者之差就是聚合口径差。
   */
  convHits: Record<Criterion, number[]>
  convTotals: number[]
  mrr: Record<Criterion, number[]>
  /** 本臂分数在检索窗口内的全部取值（分数域实测）。 */
  windowScores: number[]
  windowAboveFloor: number
  windowTotal: number
  /** 窗口内分数 `≤ 0` 的个数 —— 量化「floor=0 仍不等于纯排名」。 */
  windowNonPositive: number
  /** top-MAXK 内分数 `≤ 0` 的个数。 */
  topKNonPositive: number
  /** top-MAXK 内的金标准候选数 / 其中被 (C) 判死的个数。 */
  topKGold: number
  topKGoldKilledByOwnFloor: number
  /** top-MAXK 内金标准候选中被 (B) 判死的个数（基线臂应为 0：(B) 与 (C) 同源）。 */
  topKGoldKilledBySharedFloor: number
}

function newAcc(): ArmAcc {
  return {
    recall: Object.fromEntries(CRITERIA.map(c => [c, Object.fromEntries(KS.map(k => [k, [] as number[]]))])),
    convHits: Object.fromEntries(CRITERIA.map(c => [c, [] as number[]])),
    convTotals: [],
    mrr: Object.fromEntries(CRITERIA.map(c => [c, [] as number[]])),
    windowScores: [],
    windowAboveFloor: 0,
    windowTotal: 0,
    windowNonPositive: 0,
    topKNonPositive: 0,
    topKGold: 0,
    topKGoldKilledByOwnFloor: 0,
    topKGoldKilledBySharedFloor: 0,
  }
}

/** 宏平均：每对话先算 hits/qa，再对各对话取均值（`p2-quantile` 口径）。 */
function macroOf(hits: number[], totals: number[]): number {
  if (totals.length === 0)
    return 0
  let s = 0
  for (let i = 0; i < totals.length; i++)
    s += totals[i] > 0 ? hits[i] / totals[i] : 0
  return s / totals.length
}

function summarise(a: number[]): { min: number, p25: number, median: number, p75: number, max: number, n: number } {
  if (a.length === 0)
    return { min: 0, p25: 0, median: 0, p75: 0, max: 0, n: 0 }
  const s = a.slice().sort((x, y) => x - y)
  const at = (p: number) => s[Math.min(s.length - 1, Math.max(0, Math.round(p * (s.length - 1))))]
  return { min: s[0], p25: at(0.25), median: at(0.5), p75: at(0.75), max: s[s.length - 1], n: s.length }
}

const pct = (num: number, den: number) => (den > 0 ? num / den : 0)

/** 与 `eval-metrics.measure()` 同定义的 recall@K + MRR@maxK，只是判据可切换。 */
function rankOne(ranking: Candidate[], gold: Set<string>, criterion: Criterion, shared: SharedFloor) {
  const hit: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  let rr = 0
  for (let pos = 0; pos < ranking.length; pos++) {
    if (!rel(ranking[pos], gold, criterion, shared))
      continue
    if (rr === 0)
      rr = 1 / (pos + 1)
    for (const k of KS) {
      if (pos + 1 <= k)
        hit[k] = 1
    }
  }
  return { hit, rr }
}

/** 按三档判据累计一臂的命中、MRR 与分数域统计。 */
function scoreArm(a: ArmAcc, ranking: Candidate[], gold: Set<string>, shared: SharedFloor): void {
  for (const c of ranking) {
    a.windowScores.push(c.score)
    a.windowTotal++
    if (c.score > FLOOR)
      a.windowAboveFloor++
    if (c.score <= 0)
      a.windowNonPositive++
  }
  for (const c of ranking.slice(0, MAXK)) {
    if (c.score <= 0)
      a.topKNonPositive++
    if (gold.has(c.id)) {
      a.topKGold++
      if (!(c.score > FLOOR))
        a.topKGoldKilledByOwnFloor++
      if (!shared.above(c.id))
        a.topKGoldKilledBySharedFloor++
    }
  }
  for (const criterion of CRITERIA) {
    const r = rankOne(ranking, gold, criterion, shared)
    for (const k of KS)
      a.recall[criterion][k].push(r.hit[k])
    a.mrr[criterion].push(r.rr)
  }
}

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const sha = sha256File(path)
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== J5/P4 RRF 端到端 floor 对照：三档判据 × 四臂 ===')
  console.info(`corpus   : ${path}`)
  console.info(`sha256   : ${sha}`)
  console.info(`convs    : ${convs.length}`)
  console.info(`condition: NO_GATING；去重恒开；判据阈值 FLOOR = ${FLOOR}`)
  console.info('臂内 mem.config.retrievalFloor = 0（采用口径；retrieve() 不读该字段）')
  console.info()

  const acc: Record<string, ArmAcc> = Object.fromEntries(ARMS.map(a => [a.key, newAcc()]))
  const crossRankOnly: number[] = []
  const crossOwnScore: number[] = []
  const poolSizes: number[] = []
  let questions = 0
  let prefixAsserts = 0

  for (const [ci, conv] of convs.entries()) {
    const goldAll = goldEvidenceIds(conv)
    const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)

    // 断言：buildMemory 不给显式模式 ⇒ 默认 standardized。
    if (mem.config.retrievalScoreMode !== 'standardized')
      throw new Error(`默认模式不是 standardized：${String(mem.config.retrievalScoreMode)}`)

    // 本对话开始前各臂已累计的命中条数 —— 用于事后切出「本对话」的命中数（宏平均）。
    const mark = Object.fromEntries(ARMS.map(a => [a.key, acc[a.key].recall.rankOnly[MAXK].length]))

    // 本对话内基线臂的逐题命中，仅用于与 `measure()` 的**逐对话**交叉校验。
    const baseHit: Record<Criterion, Record<number, number[]>> = {
      rankOnly: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      sharedStandardized: Object.fromEntries(KS.map(k => [k, [] as number[]])),
      ownScore: Object.fromEntries(KS.map(k => [k, [] as number[]])),
    }

    for (const [qi, q] of conv.qa.entries()) {
      const gold = new Set<string>()
      for (const e of q.evidence ?? []) {
        if (!conv.evidenceIds.has(e))
          continue
        gold.add(e)
        gold.add(`fact_${e}`)
      }

      // ── 参考跑（= 基线臂 = 判据 B 的来源）：standardized + DEFAULT，全池。
      applyArm(mem, ARMS[0])
      const refAll = mem.retrieve(q.question, 1_000_000, false)
      poolSizes.push(refAll.length)
      const shared = new SharedFloor()
      for (const c of refAll)
        shared.set(c.id, c.score)

      // fused 路径的 topK 前缀不变式：窗口跑的前 8 必须等于一次 topK=8 的检索。
      // （`standardized` 与 `rrf` 的冲突重排头是常量150，故其分数与 topK 无关；
      //   `additive` 的头是 topK，本就不满足，故不参与此断言。）
      if (qi % PREFIX_ASSERT_EVERY === 0) {
        const narrow = mem.retrieve(q.question, MAXK, false).map(c => c.id)
        const wide = refAll.slice(0, MAXK).map(c => c.id)
        if (narrow.join('|') !== wide.join('|'))
          throw new Error(`standardized 路径出现 K 依赖：topK=8 与全池前 8 不一致（题 ${qi}）`)
        prefixAsserts++
      }

      // ── 基线臂：直接复用参考跑（fused 模式 K 无关，全池排序的前 k 即 top-k）。
      scoreArm(acc['store-default'], refAll.slice(0, FUSED_WINDOW).map(c => ({ id: c.id, score: c.score })), gold, shared)
      for (const criterion of CRITERIA) {
        const r = rankOne(refAll.slice(0, MAXK).map(c => ({ id: c.id, score: c.score })), gold, criterion, shared)
        for (const k of KS)
          baseHit[criterion][k].push(r.hit[k])
      }

      // ── 其余三臂。
      for (const arm of ARMS.slice(1)) {
        applyArm(mem, arm)
        const ranking = mem.retrieve(q.question, arm.window, false)
        scoreArm(acc[arm.key], ranking.map(c => ({ id: c.id, score: c.score })), gold, shared)
        if (arm.window > MAXK && qi % PREFIX_ASSERT_EVERY === 0) {
          const narrow = mem.retrieve(q.question, MAXK, false).map(c => c.id)
          const wide = ranking.slice(0, MAXK).map(c => c.id)
          if (narrow.join('|') !== wide.join('|'))
            throw new Error(`${arm.key}（${arm.scoreMode}）出现 K 依赖：topK=8 与 topK=${arm.window} 的前 8 不一致（题 ${qi}）`)
          prefixAsserts++
        }
      }

      questions++
    }

    // ── 交叉校验：同一对话、同一基线配置，用仓库共用的 `measure()` 再算一遍。
    //   · `retrievalFloor = FLOOR`  ⇒ 对应判据 (C)
    //   · `retrievalFloor = -Inf`   ⇒ 对应判据 (A)（`c.score > -Inf` 恒真 = 纯排名）
    applyArm(mem, ARMS[0])
    mem.config.retrievalFloor = FLOOR
    {
      const shared = measure(mem, conv, goldAll)
      for (const k of KS)
        crossOwnScore.push(shared.recall[k] - avg(baseHit.ownScore[k]))
    }
    mem.config.retrievalFloor = Number.NEGATIVE_INFINITY
    {
      const shared = measure(mem, conv, goldAll)
      for (const k of KS)
        crossRankOnly.push(shared.recall[k] - avg(baseHit.rankOnly[k]))
    }

    // ── 宏平均素材：本对话各臂各判据的命中数（命中数组自`mark` 起的增量）。
    for (const a of ARMS) {
      for (const criterion of CRITERIA) {
        const carr = acc[a.key].recall[criterion][MAXK]
        let h = 0
        for (let i = mark[a.key]; i < carr.length; i++)
          h += carr[i]
        acc[a.key].convHits[criterion].push(h)
      }
      acc[a.key].convTotals.push(conv.qa.length)
    }

    console.info(`  [${ci + 1}/${convs.length}] conv ok（累计 ${questions} 题）`)
  }

  // ─────────────────────────────────────────────────────────── 分数域汇总
  const domain = (key: string) => {
    const a = acc[key]
    return {
      window: ARMS.find(x => x.key === key)!.window,
      ...summarise(a.windowScores),
      shareAboveFloor: pct(a.windowAboveFloor, a.windowTotal),
      shareNonPositive: pct(a.windowNonPositive, a.windowTotal),
      topKNonPositive: a.topKNonPositive,
      topKGold: a.topKGold,
      topKGoldKilledByOwnFloor: a.topKGoldKilledByOwnFloor,
      topKGoldKilledBySharedFloor: a.topKGoldKilledBySharedFloor,
    }
  }

  const R = (key: string, c: Criterion, k: number) => avg(acc[key].recall[c][k])
  /** 宏平均版（每对话先算比例再对对话取均值）。 */
  const RMacro = (key: string, c: Criterion) => macroOf(acc[key].convHits[c], acc[key].convTotals)

  // ─────────────────────────────────────────────────────────── 打印
  console.info()
  for (const criterion of CRITERIA) {
    console.info(CRITERION_NOTE[criterion])
    console.info(`  ${'arm'.padEnd(18)}${KS.map(k => `R@${k}`.padStart(9)).join('')}${'MRR@8'.padStart(9)}${'R@8(macro)'.padStart(12)}`)
    for (const a of ARMS)
      console.info(`  ${a.key.padEnd(18)}${KS.map(k => R(a.key, criterion, k).toFixed(4).padStart(9)).join('')}${avg(acc[a.key].mrr[criterion]).toFixed(4).padStart(9)}${RMacro(a.key, criterion).toFixed(4).padStart(12)}`)
    console.info()
  }

  console.info('--- 各臂「自己分数」的实测域（判定 floor 是否落在域内）---')
  console.info(`  ${'arm'.padEnd(18)}${'win'.padStart(5)}${'min'.padStart(10)}${'p25'.padStart(10)}${'median'.padStart(10)}${'p75'.padStart(10)}${'max'.padStart(10)}${'>flr%'.padStart(8)}${'<=0%'.padStart(8)}${'topK<=0'.padStart(8)}`)
  for (const a of ARMS) {
    const d = domain(a.key)
    console.info(`  ${a.key.padEnd(18)}${String(d.window).padStart(5)}${d.min.toFixed(5).padStart(10)}${d.p25.toFixed(5).padStart(10)}${d.median.toFixed(5).padStart(10)}${d.p75.toFixed(5).padStart(10)}${d.max.toFixed(5).padStart(10)}${(d.shareAboveFloor * 100).toFixed(1).padStart(8)}${(d.shareNonPositive * 100).toFixed(1).padStart(8)}${String(d.topKNonPositive).padStart(8)}`)
  }
  {
    const sumW = RRF_SUM_W(ARMS[1].weights)
    console.info(`  RRF 权重和 Σw = ${sumW.toFixed(3)}；理论上限 Σw/61 = ${(sumW / 61).toFixed(5)}；FLOOR = ${FLOOR}`)
    console.info(`  ⇒ FLOOR ${FLOOR < sumW / 61 ? '<' : '≥'} RRF 上限，即 floor **落在 RRF 域内** ${FLOOR < sumW / 61 ? '✅' : '❌'}`)
  }
  console.info()

  console.info(`--- 污染量：(A) rank-only 减 (C) own-score（同为 R@${MAXK}）---`)
  for (const a of ARMS) {
    const d = R(a.key, 'rankOnly', MAXK) - R(a.key, 'ownScore', MAXK)
    console.info(`  ${a.key.padEnd(18)}${d >= 0 ? '+' : ''}${d.toFixed(4)}   top-${MAXK} 内被own-floor 判死的金标准候选 ${acc[a.key].topKGoldKilledByOwnFloor}/${acc[a.key].topKGold}`)
  }
  console.info()

  const maxOwn = Math.max(...crossOwnScore.map(Math.abs))
  const maxRank = Math.max(...crossRankOnly.map(Math.abs))
  console.info('--- 交叉校验（对标 eval/eval-metrics.ts 的 measure()）---')
  console.info(`  基线臂判据 (C)（floor=${FLOOR}）：最大偏差 ${maxOwn.toFixed(6)}  ${maxOwn < 1e-9 ? '✅ 逐位一致' : '❌ 口径写歪了'}`)
  console.info(`  基线臂判据 (A)（floor=-Inf，即纯排名）：最大偏差 ${maxRank.toFixed(6)}  ${maxRank < 1e-9 ? '✅ 逐位一致' : '❌ 口径写歪了'}`)
  console.info('  ⚠️ 该校验在**单个对话内部**做（与 decomp 脚本同），故分母相同、恒等；')
  console.info('     它能证明「逐题命中实现与 measure() 一致」，**结构上无法**发现跨对话的聚合口径差。')
  console.info(`  fused 前缀不变式断言通过 ${prefixAsserts} 次；平均池大小 = ${avg(poolSizes).toFixed(1)}`)
  console.info()

  console.info(`--- 聚合口径：微平均(micro) vs 宏平均(macro)，同为 R@${MAXK} ---`)
  console.info(`  ${'arm'.padEnd(18)}${'判据'.padEnd(10)}${'micro'.padStart(10)}${'macro'.padStart(10)}${'micro-macro'.padStart(13)}`)
  for (const a of ARMS) {
    for (const criterion of CRITERIA) {
      const mi = R(a.key, criterion, MAXK)
      const ma = RMacro(a.key, criterion)
      console.info(`  ${a.key.padEnd(18)}${CRITERION_LABEL[criterion].padEnd(10)}${mi.toFixed(6).padStart(10)}${ma.toFixed(6).padStart(10)}${(mi - ma >= 0 ? '+' : '')}${(mi - ma).toFixed(6).padStart(12)}`)
    }
  }
  console.info('  各对话题数（不相等 ⇒ 宏≠微）：', acc['store-default'].convTotals.join(','))
  console.info()

  // ─────────────────────────────────────────────────────────── 判读
  const verdicts: string[] = []
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`
  verdicts.push(`【① 判据敏感性：三档口径下的 recall@${MAXK}】`)
  for (const a of ARMS)
    verdicts.push(`  ${a.key.padEnd(18)} rank-only ${R(a.key, 'rankOnly', MAXK).toFixed(4)}   shared ${R(a.key, 'sharedStandardized', MAXK).toFixed(4)}   own ${R(a.key, 'ownScore', MAXK).toFixed(4)}`)
  verdicts.push('')
  verdicts.push('【② (A) 与 (B) 是否一致 —— 判据自身是否也带污染】')
  for (const a of ARMS) {
    const dAB = R(a.key, 'rankOnly', MAXK) - R(a.key, 'sharedStandardized', MAXK)
    verdicts.push(`  ${a.key.padEnd(18)} ${fmt(dAB)}   （top-${MAXK} 金标准候选被 shared-floor 判死 ${acc[a.key].topKGoldKilledBySharedFloor}/${acc[a.key].topKGold}）`)
  }
  verdicts.push('')
  verdicts.push(`【③ RRF vs standardized：结论必须以 (A) 或 (B) 为准，(C) 含 floor 污染】`)
  for (const criterion of CRITERIA) {
    const d = R('rrf-default', criterion, MAXK) - R('store-default', criterion, MAXK)
    verdicts.push(`  以 ${CRITERION_LABEL[criterion].padEnd(23)} rrf-default ${R('rrf-default', criterion, MAXK).toFixed(4)}  vs  store-default ${R('store-default', criterion, MAXK).toFixed(4)}  ${fmt(d)}`)
  }
  for (const criterion of CRITERIA) {
    const d = R('rrf-corrected', criterion, MAXK) - R('store-default', criterion, MAXK)
    verdicts.push(`  以 ${CRITERION_LABEL[criterion].padEnd(23)} rrf-corrected ${R('rrf-corrected', criterion, MAXK).toFixed(4)}  vs  store-default ${R('store-default', criterion, MAXK).toFixed(4)}  ${fmt(d)}`)
  }
  verdicts.push('')
  verdicts.push('【④ (A) vs (C) 的污染量 = own-score 口径低估了多少】')
  for (const a of ARMS)
    verdicts.push(`  ${a.key.padEnd(18)} ${fmt(R(a.key, 'rankOnly', MAXK) - R(a.key, 'ownScore', MAXK))}   （top-${MAXK} 金标准候选被own-floor 判死 ${acc[a.key].topKGoldKilledByOwnFloor}/${acc[a.key].topKGold}）`)
  verdicts.push('')
  verdicts.push('【⑤ 聚合口径：本表数字是微平均，跨脚本相减前必须先对齐】')
  verdicts.push(`  ${'arm'.padEnd(18)}${'判据'.padEnd(10)}${'micro'.padStart(10)}${'macro'.padStart(10)}${'micro-macro'.padStart(13)}`)
  for (const a of ARMS) {
    for (const criterion of CRITERIA) {
      const mi = R(a.key, criterion, MAXK)
      const ma = RMacro(a.key, criterion)
      verdicts.push(`  ${a.key.padEnd(18)}${CRITERION_LABEL[criterion].padEnd(10)}${mi.toFixed(6).padStart(10)}${ma.toFixed(6).padStart(10)}${(mi - ma >= 0 ? '+' : '')}${(mi - ma).toFixed(6).padStart(12)}`)
    }
  }
  verdicts.push(`  各对话题数（不相等 ⇒ 宏 ≠ 微）：${acc['store-default'].convTotals.join(',')}`)
  verdicts.push('  ⇒ 本表全部 recall 为**微平均**（逐题 0/1 pooled 后除以总题数 1986）。')
  verdicts.push('     若另一份产物报的是宏平均（每对话先算比例再均值），两个数不可直接相减。')
  verdicts.push('')
  verdicts.push('⚠️ 口径：')
  verdicts.push('  · 本表全部数字属族 B（端到端、全池、含检索噪声与冲突惩罚），与族 A（重排 top-150）不可互比。')
  verdicts.push('  · (A) 是采用口径：跨打分模式比较时 floor 不是可比判据，已按定义关闭。')
  verdicts.push(`  · additive 臂沿用 legacy K 依赖冲突头，窗口=${MAXK}，R@1/2/4 由一次 topK=8 检索按位置还原。`)
  verdicts.push(`  · 基线臂与 (B) 参考跑是同一次调用；fused 前缀不变式已断言 ${prefixAsserts} 次。`)
  verdicts.push('  · (A) 与 "retrievalFloor=0" 不是同一件事：standardized/additive 的分数可为 0 或负，floor=0 仍会剔掉它们。')
  verdicts.push('  · 与 measure() 的交叉校验在单对话内完成（分母相同故恒等），只能证明逐题命中实现一致，无法发现跨对话聚合差。')

  console.info('--- 判读（全部由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts)
    console.info(v)

  // ─────────────────────────────────────────────────────────── 产物
  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })
  const outPath = join(outDir, `j5-rrf-floor-control-${stamp}.json`)
  writeFileSync(outPath, `${JSON.stringify(withProvenance({
    generatedAt: new Date().toISOString(),
    experiment: 'j5-rrf-floor-control',
    calibrationFamily: 'B-end-to-end',
    corpus: { path, sha256: sha, conversations: convs.length },
    condition: 'NO_GATING',
    dedupeByContent: true,
    ks: KS,
    questions,
    poolSizeMean: avg(poolSizes),
    floor: FLOOR,
    floorConfigInArms: 0,
    criteria: {
      rankOnly: '(A) rel = gold in top-K; score ignored entirely (adoption criterion)',
      sharedStandardized: `(B) rel = gold AND store-standardized whole-pool score > ${FLOOR} (reference criterion)`,
      ownScore: `(C) rel = gold AND this arm own score > ${FLOOR} (reproduces the contaminated condition)`,
    },
    fusedPrefixInvarianceAsserts: prefixAsserts,
    scoreDomainNote:
      '每臂的 ownScoreDomain 是**该臂自己分数**在检索窗口内的实测分布。(A) rank-only 不看分数，故无分数域；'
      + '(B) 的判据分数域等于 store-default 臂的 ownScoreDomain（参考跑同源）；'
      + '(C) 的判据分数域等于各臂自己的 ownScoreDomain。对照 floor = '
      + `${FLOOR}：若该臂 ownScoreDomain 的 min < ${FLOOR} < max，则 floor 落在其域内。`,
    arms: ARMS.map(a => ({
      arm: a.key,
      note: a.note,
      baseline: a.baseline === true,
      scoreMode: a.scoreMode,
      weights: a.weights,
      recall: Object.fromEntries(CRITERIA.map(c => [c, Object.fromEntries(KS.map(k => [k, R(a.key, c, k)]))])),
      recallMacroAtMaxK: Object.fromEntries(CRITERIA.map(c => [c, RMacro(a.key, c)])),
      mrrAtMaxK: Object.fromEntries(CRITERIA.map(c => [c, avg(acc[a.key].mrr[c])])),
      ownScoreDomain: domain(a.key),
    })),
    aggregation: {
      primary: 'micro',
      note: 'recall 字段为**微平均**（逐题 0/1 pooled ÷ 总题数）。recallMacroAtMaxK 为**宏平均**'
        + '（每对话先算 hits/qa 再对对话取均值，p2-quantile 口径）。各对话题数不相等，'
        + '故两者不等；跨脚本相减前必须先对齐口径。',
      perConvQuestions: acc['store-default'].convTotals,
      microMinusMacroAtMaxK: Object.fromEntries(ARMS.map(a => [
        a.key,
        Object.fromEntries(CRITERIA.map(c => [c, R(a.key, c, MAXK) - RMacro(a.key, c)])),
      ])),
    },
    contamination: Object.fromEntries(ARMS.map(a => [
      a.key,
      {
        rankOnlyMinusOwnScoreAtMaxK: R(a.key, 'rankOnly', MAXK) - R(a.key, 'ownScore', MAXK),
        topKGoldCandidates: acc[a.key].topKGold,
        topKGoldKilledByOwnFloor: acc[a.key].topKGoldKilledByOwnFloor,
        topKGoldKilledBySharedFloor: acc[a.key].topKGoldKilledBySharedFloor,
      },
    ])),
    calibration: {
      recallImplMaxDeltaVsMeasure_ownScore: maxOwn,
      recallImplMaxDeltaVsMeasure_rankOnly: maxRank,
    },
    verdicts,
  }, { scoreMode: 'standardized', weights: DEFAULT_RETRIEVAL_WEIGHTS }), null, 2)}\n`, 'utf8')
  console.info()
  console.info(`artifact: ${outPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
