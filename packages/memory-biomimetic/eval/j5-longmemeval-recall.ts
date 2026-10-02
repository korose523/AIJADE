import type { BioticMemory, RetrievalWeights } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'

/**
 * J5 / P4 —— 第二语料复现：LongMemEval 上的 recall@K / MRR / NDCG@K 三臂对照。
 * J5（《检索打分量纲失配》）与 P4（英文版）的核心结论目前**只建立在 LoCoMo 一个语料
 * （10 段对话）上**，这是论文自己声明的首要效度威胁。本脚本在 LongMemEval
 * （500 题、6 种 question_type）上重跑同一组三臂对照，检验的是那个**定性顺序**：
 *
 *      recency 抑制（no-recency） ≫ 现状（current）
 *
 * 注意要检验的是**顺序**，不是数值相等：两个语料的粒度、难度、证据标注方式都不同，
 * recall@K 的绝对值必然不同。若顺序不一致，那是一个真实且重要的跨语料局限，
 * 必须照实写进论文，而不是把数字调成 LoCoMo 的样子。
 *
 * ── 三臂 ──────────────────────────────────────────────────────────────────
 *   current     DEFAULT_RETRIEVAL_WEIGHTS            （现状）
 *   sim-only    仅 similarity，其余置 0               （相关性上界参照）
 *   no-recency  CORRECTED_RETRIEVAL_WEIGHTS（recency=0）（J5 的修正权重）
 *
 * 三臂共用**同一个已建好的记忆实例**，只在 `retrieve()` 的 weights 入参上不同
 * （`BioticMemory.retrieve` 支持 per-call 权重覆盖，不改动 store 配置）。
 * 因此三臂之间的差异**只**来自打分权重，不含建记忆/巩固的随机性。
 *
 * ── 指标口径（全部在此显式定义，避免"数字归属不明"）────────────────────────
 *   recall@K ：金标准证据会话（或其 fact_ 变体）出现在 top-K **且** score > retrievalFloor。
 *              floor 条件与 `src/locomo.ts::evidenceRecall` 完全一致。
 *   MRR      ：1 / 首个命中候选的排名；无命中记 0。命中同样要求 score > floor。
 *   NDCG@K   ：二元相关性（命中=1）。DCG = Σ_{命中位置 r≤K} 1/log2(r+1)；
 *              IDCG = Σ_{i=1..min(R,K)} 1/log2(i+1)，R = 该记忆池中**未被遗忘**的
 *              金标准会话数。LongMemEval 官方 NDCG 用的是分级相关性，这里只有二元
 *              标注（answer_session_ids），故为二元 NDCG —— 这是**口径差异**，不是同一量。
 *
 * ── 用法 ──────────────────────────────────────────────────────────────────
 *   tsx eval/j5-longmemeval-recall.ts                 # 全量 500 题
 *   tsx eval/j5-longmemeval-recall.ts --limit 20      # 确定性抽样 20 题（先探耗时）
 *   tsx eval/j5-longmemeval-recall.ts --seed 1        # 换抽样种子
 *   tsx eval/j5-longmemeval-recall.ts --no-verify     # 跳过指纹校验（仅探索；产物不可用）
 *
 * 产物：eval/results/j5-longmemeval-recall.json（含 withProvenance 溯源块）
 */
import {
  buildExperimentManifest,
  buildMemory,
  CORRECTED_RETRIEVAL_WEIGHTS,
  DEFAULT_GATING,
  DEFAULT_RETRIEVAL_WEIGHTS,
} from '../src/index'
import { runProvenance, withProvenance } from './artifact-provenance'
import { parseLongMemEval, sampleItems } from './longmemeval-adapter'
import { loadLongMemEvalVerified } from './longmemeval-path'

const KS = [1, 2, 4, 8]
const MAX_K = Math.max(...KS)

/** 仅保留 similarity 项：把其余三项置 0，得到一个"纯相关性"参照臂。 */
const SIM_ONLY_WEIGHTS: RetrievalWeights = {
  similarity: 1,
  strength: 0,
  recency: 0,
  context: 0,
  affect: 0,
}

interface ArmSpec {
  name: 'current' | 'sim-only' | 'no-recency'
  description: string
  weights: RetrievalWeights
}

