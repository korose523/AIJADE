import type { ForgettingConfig, GatingCoefficients, LocomoConversation, MemoryConfig } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'

/**
 * H2 (v3 §9) — 门控遗忘是否优于均匀遗忘。
 *
 * 这是 v3 §10 的 **P3 熔断点**实验：若门控在"同等存储预算"下拿不到稳定增益，
 * 按 v3 §10 / v4 §17.2 的正确做法是把生理层降级为表现调制，而不是继续往上盖 L2/L5。
 *
 *   假设 H2：门控遗忘优于均匀遗忘
 *   对照组：均匀衰减 / 无遗忘
 *   主指标：同等存储预算下的证据召回率（evidenceRecall@K）
 *   样本量：3 种存储预算 × 3 seed（v3 §9 下限）
 *
 * 为什么"存储预算"是关键：全量存储下谁都能召回，差异会被淹没。只有在**必须丢弃
 * 一部分记忆**时，"该丢谁"才成为可测的能力——而"该丢谁"正是遗忘策略的全部内容。
 *
 * 三种条件：
 *   gated   — PlasticityGate 调制：重要记忆 durability>1（多巴胺/社交），因而衰减更慢
 *   uniform — 恒等 gate（NO_GATING）：所有记忆 durability=1、衰减系数一致，只能按新旧排序
 *   none    — 不遗忘（baseDecay=0）：strength 无差异 ⇒ 预算截断退化为"保留最近"
 *
 * 可证伪预测：预算越紧，gated 相对 uniform 的优势越大（因为 gated 有"重要性"信号，
 * uniform 只有"新旧"信号）。若 gated ≈ uniform，则 H2 不成立 → 触发熔断点。
 *
 * Usage:  tsx eval/p2-h2-forgetting.ts [path-to-locomo.json] [conversation-limit]
 *
 * v2/P2 重框定说明（commit 0683600）：门控改为由**内容显著性**驱动；
 * 生理层降级为可关闭的"表达调制"，不再门控记忆。因此原"生理/心情 seed"维度已失效，
 * 本脚本只测可复跑的核心：gated（内容显著性）vs uniform（NO_GATING）vs none（不遗忘）。
 */
import {
  BioticMemory,
  buildExperimentManifest,
  DAY,
  DEFAULT_FORGETTING,
  DEFAULT_GATING,
  DEFAULT_MEMORY_CONFIG,
  evidenceRecall,
  LexicalDistiller,
  loadLocomo,
  NO_GATING,
  registerExperimentManifest,
  retrievalStrength,
} from '../src/index'

type Cond = 'gated' | 'uniform' | 'none'
const CONDS: Cond[] = ['gated', 'uniform', 'none']

/** 遗忘地平线：90 天，足够让衰减分化，又不至于全部归零。 */
const HORIZON_DAYS = 90
/** v3 §9 要求三种存储预算。 */
const BUDGETS = [0.10, 0.25, 0.50]
/** v3 §9 要求 ≥3 seed；但重框定后门控由内容显著性驱动、确定性可复现，seed 维度已无作用。 */
const TOP_K = 4

const GATING: Record<Cond, GatingCoefficients> = {
  gated: DEFAULT_GATING,
  uniform: NO_GATING,
  none: NO_GATING,
}

const FORGETTING: Record<Cond, ForgettingConfig> = {
  gated: DEFAULT_FORGETTING,
  uniform: DEFAULT_FORGETTING,
  // 不遗忘：衰减指数为 0 ⇒ strength 不随时间下降
  none: { ...DEFAULT_FORGETTING, baseDecay: 0 },
}

// v2/P2：生理/心情 seed 维度已失效——重框定（0683600）后门控由内容显著性驱动，
// 生理层只做可关闭的表达调制、不门控记忆。故保留（cond, budget）的确定性结果即可，
// 不再需要 seed 循环。

