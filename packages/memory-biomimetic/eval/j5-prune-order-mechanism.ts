import type { BioticMemory, Distiller, GatingCoefficients, LocomoConversation, RetrievalWeights } from '../src/index'

/**
 * 判定性对照：J5 论文 §5.6「缺陷 C」把一个 +0.24 量级的跳变归因于
 * **池子规模**，而 `diag-oracle-tiebreak.ts` 把它归因于
 * **剪枝顺序（丢掉最近那批干扰项）**。两个归因互斥，必须用同一个实验分开。
 *
 * ── 本脚本要回答的四个问题 ───────────────────────────────────────────────
 *   Q1 复现：`p2-index-duplication-confusion-2026-09-15.json` 的 poolSize /
 *      recall@8 两列（dup 与 nofact，q = 1 → 0.3）是否逐位一致。
 *   Q2 关键对照：**池规模完全固定**、只改「剪掉谁」。
 *   Q3 归因：每种策略被剪项的**年龄分布**。
 *   Q4 `q = 1` 是否走「完全不剪枝」的**代码特例分支**。
 *
 * ── Q2 的控制为什么能做成严格控制（这是本脚本的核心设计）───────────────
 * `src/store.ts:803`：
 *   const k = Math.max(1, Math.min(pending.length,
 *                 Math.round(pending.length * clamp01(opts.keepFraction))))
 *   const ranked = [...pending].sort((a,b) => b.encoding.salience - a.encoding.salience)
 *                      .slice(0, k)
 * `k` **只由 pending 的条数与 q 决定，与显著性数值无关**。
 * ⇒ 在同一个 q 下，**任何**并列打破方式得到的池规模**逐条相同**。
 *   「池规模」这个混淆在 `keepFraction` 这条路径上**被结构性地消除了**。
 *
 * ── 为什么不能沿用 `diag-oracle-tiebreak.ts` 的 `jitter` 臂 ──────────────
 * 那个脚本靠改 `salienceOf` 的**数值**（非证据取 [0,0.5) 随机值）来破并列。
 * 但 `salienceOverride` 不只用于排序，还经 `src/store.ts:261` 进入
 *   durability = 1 + kSalience·salience + kSocial·socialSalience
 * 再经 `src/forgetting.ts:34` 的 decay 指数影响 `retrievalStrength`。
 * ⇒旧jitter 臂同时改变了「剪掉谁」**和**「留下的项有多强」，
 *   它测到的曲线差异**不能**干净地归因到剪枝顺序。
 *   本脚本保留该臂作 `salJitter`，只为**量化这层混淆有多大**。
 *
 * ── 本脚本的破并列方式：只改**插入顺序**，不改任何显著性数值 ─────────────
 * `buildMemory` 按 `conv.episodes` 顺序逐条 `encode`（src/locomo.ts:205），
 * `pending` 由 `episodes.filter(...)` 得到因而保持该顺序，而 V8 的
 * `Array.prototype.sort` 是**稳定排序** ⇒ 并列项保持相对顺序
 * ⇒ `slice(0, k)` 保留的是「插入顺序里最靠前的那批」。
 * 于是：
 *   chrono  —— 插入序=时间序 ⇒ 保留**最老**的 ⇒ 剪掉**最近**的（现有行为）
 *   lifo    —— 插入序=逆时间序 ⇒ 保留**最新**的 ⇒ 剪掉**最老**的
 *   shuffled—— 插入序=确定性随机 ⇒ 保留随机的一批
 * 三臂的 salience 逐条相同（证据=1、非证据=0）⇒ durability、decay、
 * 检索分公式**完全一致**，唯一差别就是「池里是哪批 id」。
 *
 * ── 残余差异的量化（`placebo` 臂）──────────────────────────────────────
 * 池内**顺序**理论上仍可能通过两处泄漏影响结果：
 *   ① `scored.sort((a,b)=>b.score-a.score)`（store.ts:1035/1047）也是稳定排序，
 *      分数逐位相等时会按池内顺序决胜；
 *   ② `buildLexicalIndex` 的 `vocab` 顺序会随文档顺序变，进而 `vidx` 变。
 *      但这只是**一致地置换了维度编号**，余弦相似度对维度置换不变。
 * ① 无法从原理上排除，故设 `placebo` 臂：与 `chrono` 剪掉**完全同一批** id，
 *   但把留下的项在插入序里随机打乱。池的**成员与规模完全相同**，
 *   只剩池内顺序不同 ⇒ 该臂与 `chrono` 的 recall 差就是**顺序效应的上界**，
 *   也就是本实验全部结论的残余差异。
 *
 * ── 分片并行（collect / merge 两段）────────────────────────────────────
 * 单次 `retrieve` 约 100ms（`src/store.ts:1036` 的 150² 冲突重排主导），
 * 全量 53 臂 × 10 会话 × 2 次 retrieve（度量 + 交叉校验）串行需数小时。
 * 故拆成两段：
 *   tsx eval/j5-prune-order-mechanism.ts collect <shard> <nshards> <out.json>
 *   tsx eval/j5-prune-order-mechanism.ts merge <out.json>...
 * `collect` 只跑**原始累加器**（每会话每臂一组数），按会话下标取模分片；
 * `merge` 把各分片的原始累加器拼接后统一汇总并出报告。
 * 分片是**按会话切分**的，合并时数组直接首尾相接——因为每会话权重相等，
 * 「先拼后求均」与「逐会话求均再平均」在数值上等价，口径不变。
 *
 * 用法：
 *   collect: tsx eval/j5-prune-order-mechanism.ts collect 0 4 /tmp/s0.json
 *   merge  : tsx eval/j5-prune-order-mechanism.ts merge /tmp/s0.json /tmp/s1.json ...
 */
import process from 'node:process'

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { buildMemory, CORRECTED_RETRIEVAL_WEIGHTS, DEFAULT_GATING, loadLocomo } from '../src/index'
import { withProvenance } from './artifact-provenance'
import { avg, goldEvidenceIds, KS, measure, mulberry32, shuffledCopy } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

