import type { GatingCoefficients, LocomoConversation } from '../src/index'
import type { Question } from './j5-recall-harness'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'

/**
 * J5 / P4 —— LoCoMo **store 端到端**三臂（+rrf）权重消融。
 *
 * ── 为什么要有这个脚本 ────────────────────────────────────────────────────
 * 历史产物里 LoCoMo 的三臂权重消融**只有 parts 离线重排轨**
 * （`p2-weight-ablation-2026-09-{15,19}.json`，字段 `rerankPool:150`），
 * **没有 store 端到端轨**。而第二个语料 LongMemEval 的三臂数是 store 端到端。
 * 跨语料对照若拿不同口径的绝对值并列，就是在**一篇主题为"口径缺陷"的论文里
 * 再制造一处口径缺陷** —— 这是本轮必须补的那一半。
 *
 * 本脚本用与 LongMemEval 侧**完全相同**的测量装置（`j5-recall-harness.ts`）
 * 在 LoCoMo 上跑，一次产出两套口径（e2e 与 parts）。其中：
 *   · `parts:*` 应当**逐格复现** `diag-weight-ablation` 的
 *     current/sim-only/no-recency（0.0906 / 0.3580 / 0.3046 @K=8）—— 这是装置自检；
 *   · `e2e:*` 是**本仓库此前不存在**的那条轨，用于与 LongMemEval 的 `e2e:*` 配对。
 *
 * ── 门控条件两侧都跑 ──────────────────────────────────────────────────────
 * LoCoMo 权威消融用 `NO_GATING`；LongMemEval 侧我此前用 `DEFAULT_GATING`。
 * 两者不兼容，故本脚本**两个都跑**，让任一配对方式都成立，而不是挑一个。
 *
 * ── 用法 ──────────────────────────────────────────────────────────────────
 *   tsx eval/j5-locomo-recall-e2e.ts                 # 全 10 段对话
 *   tsx eval/j5-locomo-recall-e2e.ts --limit 1       # 先探耗时
 *
 * 产物：eval/results/j5-locomo-recall-e2e.json
 */
import {
  buildExperimentManifest,
  buildMemory,
  DEFAULT_GATING,
  loadLocomo,
  NO_GATING,
} from '../src/index'
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
import { resolveLocomoPath, sha256File } from './locomo-path'

const GATINGS: { key: 'default' | 'none', coef: GatingCoefficients, note: string }[] = [
  { key: 'default', coef: DEFAULT_GATING, note: 'DEFAULT_GATING（与 LongMemEval 侧一致）' },
  { key: 'none', coef: NO_GATING, note: 'NO_GATING（与 diag-weight-ablation 一致）' },
]

