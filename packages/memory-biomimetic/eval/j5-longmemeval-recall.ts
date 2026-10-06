import type { Question } from './j5-recall-harness'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'

/**
 * J5 / P4 —— 第二语料复现：LongMemEval 上的 recall@K / MRR / NDCG@K 多臂对照。
 *
 * ── 为什么要有这个脚本 ────────────────────────────────────────────────────
 * J5（《检索打分量纲失配》）与 P4（英文版）的核心结论原本**只建立在 LoCoMo 一个
 * 语料（10 段对话）上**，这是论文自己声明的首要效度威胁。本脚本在 LongMemEval
 * （500 题、6 种 question_type、每题独立 haystack）上重跑同一组对照。
 *
 * 检验的是**定性顺序**：`sim-only > no-recency > current` 是否跨语料成立。
 * 注意是顺序，不是数值相等 —— 两语料的粒度、候选池规模、证据标注方式都不同。
 *
 * ── 指标实现不在本文件 ────────────────────────────────────────────────────
 * 全部测量走 `j5-recall-harness.ts`，与 `j5-locomo-recall-e2e.ts` **同一套代码**。
 * 两侧各写一份必然分叉，而分叉后的数字还会被摆进同一张跨语料对照表 ——
 * 那正是 J5 自己点名的"看起来是结论、其实与代码无关"。
 *
 * ── 用法 ──────────────────────────────────────────────────────────────────
 *   tsx eval/j5-longmemeval-recall.ts                 # 全量 500 题
 *   tsx eval/j5-longmemeval-recall.ts --limit 20      # 确定性抽样 20 题
 *   tsx eval/j5-longmemeval-recall.ts --seed 1
 *   tsx eval/j5-longmemeval-recall.ts --no-verify     # 跳过指纹校验（产物不可用于论文）
 *
 * 产物：eval/results/j5-longmemeval-recall.json
 */
import { buildExperimentManifest, buildMemory, DEFAULT_GATING } from '../src/index'
import { withProvenance } from './artifact-provenance'
import {
  aggregate,
  ARM_KEYS,
  E2E_ARMS,
  KS,
  MAX_K,
  measureArms,
  POOL_STRATA,

  RERANK_POOL,
} from './j5-recall-harness'
import { parseLongMemEval, sampleItems } from './longmemeval-adapter'
import { loadLongMemEvalVerified } from './longmemeval-path'