/** Q1 复现用的 q 网格 —— 必须与 `diag-index-duplication-confusion.ts` 一致。 */
const QS_REPRO = [1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
/** Q2/Q3 的 q 网格 —— 在 q = 1 附近加细，用于判断跳变是连续量变还是台阶。 */
const QS_MECH = [1, 0.98, 0.95, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
/** 旧口径只需在几个q 上与 `shuffled` 对比即可量化混淆，故只跑这四档。 */
const QS_JITTER = [1, 0.9, 0.6, 0.3]
/** placebo 臂对照的 q。 */
const QS_PLACEBO = [0.9, 0.6, 0.3]
/**
 * recency=0 变体的 q 网格。
 *
 * 判决性预测：若缺陷 C 的断崖来自「recency 主导的近邻干扰项占据 top-K 槽位」，
 * 则把 recency 权重置0 后，chrono 的 q=1→0.9 断崖应显著缩小。
 * 只跑 q=1 与 q=0.9 两档——它们正是断崖的两端，中间的 q 网格对本判决无增量。
 */
const QS_NOREC = [1, 0.9]
const MAXK = Math.max(...KS)

/** 不产出事实的蒸馏器 —— 排除 `fact_<id>` 重复副本对池规模的干扰。 */
const NULL_DISTILLER: Distiller = { distill: async () => [] }

/** 破并列的三种插入序（只改顺序，不改显著性数值）。 */
type Strat = 'chrono' | 'lifo' | 'shuffled'
const STRATS: Strat[] = ['chrono', 'lifo', 'shuffled']

/**
 * 构造一份 episode 插入顺序被重排的 conversation 副本。
 *
 * 只动 `episodes` 数组的顺序，**不改任何 episode 的字段**（id / content /
 * createdAt / encoding 全部原样），因此 salience、durability、createdAt
 * 逐条不变，唯一变化是 `pending` 的排列顺序。
 */
function reorderEpisodes(conv: LocomoConversation, strat: Strat, seed: number): LocomoConversation {
  if (strat === 'chrono')
    return conv
  const eps = strat === 'lifo' ? conv.episodes.slice().reverse() : shuffledCopy(conv.episodes, mulberry32(seed))
  return { ...conv, episodes: eps }
}

/** 某个 episode 在本会话时间轴上的「年龄」：0 = 最新，1 = 最老。 */
function ageFraction(conv: LocomoConversation, createdAt: number): number {
  let lo = Number.POSITIVE_INFINITY
  let hi = Number.NEGATIVE_INFINITY
  for (const e of conv.episodes) {
    if (e.createdAt < lo)
      lo = e.createdAt
    if (e.createdAt > hi)
      hi = e.createdAt
  }
  if (!(hi > lo))
    return 0
  return (hi - createdAt) / (hi - lo)
}

/**
 * 独立实现的 recall@K，用于与 `eval-metrics.ts` 的 `measure()` 交叉校验。
 *
 * 刻意走**不同的代码路径**：
 *   · `measure()` 用 `retrieve(q, 8)` 再按位置还原各 K；
 *   · 本实现用 `retrieve(q, 9999)` 的**全量排序**，对每个金标准候选取
 *     1-based 名次，名次 ≤ K 即命中。
 * 二者若一致，同时验证了 recall 数值与「`retrieve` 的 top-k 是前缀」这一性质。
 * 判定条件与 `measure()` 对齐：分数必须严格高于 `retrievalFloor`。
 *
 * 每个查询对每个 K **最多计一次**（与 `measure()` 的 `hitAtK` 语义一致）：
 * 一个查询若有多条证据同时进榜，`measure()` 只记 1 次命中，若按「每条证据都加」
 * 就会把多证据查询重复计入，分母不变分子偏大 ⇒ 出现 K 越大偏差越大的假阳性。
 * （`fact_<id>` 与 `id` 同时在候选集里，这种重复是真实存在的。）
 */
function independentRecall(
  mem: { retrieve: (q: string, k: number, bump: boolean, weights?: Partial<RetrievalWeights>) => { id: string, score: number }[], config: { retrievalFloor: number } },
  conv: LocomoConversation,
  weights?: Partial<RetrievalWeights>,
): Record<number, number> {
  const floor = mem.config.retrievalFloor
  const covered: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  for (const q of conv.qa) {
    const cands = new Set<string>()
    for (const e of q.evidence ?? []) {
      if (!conv.evidenceIds.has(e))
        continue
      cands.add(e)
      cands.add(`fact_${e}`)
    }
    const full = mem.retrieve(q.question, 9999, false, weights)
    for (const k of KS) {
      // 该 K 下只要有一条证据落在前 k 名即算命中，至多计一次（对齐 measure 的 hitAtK）。
      for (let i = 0; i < full.length && i < k; i++) {
        const c = full[i]
        if (cands.has(c.id) && c.score > floor) {
          covered[k]++
          break
        }
      }
    }
  }
  return Object.fromEntries(KS.map(k => [k, covered[k] / conv.qa.length]))
}

/**
 * 检索指标。`weights` 为空时**直接委托**给 `eval-metrics.ts` 的 `measure()`，
 * 保证默认权重路径与全仓库其他实验逐位同口径（不在此处复刻它的实现）。
 *
 * `weights` 非空时按同一判定条件重算：金标准 id 在 top-K 且分数严格高于
 * `retrievalFloor`。注意 `poolSize` / `evidenceSurvival` / `prunedTotal` 与
 * 检索权重**无关**（它们只由剪枝结果决定），故仍取自默认口径的 `measure()`。
 */
function measureW(
  mem: BioticMemory,
  conv: LocomoConversation,
  gold: Set<string>,
  weights?: Partial<RetrievalWeights>,
): ReturnType<typeof measure> {
  const base = measure(mem, conv, gold)
  if (weights === undefined)
    return base
  const floor = mem.config.retrievalFloor
  const maxK = Math.max(...KS)
  const covered: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))
  const hitScores: number[] = []
  for (const q of conv.qa) {
    const cands = new Set<string>()
    for (const e of q.evidence ?? []) {
      if (!conv.evidenceIds.has(e))
        continue
      cands.add(e)
      cands.add(`fact_${e}`)
    }
    const ranking = mem.retrieve(q.question, maxK, false, weights)
    let best = Number.NEGATIVE_INFINITY
    for (let i = 0; i < ranking.length; i++) {
      const c = ranking[i]
      if (!cands.has(c.id))
        continue
      if (c.score > best)
        best = c.score
      if (c.score > floor) {
        for (const k of KS) {
          if (i + 1 <= k)
            covered[k]++
        }
      }
    }
    if (best > Number.NEGATIVE_INFINITY)
      hitScores.push(best)
  }
  return {
    ...base,
    recall: Object.fromEntries(KS.map(k => [k, covered[k] / conv.qa.length])),
    hitScoreMean: avg(hitScores),
  }
}