const ARMS: ArmSpec[] = [
  { name: 'current', description: 'DEFAULT_RETRIEVAL_WEIGHTS（现状）', weights: DEFAULT_RETRIEVAL_WEIGHTS },
  { name: 'sim-only', description: '仅 similarity（相关性上界参照）', weights: SIM_ONLY_WEIGHTS },
  { name: 'no-recency', description: 'CORRECTED_RETRIEVAL_WEIGHTS（recency=0，J5 修正权重）', weights: CORRECTED_RETRIEVAL_WEIGHTS },
]

/**
 * LoCoMo 侧的 recall@K 参考值，**仅用于判断装置是否自洽**。
 * 两个语料不可比：LoCoMo 是 10 段对话、按 turn（dia_id）编码、category 1–5；
 * LongMemEval 是 500 题各自独立 haystack、按 session 编码。
 * 这里写进产物只是为了让"我们看过 LoCoMo 是多少"这件事可核查。
 */
const LOCOMO_REFERENCE = { 'current': 0.0906, 'sim-only': 0.3580, 'no-recency': 0.3046 }

interface PerQuestion {
  questionId: string
  questionType: string
  /** 每个臂：首个命中排名（1-based；0 = 未命中）。 */
  firstHitRank: Record<string, number>
  /** 每个臂：召回到的金标准会话数 / 池中金标准会话总数。 */
  recall: Record<string, Record<number, number>>
  mrr: Record<string, number>
  ndcg: Record<string, Record<number, number>>
}

function idcg(r: number, k: number): number {
  let s = 0
  for (let i = 1; i <= Math.min(r, k); i++)
    s += 1 / Math.log2(i + 1)
  return s
}

/**
 * 对一题、一个臂打分。
 * `ranking` 是 `retrieve(q, MAX_K, false, weights)` 的结果；`retrieve` 对全池打分后截断，
 * 且打分页宽与 K 无关（见 `eval-metrics.ts` 的说明），故 top-K 即该排序的前 K 项。
 */
function scoreOne(
  ranking: { id: string, score: number }[],
  goldIds: Set<string>,
  relevantTotal: number,
  floor: number,
): { firstHitRank: number, recallAtK: Record<number, number>, mrr: number, ndcg: Record<number, number> } {
  const hitRanks: number[] = []
  ranking.forEach((c, i) => {
    if (goldIds.has(c.id) && c.score > floor)
      hitRanks.push(i + 1)
  })

  const firstHitRank = hitRanks.length ? hitRanks[0] : 0
  const recallAtK: Record<number, number> = {}
  const ndcg: Record<number, number> = {}
  for (const k of KS) {
    recallAtK[k] = firstHitRank > 0 && firstHitRank <= k ? 1 : 0
    let dcg = 0
    for (const r of hitRanks) {
      if (r <= k)
        dcg += 1 / Math.log2(r + 1)
    }
    const ideal = idcg(relevantTotal, k)
    ndcg[k] = ideal > 0 ? dcg / ideal : 0
  }
  const mrr = firstHitRank > 0 ? 1 / firstHitRank : 0
  return { firstHitRank, recallAtK, mrr, ndcg }
}