async function build(conv: LocomoConversation, cond: Cond): Promise<BioticMemory> {
  const config: MemoryConfig = {
    ...DEFAULT_MEMORY_CONFIG,
    gating: GATING[cond],
    forgetting: FORGETTING[cond],
  }
  const mem = new BioticMemory(config, conv.endTs)
  for (const ep of conv.episodes) {
    // v2/P2：encode 内部按内容显著性计算 durability，不再接收 encoding 参数。
    mem.encode({
      id: ep.id,
      content: ep.content,
      createdAt: ep.createdAt,
      context: ep.context,
      baseStrength: ep.baseStrength,
    })
  }
  await mem.consolidate(new LexicalDistiller())
  return mem
}

interface Row {
  kind: 'episode' | 'fact'
  id: string
  strength: number
  createdAt: number
}

/**
 * 存储预算截断：按 strength 降序保留前 budget 比例，其余**逐出**。
 * 逐出 = 打上 forgotten（情景）或从 facts 中移除（语义），之后 retrieve 不再见它们。
 * 这是"同等存储"的严格实现：三种条件在同一预算下保留同样数量的记忆。
 */
/**
 * 存储预算截断：按 strength 降序保留前 budget 比例，其余逐出。
 * v2/P2：strength 中的衰减指数由**内容显著性**驱动（retrievalStrength 第 5 参），
 * 取记忆在 encode 时算好的 e.encoding.salience / fc.salience，不再接收 cortisol。
 */
function truncateToBudget(mem: BioticMemory, now: number, budget: number): void {
  const rows: Row[] = []
  const f = mem.config.forgetting
  const g = mem.config.gating
  for (const e of mem.episodes) {
    if (e.forgotten)
      continue
    rows.push({
      kind: 'episode',
      id: e.id,
      strength: retrievalStrength(
        {
          createdAt: e.createdAt,
          accessCount: e.accessCount,
          baseStrength: e.baseStrength,
          durability: e.durability,
        },
        now,
        f,
        g,
        e.encoding.salience,
      ),
      createdAt: e.createdAt,
    })
  }
  for (const fc of mem.facts) {
    rows.push({
      kind: 'fact',
      id: fc.id,
      strength: retrievalStrength(
        {
          createdAt: fc.createdAt,
          accessCount: fc.accessCount,
          baseStrength: fc.baseStrength,
          durability: fc.durability,
        },
        now,
        f,
        g,
        fc.salience,
      ),
      createdAt: fc.createdAt,
    })
  }
  // strength 相同时按新旧（newest first）——"无遗忘"条件下 strength 无差异，
  // 此时退化成"保留最近的"，这正是该条件的预期行为。
  rows.sort((a, b) => b.strength - a.strength || b.createdAt - a.createdAt)
  const keepCount = Math.max(1, Math.ceil(rows.length * budget))
  const keep = new Set(rows.slice(0, keepCount).map(r => `${r.kind}:${r.id}`))

  for (const e of mem.episodes) {
    if (!e.forgotten && !keep.has(`episode:${e.id}`))
      e.forgotten = true
  }
  const keptFacts = mem.facts.filter(fc => keep.has(`fact:${fc.id}`))
  mem.facts.splice(0, mem.facts.length, ...keptFacts)
}

function avg(a: number[]): number {
  return a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0
}