/** 一条臂的原始累加器 —— 分片之间可直接拼接，汇总在 merge 阶段做。 */
interface Raw {
  recall: Record<number, number[]>
  surv: number[]
  distinct: number[]
  pool: number[]
  /** 被剪掉的**非证据** episode 的年龄（0 = 最新，1 = 最老）。 */
  ages: number[]
  /** 被剪掉的**证据** episode 数（用于解释 evidenceSurvival 下降）。 */
  prunedGold: number[]
  xdiff: number[]
}

/** `runArm` 的入参描述：一臂所需的 conversation 副本、蒸馏器、显著性来源与 q。 */
interface ArmSpec {
  conv: LocomoConversation
  distiller: Distiller | undefined
  salienceOf: (e: { id: string, content: string }) => number | undefined
  q: number
  /**
   * 检索权重重载。`undefined` = 用产品默认权重。
   *
   * 只在**同一批`mem`** 上换权重重新打分（`retrieve` 的第4 个参数），
   * **绝不重新 `buildMemory`** —— 否则会引入一次额外混淆。
   */
  weights?: Partial<RetrievalWeights>
}

function newRaw(): Raw {
  return {
    recall: Object.fromEntries(KS.map(k => [k, [] as number[]])),
    surv: [],
    distinct: [],
    pool: [],
    ages: [],
    prunedGold: [],
    xdiff: [],
  }
}

// ───────────────────────────── collect ─────────────────────────────────────