async function main(): Promise<void> {
  const argv = process.argv.slice(2)
  const limitArg = argv.indexOf('--limit')
  const limit = limitArg >= 0 && argv[limitArg + 1] ? Number(argv[limitArg + 1]) : undefined
  const seedArg = argv.indexOf('--seed')
  const seed = seedArg >= 0 && argv[seedArg + 1] ? Number(argv[seedArg + 1]) : 0
  const noVerify = argv.includes('--no-verify')
  const cliPath = argv.find(a => !a.startsWith('--') && a !== String(limit) && a !== String(seed))

  const m = buildExperimentManifest({
    id: 'j5-longmemeval-recall',
    name: 'J5/P4: cross-corpus replication of the recency-suppression effect on LongMemEval (recall@K, MRR, NDCG@K)',
    seed,
    conditions: ARMS.map(a => ({ name: a.name, description: a.description, params: { weights: a.weights } })),
    metrics: ['recall@1', 'recall@2', 'recall@4', 'recall@8', 'MRR', 'NDCG@1', 'NDCG@2', 'NDCG@4', 'NDCG@8'],
    notes: 'Second corpus for the J5 single-corpus validity threat. LongMemEvalS (cleaned, HF, MIT), 500 items, session-level episodes. Three arms share one built memory per item and differ only in retrieval weights. Abstention: none present in the cleaned release — no items excluded. Not self-registered in experiments.registry.json (concurrent-write; registered by the owner).',
  })
  // 刻意**不**调用 registerExperimentManifest：本脚本由并发编辑者负责登记，
  // 自己写 experiments.registry.json 会造成并发写冲突。
  console.info(`experiment manifest built: ${m.schema} ${m.id}@${m.version} (seed ${seed}, ${m.conditions.length} conditions) — 未自行写入注册表`)
  console.info()

  const loaded = loadLongMemEvalVerified(cliPath, { verifyChecksum: !noVerify })
  console.info('=== J5 / P4 第二语料复现：LongMemEval ===')
  console.info(`语料路径     : ${loaded.path}  (来源: ${loaded.source})`)
  console.info(`字节数       : ${loaded.bytes}`)
  console.info(`sha256       : ${loaded.sha256}`)
  console.info(`指纹校验     : ${loaded.checksumMatches ? '通过 ✅' : '未校验/未通过 ⚠️（--no-verify）—— 该产物不可用于论文数字'}`)
  console.info(`原始题数     : ${loaded.data.length}`)

  const parsed = parseLongMemEval(loaded.data)
  console.info(`题型分布     : ${JSON.stringify(parsed.typeCounts)}`)
  console.info(`能力项分布   : ${JSON.stringify(parsed.abilityCounts)}`)
  console.info(`悬空证据题数 : ${parsed.itemsWithDanglingEvidence}  (answer_session_ids 不在 haystack 中的题目数，应为 0)`)
  console.info(`时间解析失败 : 会话 ${parsed.itemsWithUnparsedDates} 题 / 提问时刻 ${parsed.itemsWithUnparsedQuestionDate} 题（应为 0）`)
  console.info(`未知题型     : ${parsed.unknownTypes.length ? parsed.unknownTypes.join(', ') : '（无）'}`)

  const subset = limit ? sampleItems(parsed.items, limit, seed) : parsed.items
  console.info(`参与评测题数 : ${subset.length}${limit ? `  (确定性抽样 seed=${seed})` : '  (全量)'}`)
  console.info()

  const perQuestion: PerQuestion[] = []
  /** 检索下限（DEFAULT_MEMORY_CONFIG.retrievalFloor）—— 写进产物，它是 recall@K 口径的一部分。 */
  let lastFloor: number | null = null
  const started = Date.now()

  for (let i = 0; i < subset.length; i++) {
    const { conv, item } = subset[i]
    const mem: BioticMemory = await buildMemory(conv, DEFAULT_GATING)
    const floor = mem.config.retrievalFloor
    lastFloor = floor

    const goldIds = new Set<string>()
    for (const id of conv.evidenceIds) {
      goldIds.add(id)
      goldIds.add(`fact_${id}`)
    }
    // 池中仍可检索的金标准会话数 —— NDCG 的 IDCG 分母。
    const relevantTotal = mem.episodes.filter(e => !e.forgotten && conv.evidenceIds.has(e.id)).length

    const q = conv.qa[0]
    const rec: PerQuestion = {
      questionId: item.question_id,
      questionType: item.question_type,
      firstHitRank: {},
      recall: {},
      mrr: {},
      ndcg: {},
    }
    for (const arm of ARMS) {
      const ranking = mem.retrieve(q.question, MAX_K, false, arm.weights)
      const s = scoreOne(ranking, goldIds, relevantTotal, floor)
      rec.firstHitRank[arm.name] = s.firstHitRank
      rec.recall[arm.name] = s.recallAtK
      rec.mrr[arm.name] = s.mrr
      rec.ndcg[arm.name] = s.ndcg
    }
    perQuestion.push(rec)

    if ((i + 1) % 10 === 0 || i === subset.length - 1) {
      const elapsed = (Date.now() - started) / 1000
      const eta = (elapsed / (i + 1)) * (subset.length - i - 1)
      console.info(`  [${i + 1}/${subset.length}] 已用 ${elapsed.toFixed(1)}s，预计剩余 ${eta.toFixed(1)}s`)
    }
  }

  const n = perQuestion.length
  const mean = (f: (p: PerQuestion) => number): number => (n ? perQuestion.reduce((s, p) => s + f(p), 0) / n : 0)

  const armSummary: Record<string, {
    recall: Record<number, number>
    mrr: number
    ndcg: Record<number, number>
    weights: RetrievalWeights
    provenance: ReturnType<typeof runProvenance>
  }> = {}

  console.info()
  console.info(`=== 三臂结果（n = ${n} 题，每题一个独立 haystack）===`)
  console.info(`arm          ${KS.map(k => `recall@${k}`.padStart(10)).join('')}       MRR${KS.map(k => `ndcg@${k}`.padStart(10)).join('')}`)
  for (const arm of ARMS) {
    const recall: Record<number, number> = {}
    const ndcg: Record<number, number> = {}
    for (const k of KS) {
      recall[k] = mean(p => p.recall[arm.name][k])
      ndcg[k] = mean(p => p.ndcg[arm.name][k])
    }
    const mrr = mean(p => p.mrr[arm.name])
    armSummary[arm.name] = {
      recall,
      mrr,
      ndcg,
      weights: { ...arm.weights },
      provenance: runProvenance({ weights: arm.weights }),
    }
    console.info(
      arm.name.padEnd(13)
      + KS.map(k => recall[k].toFixed(4).padStart(10)).join('')
      + mrr.toFixed(4).padStart(10)
      + KS.map(k => ndcg[k].toFixed(4).padStart(10)).join(''),
    )
  }

  // ── 按题型拆分（只看 recall@8，避免刷屏）─────────────────────────────────
  const byType: Record<string, Record<string, number>> = {}
  const types = [...new Set(perQuestion.map(p => p.questionType))].sort()
  console.info()
  console.info('=== 分题型 recall@8 ===')
  console.info(`question_type               n   ${ARMS.map(a => a.name.padStart(12)).join('')}`)
  for (const t of types) {
    const sub = perQuestion.filter(p => p.questionType === t)
    byType[t] = { n: sub.length }
    const cells: string[] = []
    for (const arm of ARMS) {
      const v = sub.reduce((s, p) => s + p.recall[arm.name][8], 0) / sub.length
      byType[t][arm.name] = v
      cells.push(v.toFixed(4).padStart(12))
    }
    console.info(`${t.padEnd(28) + String(sub.length).padStart(3)}   ${cells.join('')}`)
  }

  // ── 定性顺序检验（这是本脚本真正要回答的问题）────────────────────────────
  //
  // **对全部 K 逐个报告，而不是只报一个 K。** 理由：LongMemEval_S 每题的候选池只有
  // 约 40–60 个 session，远小于 LoCoMo 的一个对话（数千轮），所以 recall@K 在大 K 上
  // 会**触顶**（各臂同 =1.0000），触顶处的差距恒为 0，看不出任何顺序。
  // 只报 K=8 会把"触顶"误读成"没有效应"；只报 K=1 又等于挑最有利的一个 K。
  // 因此把四个 K 全部列出，并把"是否复现"按 K 分别给出，由读者自行判断。
  const perKGaps: Record<number, { current: number, simOnly: number, noRecency: number, gapSimOnly: number, gapNoRecency: number, replicates: boolean, saturated: boolean }> = {}
  for (const k of KS) {
    const c = armSummary.current.recall[k]
    const s = armSummary['sim-only'].recall[k]
    const nr = armSummary['no-recency'].recall[k]
    perKGaps[k] = {
      current: c,
      simOnly: s,
      noRecency: nr,
      gapSimOnly: s - c,
      gapNoRecency: nr - c,
      replicates: (s - c) > 0 && (nr - c) > 0,
      // 触顶判据：三臂全部 ≥ 0.999 ⇒ 该 K 上指标已无分辨力。
      saturated: c >= 0.999 && s >= 0.999 && nr >= 0.999,
    }
  }
  const unsaturated = KS.filter(k => !perKGaps[k].saturated)
  const replicatesAllUnsaturated = unsaturated.length > 0 && unsaturated.every(k => perKGaps[k].replicates)
  const replicatesAny = KS.some(k => perKGaps[k].replicates)

  console.info()
  console.info('=== 定性顺序检验（逐个 K 报告）===')
  console.info(`LoCoMo 侧参考值（不同语料，仅作装置自洽性参照，不可直接比较）：`)
  console.info(`  current=${LOCOMO_REFERENCE.current}  sim-only=${LOCOMO_REFERENCE['sim-only']}  no-recency=${LOCOMO_REFERENCE['no-recency']}`)
  console.info()
  console.info('   K    current   sim-only  no-recency   Δ(sim−cur)  Δ(noRec−cur)  复现?   触顶?')
  for (const k of KS) {
    const g = perKGaps[k]
    console.info(
      `  ${String(k).padStart(2)}   ${g.current.toFixed(4)}    ${g.simOnly.toFixed(4)}     ${g.noRecency.toFixed(4)}     `
      + `${(g.gapSimOnly >= 0 ? '+' : '')}${g.gapSimOnly.toFixed(4)}     ${(g.gapNoRecency >= 0 ? '+' : '')}${g.gapNoRecency.toFixed(4)}     `
      + `${g.replicates ? '是' : '否'}      ${g.saturated ? '是' : '否'}`,
    )
  }
  console.info()
  if (unsaturated.length === 0) {
    console.info('  ⇒ **四个 K 全部触顶**：该语料在此指标上对本操纵**没有分辨力**，既不能说复现也不能说未复现。')
  }
  else if (replicatesAllUnsaturated) {
    console.info(`  ⇒ 在未触顶的 K（${unsaturated.join(', ')}）上两臂均高于 current：**定性顺序（recency 抑制 ≫ 现状）复现**。`
      + `（触顶的 K：${KS.filter(k => perKGaps[k].saturated).join(', ') || '无'}）`)
  }
  else if (replicatesAny) {
    console.info(`  ⇒ **部分复现**：仅在部分 K 上同向（${unsaturated.filter(k => perKGaps[k].replicates).join(', ') || '无'}）。`
      + `必须按 K 分别陈述，不得概括为"复现"。`)
  }
  else {
    console.info('  ⇒ **定性顺序未复现**：未触顶的 K 上两臂均不高于 current。这是一个真实的跨语料局限，必须如实写入论文，不得修饰。')
  }
  console.info('  注：LoCoMo 与 LongMemEval 的 recall@K 绝对值不可比（粒度不同：turn vs session；')
  console.info('      规模不同：10 段共享对话 vs 500 个各自独立的 haystack，每题候选池仅约 40–60 个 session）。可比的只有顺序。')

  // ── 产物 ─────────────────────────────────────────────────────────────────
  const artifact = {
    experiment: { id: m.id, version: m.version, seed },
    corpus: {
      name: 'LongMemEvalS (cleaned)',
      path: loaded.path,
      source: loaded.source,
      bytes: loaded.bytes,
      sha256: loaded.sha256,
      checksumMatches: loaded.checksumMatches,
      itemsTotal: loaded.data.length,
      itemsEvaluated: n,
      sampled: Boolean(limit),
      sampleSeed: limit ? seed : null,
      typeCounts: parsed.typeCounts,
      abilityCounts: parsed.abilityCounts,
      parseAnomalies: {
        itemsWithDanglingEvidence: parsed.itemsWithDanglingEvidence,
        itemsWithUnparsedDates: parsed.itemsWithUnparsedDates,
        itemsWithUnparsedQuestionDate: parsed.itemsWithUnparsedQuestionDate,
        unknownTypes: parsed.unknownTypes,
      },
      abstention: {
        presentInCorpus: types.includes('abstention'),
        itemsExcluded: 0,
        note: '官方 cleaned 变体的 500 题中不含 abstention 题型（实测题型分布合计 500，`"answer": null` 计数为 0），故无需排除任何题目。',
      },
    },
    metricConvention: {
      granularity: 'session（一条 episode = 一个 haystack session，与 LongMemEval 官方 session 级口径一致）',
      recallAtK: '金标准会话（或 fact_ 变体）出现在 top-K 且 score > retrievalFloor',
      mrr: '1 / 首个命中候选排名；无命中记 0；命中同样要求 score > floor',
      ndcgAtK: '二元相关性（LongMemEval 官方为分级相关性，此处为二元，非同一量）',
      retrievalFloor: lastFloor,
      ks: KS,
    },
    arms: armSummary,
    byQuestionType: byType,
    locomoReference: LOCOMO_REFERENCE,
    qualitativeOrdering: {
      note: '按 K 逐个报告。触顶（三臂 recall ≥ 0.999）的 K 上指标无分辨力，其差距恒为 0，不构成"未复现"的证据。',
      perK: perKGaps,
      unsaturatedKs: unsaturated,
      replicatesAllUnsaturated,
      replicatesAnyK: replicatesAny,
    },
    perQuestion,
  }
  mkdirSync(new URL('./results/', import.meta.url), { recursive: true })
  writeFileSync(
    new URL('./results/j5-longmemeval-recall.json', import.meta.url),
    `${JSON.stringify(withProvenance(artifact), null, 2)}\n`,
  )
  console.info()
  console.info(`产物已写入：eval/results/j5-longmemeval-recall.json`)
  console.info(`总耗时：${((Date.now() - started) / 1000).toFixed(1)}s`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