/** LoCoMo 侧权威值（parts 轨），仅作参照 —— 见产物 `convention.crossCorpusRule`。 */
const LOCOMO_AUTHORITATIVE = { 'current': 0.0906, 'sim-only': 0.3580, 'no-recency': 0.3046 }

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
    conditions: E2E_ARMS.map(a => ({ name: a.name, description: a.description, params: { weights: a.weights, scoreMode: a.scoreMode ?? 'standardized' } })),
    metrics: ['recall@1', 'recall@2', 'recall@4', 'recall@8', 'MRR', 'NDCG@K', 'poolSize', 'effectiveTruncation'],
    notes: 'Second corpus for the J5 single-corpus validity threat. LongMemEvalS (cleaned, HF, MIT), 500 items, session-level episodes, each item its own haystack. Measured with j5-recall-harness.ts — the same code as j5-locomo-recall-e2e.ts. Both e2e and parts conventions reported; floor=0 adopted, floor=0.02 control. Abstention: none present in the cleaned release — no items excluded. Not self-registered in experiments.registry.json.',
  })
  console.info(`experiment manifest built: ${m.schema} ${m.id}@${m.version} — 未自行写入注册表`)
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
  console.info(`悬空证据题数 : ${parsed.itemsWithDanglingEvidence}`)
  console.info(`时间解析失败 : 会话 ${parsed.itemsWithUnparsedDates} 题 / 提问时刻 ${parsed.itemsWithUnparsedQuestionDate} 题`)
  console.info(`未知题型     : ${parsed.unknownTypes.length ? parsed.unknownTypes.join(', ') : '（无）'}`)

  const subset = limit ? sampleItems(parsed.items, limit, seed) : parsed.items
  console.info(`参与评测题数 : ${subset.length}${limit ? `  (确定性抽样 seed=${seed})` : '  (全量)'}`)
  console.info(`门控         : DEFAULT_GATING`)
  console.info()

  const rows: (ReturnType<typeof measureArms>[number] & { questionType: string })[] = []
  const started = Date.now()

  for (let i = 0; i < subset.length; i++) {
    const { conv, item } = subset[i]
    const mem = await buildMemory(conv, DEFAULT_GATING)
    const relevantTotal = mem.episodes.filter(e => !e.forgotten && conv.evidenceIds.has(e.id)).length
    const question: Question = {
      id: item.question_id,
      text: conv.qa[0].question,
      gold: new Set<string>([...conv.evidenceIds].flatMap(id => [id, `fact_${id}`])),
      relevantTotal,
    }
    const r = measureArms(mem, [question])[0]
    rows.push({ ...r, questionType: item.question_type })

    if ((i + 1) % 10 === 0 || i === subset.length - 1) {
      const el = (Date.now() - started) / 1000
      console.info(`  [${i + 1}/${subset.length}] 已用 ${el.toFixed(1)}s，预计剩余 ${((el / (i + 1)) * (subset.length - i - 1)).toFixed(1)}s`)
    }
  }

  const summary: Record<string, ReturnType<typeof aggregate>> = {}
  console.info()
  console.info(`=== 各臂结果（n=${rows.length} 题，每题一个独立 haystack）===`)
  console.info(`${'arm'.padEnd(18) + KS.map(k => `R0@${k}`.padStart(8)).join('') + KS.map(k => `RF@${k}`.padStart(8)).join('')}      MRR`)
  for (const key of ARM_KEYS) {
    const a = aggregate(rows, key)
    summary[key] = a
    console.info(
      key.padEnd(18)
      + KS.map(k => a.recallFloor0[k].toFixed(4).padStart(8)).join('')
      + KS.map(k => a.recallFloorCfg[k].toFixed(4).padStart(8)).join('')
      + a.mrr.toFixed(4).padStart(10),
    )
  }
  console.info('  （R0 = floor=0 纯排名，采信值；RF = floor=0.02 现口径，对照。差即 floor 伪影）')
  console.info()

  // ── 定性顺序检验：两轨 × 逐个 K ────────────────────────────────────────
  const ordering: Record<string, Record<number, Record<string, number>>> = {}
  for (const track of ['e2e', 'parts'] as const) {
    ordering[track] = {}
    console.info(`=== 定性顺序检验（${track} 轨，floor=0）===`)
    console.info('   K    current   sim-only  no-recency   Δ(sim−cur)  Δ(noRec−cur)  顺序成立?')
    for (const k of KS) {
      const c = summary[`${track}:current`].recallFloor0[k]
      const s = summary[`${track}:sim-only`].recallFloor0[k]
      const nr = summary[`${track}:no-recency`].recallFloor0[k]
      ordering[track][k] = { current: c, simOnly: s, noRecency: nr, gapSimOnly: s - c, gapNoRecency: nr - c }
      const ok = (s - c) > 0 && (nr - c) > 0
      console.info(
        `  ${String(k).padStart(2)}   ${c.toFixed(4)}    ${s.toFixed(4)}     ${nr.toFixed(4)}     `
        + `${(s - c >= 0 ? '+' : '')}${(s - c).toFixed(4)}     ${(nr - c >= 0 ? '+' : '')}${(nr - c).toFixed(4)}     ${ok ? '是' : '否'}`,
      )
    }
    console.info()
  }

  // ── 分题型 recall@8（e2e 轨，floor=0）───────────────────────────────────
  const byType: Record<string, Record<string, number>> = {}
  const types = [...new Set(rows.map(r => r.questionType))].sort()
  console.info('=== 分题型 recall@8（e2e 轨，floor=0）===')
  console.info(`question_type               n   ${E2E_ARMS.map(a => a.name.padStart(12)).join('')}`)
  for (const t of types) {
    const sub = rows.filter(r => r.questionType === t)
    byType[t] = { n: sub.length }
    const cells: string[] = []
    for (const arm of E2E_ARMS) {
      const v = aggregate(sub, `e2e:${arm.name}`).recallFloor0[MAX_K]
      byType[t][`e2e:${arm.name}`] = v
      cells.push(v.toFixed(4).padStart(12))
    }
    console.info(`${t.padEnd(28) + String(sub.length).padStart(3)}   ${cells.join('')}`)
  }
  console.info()

  // ── 池规模分层 ──────────────────────────────────────────────────────────
  const strata: Record<string, { n: number, meanPoolSize: number, meanEffectiveTruncation: number, recall8Floor0: Record<string, number> }> = {}
  console.info('=== 池规模分层（e2e 轨，recall@8，floor=0）===')
  console.info(`stratum        n     poolSize(mean)  effTrunc(mean)  ${E2E_ARMS.map(a => a.name.padStart(14)).join('')}`)
  for (const s of POOL_STRATA) {
    const sub = rows.filter(r => r.poolSize >= s.lo && r.poolSize < s.hi)
    if (!sub.length) {
      console.info(`${s.label.padEnd(14)}${String(0).padStart(4)}  （空）`)
      continue
    }
    const meanPool = sub.reduce((a, r) => a + r.poolSize, 0) / sub.length
    const meanTrunc = sub.reduce((a, r) => a + r.effectiveTruncation, 0) / sub.length
    const rec: Record<string, number> = {}
    const cells: string[] = []
    for (const arm of E2E_ARMS) {
      const v = aggregate(sub, `e2e:${arm.name}`).recallFloor0[MAX_K]
      rec[`e2e:${arm.name}`] = v
      cells.push(v.toFixed(4).padStart(14))
    }
    strata[s.label] = { n: sub.length, meanPoolSize: meanPool, meanEffectiveTruncation: meanTrunc, recall8Floor0: rec }
    console.info(`${s.label.padEnd(14)}${String(sub.length).padStart(4)}  ${meanPool.toFixed(1).padStart(14)}  ${meanTrunc.toFixed(3).padStart(14)}  ${cells.join('')}`)
  }
  console.info()

  const poolSizes = rows.map(r => r.poolSize).sort((a, b) => a - b)
  const q = (p: number) => poolSizes[Math.min(poolSizes.length - 1, Math.floor(p * poolSizes.length))]

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
      itemsEvaluated: rows.length,
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
        note: '官方 cleaned 变体的 500 题中不含 abstention 题型，故无需排除任何题目。',
      },
    },
    convention: {
      granularity: 'session（一条 episode = 一个 haystack session，与 LongMemEval 官方 session 级口径一致）；LoCoMo 侧为 turn（dia_id）级，两侧绝对值不可相减',
      gating: 'DEFAULT_GATING',
      rerankPool: RERANK_POOL,
      maxK: MAX_K,
      e2e: 'mem.retrieve(q, MAX_K, false, weights) —— 含检索噪声与冲突惩罚、全候选池',
      parts: '取现行打分前 150 条，用 c.parts 按各臂权重重排；floor 沿用该候选的 store 分数',
      floorDual: {
        adopted: 'floor=0（纯排名能力）—— 跨打分模式可比',
        control: 'floor=config.retrievalFloor=0.02 —— 现口径；跨打分模式不可比（RRF 分数域仅约 0.010–0.038）',
      },
      ndcg: '二元相关性（LongMemEval 官方 NDCG 为分级相关性，非同一量）',
      retrievalFloor: 0.02,
      effectiveTruncation: `min(${RERANK_POOL}, poolSize) / poolSize —— 本语料池 38–62 ⇒ 150 截断为空操作`,
      crossCorpusRule: '两语料只在 e2e↔e2e 或 parts↔parts 之间比；与 LoCoMo 权威值比时用 parts。绝对值一律不并列。',
    },
    poolSizeStats: {
      n: poolSizes.length,
      min: poolSizes[0],
      p50: q(0.5),
      mean: Number((poolSizes.reduce((a, b) => a + b, 0) / poolSizes.length).toFixed(1)),
      max: poolSizes[poolSizes.length - 1],
    },
    arms: summary,
    qualitativeOrdering: ordering,
    byQuestionType: byType,
    poolStrata: strata,
    locomoAuthoritative: LOCOMO_AUTHORITATIVE,
  }

  mkdirSync(new URL('./results/', import.meta.url), { recursive: true })
  writeFileSync(
    new URL('./results/j5-longmemeval-recall.json', import.meta.url),
    `${JSON.stringify(withProvenance(artifact), null, 2)}\n`,
  )
  console.info(`产物已写入：eval/results/j5-longmemeval-recall.json`)
  console.info(`总耗时：${((Date.now() - started) / 1000).toFixed(1)}s`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