async function collect(
  shard: number,
  nshards: number,
  outPath: string,
  pathArg?: string,
  limitArg?: string,
  only?: string,
): Promise<void> {
  // 可选的位置参数；`-` 表示"不显式指定"。传空串不行——`resolveLocomoPath`
  // 会把空串当成"用户明确指定了一个路径"并直接报错。
  const path = resolveLocomoPath(pathArg && pathArg !== '-' ? pathArg : undefined).path
  const limit = limitArg && limitArg !== '-' ? Number(limitArg) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll
  const mine = convs.map((_, i) => i).filter(i => i % nshards === shard)
  // `only='norec'` 时只跑 recency=0 变体（其余臂已在主分片跑完，
  // 不必为补两个臂重跑全网格）。其他值一律跑全网格。
  const norecOnly = only === 'norec'

  const acc: Record<string, Raw> = {}
  const bump = (k: string): Raw => (acc[k] ??= newRaw())

  /** 跑一臂并累加。`mk` 负责给出该臂的 conversation 副本与显著性来源。 */
  async function runArm(key: string, mk: (ci: number, conv: LocomoConversation) => ArmSpec | Promise<ArmSpec>): Promise<void> {
    const a = bump(key)
    for (const ci of mine) {
      const base = convs[ci]
      const gold = goldEvidenceIds(base)
      const { conv, distiller, salienceOf, q, weights } = await mk(ci, base)
      const mem = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients, distiller, { salienceOf, keepFraction: q })
      const m = measureW(mem, base, gold, weights)
      const indep = independentRecall(mem, base, weights)
      for (const k of KS) {
        a.xdiff.push(Math.abs(indep[k] - m.recall[k]))
        a.recall[k].push(m.recall[k])
      }
      a.surv.push(m.evidenceSurvival)
      a.distinct.push(mem.episodes.filter(e => !e.forgotten).length)
      a.pool.push(m.poolSize)
      for (const e of mem.episodes) {
        if (!e.forgotten)
          continue
        if (gold.has(e.id))
          a.prunedGold.push(1)
        else
          a.ages.push(ageFraction(base, e.createdAt))
      }
    }
  }

  /** oracle 显著性：证据 = 1、非证据 = 0（逐条相同，与策略无关）。 */
  const oracleSalience = (gold: Set<string>) => ({ id }: { id: string }) => (gold.has(id) ? 1 : 0)
  const oracleSalienceFactory = oracleSalience

  /**
   * 校验 placebo 臂剪掉的 id 集合与 chrono **逐条相同**。
   *
   * 这是 placebo 成立的前提：若两臂剪掉的不是同一批，测到的差就混入了
   * 「剪掉谁」的差异，顺序效应的上界随之失效。而 `consolidate` 会把证据
   * （salience=1）整体提到排序最前面（`src/store.ts:804`），所以「被剪的是
   * 插入序靠后的那批」这个前提必须**实测**而不能推理——本函数就是那个实测。
   */
  async function assertPlaceboSamePruned(q: number): Promise<{ same: boolean, detail: string }> {
    for (const ci of mine) {
      const conv = convs[ci]
      const oracle = oracleSalienceFactory(goldEvidenceIds(conv))
      const chron = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients, NULL_DISTILLER, { salienceOf: oracle, keepFraction: q })
      const chronPruned = new Set(chron.episodes.filter(e => e.forgotten).map(e => e.id))
      const keep = conv.episodes.filter(e => !chronPruned.has(e.id))
      const drop = conv.episodes.filter(e => chronPruned.has(e.id))
      const eps = [...shuffledCopy(keep, mulberry32(0x5EED + ci)), ...shuffledCopy(drop, mulberry32(0xC0FFEE + ci))]
      const pb = await buildMemory({ ...conv, episodes: eps }, DEFAULT_GATING as GatingCoefficients, NULL_DISTILLER, { salienceOf: oracle, keepFraction: q })
      const pbPruned = new Set(pb.episodes.filter(e => e.forgotten).map(e => e.id))
      const onlyChron = [...chronPruned].filter(id => !pbPruned.has(id))
      const onlyPb = [...pbPruned].filter(id => !chronPruned.has(id))
      if (onlyChron.length || onlyPb.length) {
        return { same: false, detail: `q=${q} conv${ci}: chrono 独有 ${onlyChron.length} 条、placebo 独有 ${onlyPb.length} 条` }
      }
    }
    return { same: true, detail: `q=${q}: 被剪 id 集合与 chrono 逐条相同（本分片 ${mine.length} 个会话全部核对通过）` }
  }

  const total = norecOnly
    ? QS_NOREC.length
    : QS_REPRO.length * 2 + (QS_MECH.length - QS_REPRO.length) + QS_MECH.length * (STRATS.length - 1) + QS_JITTER.length + QS_PLACEBO.length + QS_NOREC.length
  let done = 0
  const tick = (label: string) => {
    done++
    process.stderr.write(`[shard ${shard}] ${done}/${total} ${label} (${new Date().toISOString().slice(11, 19)})\n`)
  }

  if (!norecOnly) {
    for (const q of QS_REPRO) {
      for (const mode of ['dup', 'nofact'] as const) {
        await runArm(`repro|${mode}|${q}`, (_ci, conv) => ({
          conv,
          distiller: mode === 'nofact' ? NULL_DISTILLER : undefined,
          salienceOf: oracleSalience(goldEvidenceIds(conv)),
          q,
        }))
        tick(`repro ${mode} q=${q}`)
      }
    }
  }

  // `mech|chrono` 与 `repro|nofact` 是**同一个计算**（同样本、同样本序、
  // 同 NULL_DISTILLER、同 oracle 显著性、同样 q），只是 `reorderEpisodes`
  // 对 `chrono` 原样返回。Q1 需要 repro 的全q 网格，Q2 需要 mech 的加细网格，
  // 两者在 QS_REPRO 上完全重叠 ⇒ 这里只补跑QS_MECH 里 repro 没有的档
  // （0.98 / 0.95），其余在 merge 阶段直接复用 repro|nofact 的累加器。
  // 这是消除重复计算，不是改口径：被复用的两臂在代码路径上逐字相同。
  if (!norecOnly) {
    const extraMech = QS_MECH.filter(q => !QS_REPRO.includes(q))
    for (const strat of STRATS) {
      for (const q of strat === 'chrono' ? extraMech : QS_MECH) {
        await runArm(`mech|${strat}|${q}`, (ci, conv) => ({
          conv: reorderEpisodes(conv, strat, 0xBEEF + ci),
          distiller: NULL_DISTILLER,
          salienceOf: oracleSalience(goldEvidenceIds(conv)),
          q,
        }))
        tick(`mech ${strat} q=${q}`)
      }
    }

    for (const q of QS_JITTER) {
      await runArm(`mech|salJitter|${q}`, (ci, conv) => {
        const gold = goldEvidenceIds(conv)
        const rnd = mulberry32(0xBEEF + ci)
        const jit = conv.episodes.map(() => rnd() * 0.5)
        const idxOf = new Map(conv.episodes.map((ep, i) => [ep.id, i]))
        return {
          conv,
          distiller: NULL_DISTILLER,
          salienceOf: ({ id }) => {
            const i = idxOf.get(id)
            if (i === undefined)
              return undefined
            return gold.has(id) ? 1 : jit[i]
          },
          q,
        }
      })
      tick(`mech salJitter q=${q}`)
    }
  }

  // placebo：与 chrono 剪掉完全同一批 id，但把留下的项在插入序里随机打乱。
  //
  // 被剪的那批**不能**自己用 `slice(k)` 推算：`consolidate` 先按 salience 降序
  // 排序（src/store.ts:804），证据（salience=1）会被整体提到最前面，
  // 于是真正被剪的是「非证据里插入序靠后的那批」，与原始下标无关。
  // 故这里先真跑一次 chrono，直接读它标出来的 forgotten id——由产品代码定义，
  // 不在本脚本里复刻其排序逻辑（复刻等于把实现抄一遍，日后改动就会静默失配）。
  if (!norecOnly) {
    for (const q of QS_PLACEBO) {
      await runArm(`placebo|${q}`, async (ci, conv) => {
        const gold = goldEvidenceIds(conv)
        const oracle = oracleSalience(gold)
        const chron = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients, NULL_DISTILLER, {
          salienceOf: oracle,
          keepFraction: q,
        })
        const prunedIds = new Set(chron.episodes.filter(e => e.forgotten).map(e => e.id))
        const keep = conv.episodes.filter(e => !prunedIds.has(e.id))
        const drop = conv.episodes.filter(e => prunedIds.has(e.id))
        // 留下的排在前面、被剪的排在后面：稳定排序下 store 会重新挑出同一批 kept。
        // 剪掉的那批全是非证据（证据在 chrono 里排在最前，不会被剪），
        // 且 kept 非证据的条数恰好 = k - |证据|，故 store 会全留 leave、全剪 drop。
        const eps = [...shuffledCopy(keep, mulberry32(0x5EED + ci)), ...shuffledCopy(drop, mulberry32(0xC0FFEE + ci))]
        return {
          conv: { ...conv, episodes: eps },
          distiller: NULL_DISTILLER,
          salienceOf: oracle,
          q,
        }
      })
      tick(`placebo q=${q}`)
    }
  }

  // recency=0 变体：在**同一批 chrono 的 mem** 上只换检索权重重新打分。
  //
  // 关键纪律：`weights` 经 `runArm` 传给 `measureW` / `independentRecall`，
  // 最终只落到 `retrieve()` 的第 4 个参数；剪枝本身（`buildMemory`）照旧按
  // 默认路径跑完。若在这里重新 `buildMemory`，就会多引入一次混淆。
  for (const q of QS_NOREC) {
    await runArm(`norec|chrono|${q}`, (ci, conv) => ({
      conv: reorderEpisodes(conv, 'chrono', 0),
      distiller: NULL_DISTILLER,
      salienceOf: oracleSalience(goldEvidenceIds(conv)),
      q,
      weights: CORRECTED_RETRIEVAL_WEIGHTS,
    }))
    tick(`norec chrono q=${q}`)
  }

  // 前提校验：placebo 必须与 chrono 剪掉同一批 id，否则顺序效应的上界不成立。
  const placeboChecks: { q: number, same: boolean, detail: string }[] = []
  if (!norecOnly) {
    for (const q of QS_PLACEBO) {
      const r = await assertPlaceboSamePruned(q)
      placeboChecks.push({ q, ...r })
      process.stderr.write(`[shard ${shard}] placebo 前提校验 q=${q}: ${r.same ? '✅' : '❌'} ${r.detail}\n`)
    }
  }

  // 复用前提校验：`mech|chrono|q` 在 merge 阶段直接取 `repro|nofact|q` 的值。
  // 这里在**一个**共享档位上把两条路径各跑一遍，确认它们确实逐位相同——
  // 否则「消除重复计算」就变成了「悄悄换口径」。
  const dedupProbe = norecOnly ? undefined : QS_REPRO.find(q => QS_MECH.includes(q))
  const dedupCheck = await (async (): Promise<{ q: number, same: boolean, detail: string } | null> => {
    if (dedupProbe === undefined)
      return null
    const q = dedupProbe
    for (const ci of mine) {
      const conv = convs[ci]
      const oracle = oracleSalienceFactory(goldEvidenceIds(conv))
      const a = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients, NULL_DISTILLER, { salienceOf: oracle, keepFraction: q })
      const b = await buildMemory(reorderEpisodes(conv, 'chrono', 0), DEFAULT_GATING as GatingCoefficients, NULL_DISTILLER, { salienceOf: oracle, keepFraction: q })
      const fa = a.episodes.filter(e => e.forgotten).map(e => e.id).sort().join(',')
      const fb = b.episodes.filter(e => e.forgotten).map(e => e.id).sort().join(',')
      if (fa !== fb)
        return { q, same: false, detail: `conv${ci} 两条路径剪掉的 id 不同` }
    }
    return { q, same: true, detail: `q=${q}: repro|nofact 与 mech|chrono 剪掉的 id 逐条相同（本分片 ${mine.length} 个会话）` }
  })()
  if (dedupCheck)
    process.stderr.write(`[shard ${shard}] 复用前提校验: ${dedupCheck.same ? '✅' : '❌'} ${dedupCheck.detail}\n`)

  mkdirSync(dirname(outPath), { recursive: true })
  writeFileSync(outPath, `${JSON.stringify({
    schema: 'aijade.j5_prune_order_shard@1',
    shard,
    nshards,
    corpus: { path, sha256: sha256File(path), conversations: convs.length },
    convIndices: mine,
    ks: KS,
    grids: { repro: QS_REPRO, mechanism: QS_MECH, jitter: QS_JITTER, placebo: QS_PLACEBO, norec: QS_NOREC },
    placeboChecks,
    dedupCheck,
    raw: acc,
  }, null, 2)}\n`, 'utf8')
  process.stderr.write(`[shard ${shard}] written ${outPath}\n`)
}