async function main(): Promise<void> {
  const m = buildExperimentManifest({
    id: 'h2-gated-forgetting-ablation',
    name: 'H2 (v3 §9): gated vs uniform vs no forgetting under matched storage budget',
    seed: 0,
    conditions: [
      { name: 'gated', description: 'DEFAULT_GATING — content-salience-driven durability (important memories decay slower)', params: { gating: 'DEFAULT_GATING', forgetting: 'DEFAULT_FORGETTING' } },
      { name: 'uniform', description: 'NO_GATING — identity gate, all durability=1, decay uniform', params: { gating: 'NO_GATING', forgetting: 'DEFAULT_FORGETTING' } },
      { name: 'none', description: 'No forgetting (baseDecay=0) — truncation degrades to keep-most-recent', params: { gating: 'NO_GATING', forgetting: 'baseDecay=0' } },
    ],
    metrics: ['evidenceRecall@K', 'gap.gatedMinusUniform'],
    notes: 'Budgets [10%,25%,50%]; horizon +90d; TOP_K=4. Re-frame (commit 0683600): gate is content-salience driven, deterministic per (cond, budget) — former physiological-seed dimension removed. Falsifiable prediction: gated > uniform, gap widens as budget tightens; else v3 §10 P3 fuse-point triggers.',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const path = process.argv[2] ?? '/tmp/locomo10.json'
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convs = loadLocomo(path)
  const subset = limit ? convs.slice(0, limit) : convs

  console.info('=== H2 (v3 §9): 门控遗忘 vs 均匀遗忘 vs 无遗忘 — 同等存储预算下的准确率 ===')
  console.info(`corpus        : ${path}`)
  console.info(`conversations : ${subset.length}`)
  console.info(`horizon       : +${HORIZON_DAYS}d`)
  console.info(`budgets       : ${BUDGETS.map(b => `${Math.round(b * 100)}%`).join(', ')}`)
  console.info(`metric        : evidenceRecall@${TOP_K} after budget truncation`)
  console.info()

  // results[budget][cond] = mean recall over conversations (deterministic per cond/budget)
  const results: Record<string, Record<Cond, number[]>> = {}
  for (const b of BUDGETS) {
    results[String(b)] = { gated: [], uniform: [], none: [] }
  }

  for (const cond of CONDS) {
    for (const b of BUDGETS) {
      const perConv: number[] = []
      for (const conv of subset) {
        const now = conv.endTs + HORIZON_DAYS * DAY
        const mem = await build(conv, cond)
        truncateToBudget(mem, now, b)
        mem.setNow(now) // 推进时钟并失效索引
        perConv.push(evidenceRecall(mem, conv, TOP_K).overall)
      }
      results[String(b)][cond].push(avg(perConv))
    }
  }

  console.info('evidenceRecall@K  (mean over conversations; deterministic per cond/budget)')
  console.info('  budget   gated            uniform          none             gap(gated-uniform)')
  for (const b of BUDGETS) {
    const r = results[String(b)]
    const gm = avg(r.gated)
    const um = avg(r.uniform)
    const fmt = (a: number[]) => `${avg(a).toFixed(3)} [${a.map(x => x.toFixed(3)).join(' ')}]`
    console.info(
      `  ${String(Math.round(b * 100)).padStart(4)}%   ${fmt(r.gated).padEnd(16)} ${fmt(r.uniform).padEnd(16)} ${fmt(r.none).padEnd(16)} ${(gm - um >= 0 ? '+' : '')}${(gm - um).toFixed(3)}`,
    )
  }
  console.info()
  console.info('判读：')
  console.info('  · gated > uniform 且差距随预算收紧而变大 ⇒ H2 成立，生理层保住机制主张。')
  console.info('  · gated ≈ uniform ⇒ H2 不成立 ⇒ 按 v3 §10 触发 P3 熔断点，生理层应降级为表现调制。')
  console.info('  · uniform/none 不受内容显著性影响（恒等 gate 下所有记忆 durability=1、衰减一致）——这是消融干净的证据，而非缺陷。')
  const artifact = {
    experiment: 'H2 (v3 §9): gated vs uniform vs no forgetting under matched storage budget',
    corpus: path,
    conversations: subset.length,
    horizonDays: HORIZON_DAYS,
    budgets: BUDGETS,
    topK: TOP_K,
    metric: 'evidenceRecall@K after budget truncation',
    perSeed: results,
    summary: BUDGETS.map(b => ({
      budget: b,
      gated: avg(results[String(b)].gated),
      uniform: avg(results[String(b)].uniform),
      none: avg(results[String(b)].none),
      gapGatedUniform: avg(results[String(b)].gated) - avg(results[String(b)].uniform),
    })),
    caveat: 'After the re-frame (commit 0683600) the gate is driven by content salience (predictSalienceV2), not by an oracle label or by physiology. The measured gating benefit is therefore conditional on the predicted-salience signal being available; p2-h2-salience.ts re-tests the mechanism with the predicted signal. Retention is now deterministic per (cond, budget) — the former physiological-seed dimension is gone (physiology only modulates presentation).',
  }
  mkdirSync('eval/results', { recursive: true })
  writeFileSync('eval/results/p2-h2.json', `${JSON.stringify(artifact, null, 2)}\n`)
  console.info('artifact written: eval/results/p2-h2.json')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