async function main(): Promise<void> {
  const argv = process.argv.slice(2)
  const limitArg = argv.indexOf('--limit')
  const limit = limitArg >= 0 && argv[limitArg + 1] ? Number(argv[limitArg + 1]) : undefined
  const cliPath = argv.find(a => !a.startsWith('--') && a !== String(limit))

  const m = buildExperimentManifest({
    id: 'j5-locomo-recall-e2e',
    name: 'J5/P4: LoCoMo store end-to-end three-arm (+rrf) weight ablation, produced by the same harness as LongMemEval',
    seed: 0,
    conditions: [
      ...GATINGS.map(g => ({ name: `gating-${g.key}`, description: g.note, params: { gating: g.key } })),
      ...E2E_ARMS.map(a => ({ name: `e2e:${a.name}`, description: a.description, params: { weights: a.weights, scoreMode: a.scoreMode ?? 'standardized' } })),
    ],
    metrics: ['recall@1', 'recall@2', 'recall@4', 'recall@8', 'MRR', 'NDCG@K', 'poolSize', 'effectiveTruncation'],
    notes: 'Adds the store end-to-end track that no prior LoCoMo artifact had (p2-weight-ablation-* are rerankPool:150 parts-only). Both gating conditions are run so either pairing (DEFAULT_GATING vs LongMemEval, NO_GATING vs diag-weight-ablation) is valid. Every arm reports two floor conventions: floor=0 (adopted, pure ranking) and floor=config.retrievalFloor=0.02 (control); the difference is the floor artifact. Not self-registered in experiments.registry.json.',
  })
  console.info(`experiment manifest built: ${m.schema} ${m.id}@${m.version} — 未自行写入注册表`)
  console.info()

  const path = resolveLocomoPath(cliPath).path
  const sha = sha256File(path)
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== J5 / P4：LoCoMo store 端到端三臂（+rrf）===')
  console.info(`语料路径 : ${path}`)
  console.info(`sha256   : ${sha}`)
  console.info(`对话数   : ${convs.length}${limit ? ` (--limit ${limit})` : ' (全量)'}`)
  console.info(`门控     : ${GATINGS.map(g => g.key).join(', ')}（两个都跑）`)
  console.info(`截断池   : RERANK_POOL = ${RERANK_POOL}（与 diag-weight-ablation 同值）`)
  console.info()

  const rowsByGating: Record<string, ReturnType<typeof measureArms>> = {}
  const started = Date.now()

  for (const g of GATINGS) {
    const rows: ReturnType<typeof measureArms> = []
    for (let ci = 0; ci < convs.length; ci++) {
      const conv: LocomoConversation = convs[ci]
      const mem = await buildMemory(conv, g.coef)
      const questions: Question[] = conv.qa.map((q, qi) => {
        const gold = new Set<string>()
        for (const e of q.evidence ?? []) {
          if (!conv.evidenceIds.has(e))
            continue
          gold.add(e)
          gold.add(`fact_${e}`)
        }
        const relevantTotal = mem.episodes.filter(e => !e.forgotten && conv.evidenceIds.has(e.id)).length
        return { id: `${conv.sampleId}#${qi}`, text: q.question, gold, relevantTotal }
      })
      rows.push(...measureArms(mem, questions))
      const done = rows.length
      if ((ci + 1) % 1 === 0 || ci === convs.length - 1) {
        const el = (Date.now() - started) / 1000
        console.info(`  [gating=${g.key}] conv ${ci + 1}/${convs.length}  题累计 ${done}  已用 ${el.toFixed(1)}s`)
      }
    }
    rowsByGating[g.key] = rows
  }

  const summary: Record<string, Record<string, ReturnType<typeof aggregate>>> = {}
  console.info()
  for (const g of GATINGS) {
    const rows = rowsByGating[g.key]
    summary[g.key] = {}
    console.info(`=== gating=${g.key}（${g.note}）n=${rows.length} 题 ===`)
    console.info(`${'arm'.padEnd(18) + KS.map(k => `R0@${k}`.padStart(8)).join('') + KS.map(k => `RF@${k}`.padStart(8)).join('')}      MRR`)
    for (const key of ARM_KEYS) {
      const a = aggregate(rows, key)
      summary[g.key][key] = a
      console.info(
        key.padEnd(18)
        + KS.map(k => a.recallFloor0[k].toFixed(4).padStart(8)).join('')
        + KS.map(k => a.recallFloorCfg[k].toFixed(4).padStart(8)).join('')
        + a.mrr.toFixed(4).padStart(10),
      )
    }
    console.info('  （R0 = floor=0 纯排名，采信值；RF = floor=0.02 现口径，对照）')
    console.info()
  }

  // ── 装置自检：parts 轨应逐格复现 diag-weight-ablation 的权威值 ──────────
  console.info('=== 装置自检（parts 轨 vs LoCoMo 权威消融）===')
  const AUTH = { 'current': 0.0906, 'sim-only': 0.3580, 'no-recency': 0.3046 }
  const selfCheck: Record<string, { measured: number, authoritative: number, delta: number }> = {}
  for (const name of ['current', 'sim-only', 'no-recency'] as const) {
    const measured = summary.none?.[`parts:${name}`]?.recallFloorCfg[MAX_K] ?? Number.NaN
    const d = measured - AUTH[name]
    selfCheck[name] = { measured, authoritative: AUTH[name], delta: d }
    console.info(`  parts:${name.padEnd(12)} 实测 ${measured.toFixed(4)}  权威 ${AUTH[name]}  Δ=${d >= 0 ? '+' : ''}${d.toFixed(4)}  ${Math.abs(d) < 0.0005 ? '✅ 逐格复现' : '⚠️ 不一致'}`)
  }
  console.info()

  // ── 池规模分层 ──────────────────────────────────────────────────────────
  const strataOut: Record<string, Record<string, { n: number, recall8Floor0: Record<string, number> }>> = {}
  for (const g of GATINGS) {
    strataOut[g.key] = {}
    const rows = rowsByGating[g.key]
    console.info(`=== 池规模分层（gating=${g.key}）===`)
    console.info(`stratum        n     poolSize(mean)  effTrunc(mean)  ${ARM_KEYS.slice(0, 4).map(k => k.padStart(16)).join('')}`)
    for (const s of POOL_STRATA) {
      const sub = rows.filter(r => r.poolSize >= s.lo && r.poolSize < s.hi)
      if (!sub.length) {
        console.info(`${s.label.padEnd(14)}${String(0).padStart(4)}  （空）`)
        continue
      }
      const meanPool = sub.reduce((a, r) => a + r.poolSize, 0) / sub.length
      const meanTrunc = sub.reduce((a, r) => a + r.effectiveTruncation, 0) / sub.length
      const cells: string[] = []
      const rec: Record<string, number> = {}
      for (const key of ARM_KEYS.slice(0, 4)) {
        const v = aggregate(sub, key).recallFloor0[MAX_K]
        rec[key] = v
        cells.push(v.toFixed(4).padStart(16))
      }
      strataOut[g.key][s.label] = { n: sub.length, recall8Floor0: rec }
      console.info(`${s.label.padEnd(14)}${String(sub.length).padStart(4)}  ${meanPool.toFixed(1).padStart(14)}  ${meanTrunc.toFixed(3).padStart(14)}  ${cells.join('')}`)
    }
    console.info()
  }

  const poolSizes = rowsByGating.none.map(r => r.poolSize).sort((a, b) => a - b)
  const q = (p: number) => poolSizes[Math.min(poolSizes.length - 1, Math.floor(p * poolSizes.length))]

  const artifact = {
    experiment: { id: m.id, version: m.version },
    corpus: {
      name: 'LoCoMo',
      path,
      sha256: sha,
      conversations: convs.length,
      questions: rowsByGating.none.length,
      gatingConditions: GATINGS.map(g => g.key),
    },
    convention: {
      rerankPool: RERANK_POOL,
      maxK: MAX_K,
      e2e: 'mem.retrieve(q, MAX_K, false, weights) —— 含检索噪声与冲突惩罚、全候选池',
      parts: '取现行打分前 150 条，用 c.parts 按各臂权重重排；floor 沿用该候选的 store 分数（同 diag-weight-ablation.ts:157）',
      floorDual: {
        adopted: 'floor=0（纯排名能力）—— 跨打分模式可比',
        control: 'floor=config.retrievalFloor=0.02 —— 现口径，跨打分模式不可比（RRF 分数域仅约 0.010–0.038）',
      },
      crossCorpusRule: '两语料只在 e2e↔e2e 或 parts↔parts 之间比；与 LoCoMo 权威值 0.0906/0.3580/0.3046 比时用 parts。',
    },
    poolSizeStats: {
      n: poolSizes.length,
      min: poolSizes[0],
      p50: q(0.5),
      mean: Number((poolSizes.reduce((a, b) => a + b, 0) / poolSizes.length).toFixed(1)),
      max: poolSizes[poolSizes.length - 1],
    },
    arms: summary,
    selfCheckAgainstAuthoritative: selfCheck,
    poolStrata: strataOut,
  }

  mkdirSync(new URL('./results/', import.meta.url), { recursive: true })
  writeFileSync(
    new URL('./results/j5-locomo-recall-e2e.json', import.meta.url),
    `${JSON.stringify(withProvenance(artifact), null, 2)}\n`,
  )
  console.info(`产物已写入：eval/results/j5-locomo-recall-e2e.json`)
  console.info(`总耗时：${((Date.now() - started) / 1000).toFixed(1)}s`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