// ────────────────────────────── merge ─────────────────────────────────────

interface Summary {
  recall: Record<number, number>
  evidenceSurvival: number
  distinct: number
  poolSize: number
  prunedAge: { count: number, mean: number, median: number, newestDecile: number, newestQuartile: number, oldestQuartile: number }
  prunedGold: number
  crossCheckMaxAbsDiff: number
}

function summarize(r: Raw): Summary {
  const ages = r.ages.slice().sort((a, b) => a - b)
  const frac = (pred: (x: number) => boolean) => (r.ages.length ? r.ages.filter(pred).length / r.ages.length : 0)
  return {
    recall: Object.fromEntries(KS.map(k => [k, avg(r.recall[k])])),
    evidenceSurvival: avg(r.surv),
    distinct: avg(r.distinct),
    poolSize: avg(r.pool),
    prunedAge: {
      count: r.ages.length,
      mean: avg(r.ages),
      median: ages.length ? ages[Math.floor(ages.length / 2)] : 0,
      // age 越小越新，故「最新十分位」= age 落在最小的 10%。
      newestDecile: frac(x => x <= 0.1),
      newestQuartile: frac(x => x <= 0.25),
      oldestQuartile: frac(x => x >= 0.75),
    },
    prunedGold: r.prunedGold.length,
    crossCheckMaxAbsDiff: Math.max(0, ...r.xdiff),
  }
}

async function merge(paths: string[], norecPaths: string[] = []): Promise<void> {
  const shards = paths.map(p => JSON.parse(readFileSync(p, 'utf8')) as {
    corpus: { path: string, sha256: string, conversations: number }
    convIndices: number[]
    grids: { repro: number[], mechanism: number[], jitter: number[], placebo: number[], norec: number[] }
    placeboChecks?: { q: number, same: boolean, detail: string }[]
    dedupCheck?: { q: number, same: boolean, detail: string } | null
    raw: Record<string, Raw>
  })
  const first = shards[0]
  const corpus = first.corpus
  // 网格直接取本脚本的常量，不从分片里读——早期分片是在 norec 臂加入之前写出的，
  // 其 `grids` 字段缺 `norec`，若直接沿用会在报告里漏掉这一节。
  // 常量是唯一的口径来源，分片只提供累加器。
  const grids = { repro: QS_REPRO, mechanism: QS_MECH, jitter: QS_JITTER, placebo: QS_PLACEBO, norec: QS_NOREC }
  for (const s of shards) {
    if (s.corpus.sha256 !== corpus.sha256)
      throw new Error(`分片语料指纹不一致，拒绝合并：${s.corpus.sha256} ≠ ${corpus.sha256}`)
  }
  const seen = new Set<number>()
  for (const s of shards) {
    for (const i of s.convIndices) {
      if (seen.has(i))
        throw new Error(`会话 ${i} 出现在多个分片里，分片划分有重叠`)
      seen.add(i)
    }
  }
  // norec 分片单独成组：它们与主分片**覆盖同一批会话**（同一 q 上只换检索权重），
  // 故不能参与上面的重叠检查，否则会误判为分片划分有误。
  // 但语料指纹仍须一致，否则「只换检索权重」这个前提就不成立。
  const norecShards = norecPaths.map(p => JSON.parse(readFileSync(p, 'utf8')) as {
    corpus: { path: string, sha256: string, conversations: number }
    convIndices: number[]
    raw: Record<string, Raw>
  })
  for (const s of norecShards) {
    if (s.corpus.sha256 !== corpus.sha256)
      throw new Error(`norec 分片语料指纹不一致，拒绝合并：${s.corpus.sha256} ≠ ${corpus.sha256}`)
  }
  const norecSeen = new Set<number>()
  for (const s of norecShards) {
    for (const i of s.convIndices) {
      if (norecSeen.has(i))
        throw new Error(`会话 ${i} 出现在多个 norec 分片里，分片划分有重叠`)
      norecSeen.add(i)
    }
  }
  if (norecShards.length > 0 && norecSeen.size !== corpus.conversations)
    throw new Error(`norec 分片覆盖 ${norecSeen.size} 个会话，应为 ${corpus.conversations}——norec 分片不完整`)
  if (seen.size !== corpus.conversations)
    throw new Error(`分片覆盖 ${seen.size} 个会话，应为 ${corpus.conversations}——分片不完整`)

  // 同一臂的原始累加器直接拼接：每会话权重相等，先拼后均与逐会话求均再平均等价。
  const merged: Record<string, Raw> = {}
  for (const s of shards) {
    for (const [k, r] of Object.entries(s.raw)) {
      const m = merged[k] ??= newRaw()
      for (const kk of KS) m.recall[kk].push(...r.recall[kk])
      m.surv.push(...r.surv)
      m.distinct.push(...r.distinct)
      m.pool.push(...r.pool)
      m.ages.push(...r.ages)
      m.prunedGold.push(...r.prunedGold)
      m.xdiff.push(...r.xdiff)
    }
  }
  // norec 分片的累加器按臂名直接并入（臂名前缀 `norec|`，与主分片不重名）。
  for (const s of norecShards) {
    for (const [k, r] of Object.entries(s.raw)) {
      const m = merged[k] ??= newRaw()
      for (const kk of KS) m.recall[kk].push(...r.recall[kk])
      m.surv.push(...r.surv)
      m.distinct.push(...r.distinct)
      m.pool.push(...r.pool)
      m.ages.push(...r.ages)
      m.prunedGold.push(...r.prunedGold)
      m.xdiff.push(...r.xdiff)
    }
  }
  const S: Record<string, Summary> = Object.fromEntries(Object.entries(merged).map(([k, r]) => [k, summarize(r)]))

  // `mech|chrono|q` 只跑了 QS_MECH 里 repro 没有的档；其余档位直接复用
  // `repro|nofact|q` —— 两者是同一个计算（见 collect 阶段的说明）。
  for (const q of grids.repro) {
    const src = S[`repro|nofact|${q}`]
    if (src)
      S[`mech|chrono|${q}`] = src
  }

  const L: string[] = []
  const say = (s = '') => L.push(s)
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`

  say('=== 判定性对照：池规模 vs 剪枝顺序（缺陷 C 的真实归因）===')
  say(`corpus : ${corpus.path}`)
  say(`sha256 : ${corpus.sha256}`)
  say(`convs  : ${corpus.conversations}`)
  say()

  // ── Q1 ──
  say('--- Q1 复现：oracle 显著性，chrono 插入序（= 现有行为）---')
  say(`  ${'arm'.padEnd(14)}${'poolSize'.padStart(10)}${'distinct'.padStart(10)}${'evSurv'.padStart(9)}${'R@8'.padStart(9)}`)
  const repro: Record<string, Summary> = {}
  for (const q of grids.repro) {
    for (const mode of ['dup', 'nofact'] as const) {
      const s = S[`repro|${mode}|${q}`]
      repro[`${mode}-${q}`] = s
      say(`  ${`${mode} q=${q}`.padEnd(14)}${s.poolSize.toFixed(1).padStart(10)}${s.distinct.toFixed(1).padStart(10)}${s.evidenceSurvival.toFixed(4).padStart(9)}${s.recall[MAXK].toFixed(4).padStart(9)}`)
    }
  }
  say()

  // 与已归档产物逐位比对
  const archivedPath = join(dirname(new URL(import.meta.url).pathname), 'results', 'p2-index-duplication-confusion-2026-09-15.json')
  const q1: string[] = []
  if (existsSync(archivedPath)) {
    const arch = JSON.parse(readFileSync(archivedPath, 'utf8')) as { arms: Record<string, { poolSize: number, recall: Record<string, number> }> }
    q1.push('【Q1 逐位比对：本次复现 vs p2-index-duplication-confusion-2026-09-15.json】')
    let allMatch = true
    for (const q of grids.repro) {
      for (const mode of ['dup', 'nofact'] as const) {
        const a = arch.arms[`oracle-q${q}-${mode}`]
        const b = repro[`${mode}-${q}`]
        if (!a) {
          q1.push(`  oracle-q${q}-${mode}: 归档产物缺此臂`)
          allMatch = false
          continue
        }
        const dPool = b.poolSize - a.poolSize
        const dR = b.recall[MAXK] - a.recall[String(MAXK)]
        const ok = Math.abs(dPool) < 5e-4 && Math.abs(dR) < 5e-4
        if (!ok)
          allMatch = false
        q1.push(`  ${`oracle-q${q}-${mode}`.padEnd(20)} pool ${b.poolSize.toFixed(4)} vs ${a.poolSize.toFixed(4)} (Δ${dPool >= 0 ? '+' : ''}${dPool.toFixed(4)})   R@8 ${b.recall[MAXK].toFixed(4)} vs ${a.recall[String(MAXK)].toFixed(4)} (Δ${fmt(dR)})  ${ok ? '✅' : '❌'}`)
      }
    }
    q1.push(`  ⇒ ${allMatch ? '**Q1 逐位一致**，复现可信。' : '⚠️ 存在不一致，须停下排查。'}`)
  }
  else {
    q1.push('【Q1】未找到归档产物，无法逐位比对。')
  }
  say(...q1)
  say()

  // ── Q2/Q3 ──
  say('--- Q2/Q3：池规模固定，只改剪掉谁（空蒸馏器，salience 逐条相同）---')
  say(`  ${'strategy'.padEnd(12)}${'q'.padStart(6)}${'distinct'.padStart(10)}${'pool'.padStart(9)}${'evSurv'.padStart(9)}${'R@8'.padStart(9)}${'ΔR@8 vs q=1'.padStart(14)}`)
  const mech: Record<string, Summary> = {}
  for (const strat of [...STRATS, 'salJitter']) {
    for (const q of grids.mechanism) {
      if (strat === 'salJitter' && !grids.jitter.includes(q))
        continue
      const s = S[`mech|${strat}|${q}`]
      mech[`${strat}|${q}`] = s
      const d = q === 1 ? Number.NaN : mech[`${strat}|1`].recall[MAXK] - s.recall[MAXK]
      say(`  ${strat.padEnd(12)}${String(q).padStart(6)}${s.distinct.toFixed(1).padStart(10)}${s.poolSize.toFixed(1).padStart(9)}${s.evidenceSurvival.toFixed(4).padStart(9)}${s.recall[MAXK].toFixed(4).padStart(9)}${(Number.isNaN(d) ? '' : fmt(d)).padStart(14)}`)
    }
  }
  say()

  say('--- 机制判决：recency=0 是否消除 q=1→0.9 断崖（同一批 mem，只换检索权重）---')
  for (const q of grids.norec) {
    const a = S[`mech|chrono|${q}`]
    const b = S[`norec|chrono|${q}`]
    if (!a || !b)
      continue
    say(`  q=${q}: 默认权重 R@8 ${a.recall[MAXK].toFixed(4)} → recency=0 R@8 ${b.recall[MAXK].toFixed(4)}（Δ ${fmt(b.recall[MAXK] - a.recall[MAXK])}）`)
  }
  {
    const d1 = S['mech|chrono|1']
    const d9 = S['mech|chrono|0.9']
    const n1 = S['norec|chrono|1']
    const n9 = S['norec|chrono|0.9']
    if (d1 && d9 && n1 && n9) {
      const jumpDefault = d9.recall[MAXK] - d1.recall[MAXK]
      const jumpNoRec = n9.recall[MAXK] - n1.recall[MAXK]
      say(`  ⇒ 断崖幅度：默认 ${fmt(jumpDefault)} vs recency=0 ${fmt(jumpNoRec)}（比值 ${(jumpNoRec / jumpDefault).toFixed(3)}）`)
    }
  }
  say()

  say('--- Q3：被剪项的年龄分布（0 = 最新，1 = 最老）---')
  say(`  ${'strategy'.padEnd(12)}${'q'.padStart(6)}${'nPruned非证据'.padStart(14)}${'meanAge'.padStart(9)}${'medAge'.padStart(9)}${'最新10%'.padStart(10)}${'最新25%'.padStart(10)}${'最老25%'.padStart(10)}${'剪掉证据数'.padStart(12)}`)
  for (const strat of [...STRATS, 'salJitter']) {
    for (const q of grids.mechanism) {
      if (q === 1 || !(`${strat}|${q}` in mech))
        continue
      const g = mech[`${strat}|${q}`].prunedAge
      say(`  ${strat.padEnd(12)}${String(q).padStart(6)}${String(g.count).padStart(14)}${g.mean.toFixed(3).padStart(9)}${g.median.toFixed(3).padStart(9)}${(g.newestDecile * 100).toFixed(1).padStart(10)}${(g.newestQuartile * 100).toFixed(1).padStart(10)}${(g.oldestQuartile * 100).toFixed(1).padStart(10)}${String(mech[`${strat}|${q}`].prunedGold).padStart(12)}`)
    }
  }
  say()

  say('--- 残余差异量化：池成员相同、仅池内顺序打乱（placebo vs chrono）---')
  for (const q of grids.placebo) {
    const p = S[`placebo|${q}`]
    const c = mech[`chrono|${q}`]
    say(`  q=${q}: chrono R@8 ${c.recall[MAXK].toFixed(4)}（distinct ${c.distinct.toFixed(1)}） vs 同池乱序 ${p.recall[MAXK].toFixed(4)}（distinct ${p.distinct.toFixed(1)}） ⇒ 池内顺序效应 ${fmt(p.recall[MAXK] - c.recall[MAXK])}`)
  }
  const checks = shards.flatMap(s => s.placeboChecks ?? [])
  if (checks.length) {
    say()
    say('  前提校验（placebo 剪掉的 id 是否与 chrono 逐条相同）：')
    for (const q of grids.placebo) {
      const cs = checks.filter(c => c.q === q)
      const ok = cs.length > 0 && cs.every(c => c.same)
      say(`    q=${q}: ${ok ? '✅' : '❌'} ${cs.map(c => c.detail).join('；')}`)
    }
  }
  const dedup = shards.map(s => s.dedupCheck).filter((d): d is { q: number, same: boolean, detail: string } => !!d)
  if (dedup.length) {
    say()
    say('  复用前提校验（`mech|chrono` 直接复用 `repro|nofact` 的计算）：')
    for (const d of dedup)
      say(`    ${d.same ? '✅' : '❌'} ${d.detail}`)
  }
  say()

  // ── 交叉校验 ──
  const maxXdiff = Math.max(0, ...Object.values(S).map(s => s.crossCheckMaxAbsDiff))
  say('--- recall 实现交叉校验（independentRecall vs measure）---')
  say(`  全部 ${Object.keys(S).length} 臂的最大绝对偏差 = ${maxXdiff.toFixed(6)}${maxXdiff === 0 ? '（完全一致）' : '（不一致，须排查）'}`)
  say()

  // ── 判读 ──
  const V: string[] = []
  V.push('【判据 1】池规模是否在策略间严格固定')
  let spreadAll = 0
  for (const q of grids.mechanism) {
    const ds = STRATS.map(s => mech[`${s}|${q}`].distinct)
    const spread = Math.max(...ds) - Math.min(...ds)
    spreadAll = Math.max(spreadAll, spread)
    V.push(`  q=${q}: distinct = ${ds.map(d => d.toFixed(1)).join(' / ')} ⇒ 跨策略极差 ${spread.toFixed(4)}`)
  }
  V.push(`  ⇒ 全部 q 的跨策略极差最大值 = ${spreadAll.toFixed(4)}`)
  V.push(`  ${spreadAll < 1e-6
    ? '**池规模被严格固定**（`k` 只由条数 × q 决定，见 src/store.ts:803）⇒「池子大小」这一维度在本路径上已被结构性消除。'
    : '⚠️ 池规模未被固定，策略间混入了规模差异，须在结论中声明。'}`)
  V.push('')

  V.push('【判据 2】q=1 → q=0.9 一步的 recall@8 跳变（池规模相同，只差剪掉谁）')
  const jump: Record<string, number> = {}
  for (const strat of [...STRATS, 'salJitter']) {
    jump[strat] = mech[`${strat}|1`].recall[MAXK] - mech[`${strat}|0.9`].recall[MAXK]
    V.push(`  ${strat.padEnd(10)} ${mech[`${strat}|1`].recall[MAXK].toFixed(4)} → ${mech[`${strat}|0.9`].recall[MAXK].toFixed(4)}   跳变 ${fmt(jump[strat])}`)
  }
  V.push('')

  V.push('【判据 2b】q=1 附近加细（判断是连续量变还是台阶）')
  for (const strat of STRATS) {
    V.push(`  ${strat.padEnd(10)} ${grids.mechanism.filter(q => q >= 0.9).map(q => `q=${q}: ${mech[`${strat}|${q}`].recall[MAXK].toFixed(4)}`).join('  ')}`)
  }
  V.push('')

  V.push('【判据 3】被剪项的年龄分布（0 = 最新）')
  for (const strat of STRATS) {
    const g = mech[`${strat}|0.9`].prunedAge
    V.push(`  ${strat.padEnd(10)} q=0.9：被剪非证据 ${g.count} 条，平均年龄 ${g.mean.toFixed(3)}，中位 ${g.median.toFixed(3)}，最新 10% 占 ${(g.newestDecile * 100).toFixed(1)}%，最新 25% 占 ${(g.newestQuartile * 100).toFixed(1)}%，最老 25% 占 ${(g.oldestQuartile * 100).toFixed(1)}%`)
  }
  V.push('')

  V.push('【判据 4】旧口径（改 salience 数值破并列） vs 本脚本（只改插入序）')
  for (const q of grids.jitter.filter(q => q !== 1)) {
    V.push(`  q=${q}: salJitter R@8 ${mech[`salJitter|${q}`].recall[MAXK].toFixed(4)} vs shuffled R@8 ${mech[`shuffled|${q}`].recall[MAXK].toFixed(4)} ⇒ 差 ${fmt(mech[`salJitter|${q}`].recall[MAXK] - mech[`shuffled|${q}`].recall[MAXK])}`)
  }
  V.push('  ⇒ 该差即 durability/decay 混淆的量级；`diag-oracle-tiebreak.ts` 把它一并算进了「剪枝顺序」。')
  V.push('')

  V.push('【判据 5】最终判读')
  const chronoJump = jump.chrono
  const lifoJump = jump.lifo
  const shufJump = jump.shuffled
  const cAge = mech['chrono|0.9'].prunedAge
  const lAge = mech['lifo|0.9'].prunedAge
  const sAge = mech['shuffled|0.9'].prunedAge
  if (Math.abs(chronoJump) > 0.05 && Math.abs(lifoJump) < Math.abs(chronoJump) / 2) {
    V.push(`  · chrono（剪掉最近）跳 ${fmt(chronoJump)}；lifo（剪掉最老）跳 ${fmt(lifoJump)}；shuffled（随机）跳 ${fmt(shufJump)}。`)
    V.push(`  · 三者池规模逐条相同 ⇒ 跳变**不能**归因于池子大小。`)
    V.push(`  · 被剪项年龄：chrono 平均 ${cAge.mean.toFixed(3)}（最新 10% 占 ${(cAge.newestDecile * 100).toFixed(1)}%）、`)
    V.push(`    lifo 平均 ${lAge.mean.toFixed(3)}（最老 25% 占 ${(lAge.oldestQuartile * 100).toFixed(1)}%）、shuffled 平均 ${sAge.mean.toFixed(3)}（最新 10% 占 ${(sAge.newestDecile * 100).toFixed(1)}%）`)
    V.push('  ⇒ 跳变量与「剪掉的是不是最近那批」单调对应，与池规模无关。')
  }
  else {
    V.push(`  · chrono 跳 ${fmt(chronoJump)}，lifo 跳 ${fmt(lifoJump)}，shuffled 跳 ${fmt(shufJump)}——未出现「剪掉谁」主导的分离。`)
    V.push('  ⇒ 须按实测数字重新判读，不得沿用任何现成说法。')
  }

  const verdicts = [...q1, '', ...V]
  say('--- 判读（本段由上方实测数字生成，无硬编码结论）---')
  say(...verdicts)

  // ── 产物 ──
  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })
  const jsonPath = join(outDir, `j5-prune-order-mechanism-${stamp}.json`)
  writeFileSync(jsonPath, `${JSON.stringify(withProvenance({
    generatedAt: new Date().toISOString(),
    corpus,
    ks: KS,
    grids,
    design: {
      poolControl: 'k = max(1, min(pending.length, round(pending.length * q))) 只依赖条数与 q（src/store.ts:803）⇒ 同 q 下池规模与显著性数值无关地被固定',
      tiebreakMechanism: '只改 conv.episodes 的插入顺序（V8 sort 稳定 ⇒ 并列按插入序决胜），salience 逐条相同（证据=1/非证据=0）⇒ durability/decay/检索分公式完全一致',
      confoundAvoided: 'salJitter 臂沿用旧口径（改 salience 数值），会经 durability（src/store.ts:261）与 decay（src/forgetting.ts:34）污染「留下的项有多强」，故单列以量化其量级',
      residual: 'placebo 臂：与 chrono 剪掉同一批 id、仅池内顺序不同 ⇒ 其与 chrono 的差即池内顺序效应的上界',
      q4: 'q=1 与 q<1 走同一条 keepFraction 代码路径（src/store.ts:802-806），无特例分支；k=round(N·q) 是q 的连续函数',
    },
    crossCheck: { maxAbsDiffRecall: maxXdiff, note: 'independentRecall（retrieve(q,9999) 全量名次） vs eval-metrics.measure（retrieve(q,8) 位置还原）' },
    poolSizeSpreadAcrossStrategies: spreadAll,
    arms: {
      repro: Object.fromEntries(Object.entries(repro).map(([k, v]) => [k, { ...v, label: `Q1 复现 ${k}` }])),
      mechanism: Object.fromEntries(Object.entries(mech).map(([k, v]) => [k.split('|'), { ...v, label: `Q2/Q3 ${k}` }])),
      placebo: Object.fromEntries(grids.placebo.map(q => [String(q), { ...S[`placebo|${q}`], label: `Q2 残余 placebo q=${q}` }])),
      norec: Object.fromEntries(grids.norec.map(q => [`chrono|${q}`, { ...S[`norec|chrono|${q}`], label: `机制判决 recency=0 chrono q=${q}` }])),
    },
    verdicts,
  }), null, 2)}\n`, 'utf8')

  const text = `${L.join('\n')}\n`
  process.stdout.write(text)
  mkdirSync(outDir, { recursive: true })
  const logPath = join(outDir, `j5-prune-order-mechanism-${stamp}.run.log`)
  writeFileSync(logPath, text, 'utf8')
  process.stderr.write(`artifact: ${jsonPath}\nlog: ${logPath}\n`)
}

// ─────────────────────────────── 入口 ─────────────────────────────────────

const mode = process.argv[2]

/** 入口包一层函数以避开 top-level await（lint 规则 `antfu/no-top-level-await`）。 */
async function main(): Promise<void> {
  if (mode === 'collect') {
    await collect(Number(process.argv[3]), Number(process.argv[4]), process.argv[5], process.argv[6], process.argv[7], process.argv[8])
  }
  else if (mode === 'merge') {
    // norec 分片是可选的第二个分组（`--norec a.json b.json ...`），跑在主分片之后。
    const rest = process.argv.slice(3)
    const cut = rest.indexOf('--norec')
    const main = cut === -1 ? rest : rest.slice(0, cut)
    const norec = cut === -1 ? [] : rest.slice(cut + 1)
    await merge(main, norec)
  }
  else {
    console.error('用法：')
    console.error('  collect <shard> <nshards> <out.json> [corpus-path|-] [conv-limit|-] [only|norec]')
    console.error('  merge <shard.json>... [--norec <norec-shard.json>...]')
    process.exitCode = 1
  }
}

main().catch((err: unknown) => {
  console.error(err)
  process.exitCode = 1
})
