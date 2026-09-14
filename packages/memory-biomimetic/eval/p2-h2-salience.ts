import type { ForgettingConfig, GatingCoefficients, LocomoConversation, MemoryConfig } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'

/**
 * H2 去 oracle 化 —— 决定机制主张能否站住的关键实验（重框定后版本）。
 *
 * 问题：`locomo.ts` 用 oracle 标注 salience（dia_id 是否出现在金标准 evidence 中）。
 * 上一个 H2（`p2-h2-forgetting.ts`）在该 oracle 下测到 gated > uniform。但这个增益
 * 有两个可能来源：
 *   (a) 门控真的有用（把"重要的"挑出来）；
 *   (b) 门控只是**转述了答案**（因为"重要"是金标准直接给的）。
 *
 * 本实验用**预测式 salience**（`src/salience.ts` 的 `predictSalience`，完全不接触金标准
 * 标签）重跑同一 H2 协议，并报告：
 *   1. 预测器质量（AUC：0.5=随机，1.0=完美）
 *   2. 预测（内容）显著性下 gated−uniform 差距
 *
 * 重框定说明（commit 0683600）：门控现由**内容显著性**驱动，encode 内部用
 * `predictSalienceV2` 计算，store 不接受外部 dopamine/cortisol 注入。因此：
 *   · 旧版的"oracle vs predicted"两种编码注入模式已无意义——两种都收敛到同一个
 *     内容显著性门控；本脚本只保留可复跑的核心 gated（内容显著性）vs uniform（NO_GATING）。
 *   · 旧版的 α 混合敏感度（把 oracle 与预测按 α 混合多巴胺）同样建立在"注入"假设上，
 *     已不适用，故移除；"门控值得做需要多好的预测器"这一科学问题改由上方 predictor AUC
 *     直接回答（AUC 过 0.78 门槛即认为预测信号可用）。
 *
 * Usage:  tsx eval/p2-h2-salience.ts [path-to-locomo.json]
 */
import {
  auc,
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
  predictSalience,
  registerExperimentManifest,
  retrievalStrength,
} from '../src/index'

type Cond = 'gated' | 'uniform'
const CONDS: Cond[] = ['gated', 'uniform']

const HORIZON_DAYS = 90
const BUDGETS = [0.10, 0.25, 0.50]
const TOP_K = 4

const GATING: Record<Cond, GatingCoefficients> = {
  gated: DEFAULT_GATING,
  uniform: NO_GATING,
}
const FORGETTING: Record<Cond, ForgettingConfig> = {
  gated: DEFAULT_FORGETTING,
  uniform: DEFAULT_FORGETTING,
}

/** 只读地计算预测显著性分数 —— **不修改**任何 episode。 */
function computePredictedScores(conv: LocomoConversation): number[] {
  const priors: string[] = []
  const scores: number[] = []
  for (const ep of conv.episodes) {
    scores.push(predictSalience(ep.content, priors).total)
    priors.push(ep.content)
  }
  return scores
}

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

function truncateToBudget(mem: BioticMemory, now: number, budget: number): void {
  interface Row {
    kind: 'episode' | 'fact'
    id: string
    strength: number
    createdAt: number
  }
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
    id: 'h2-content-salience-gated',
    name: 'H2 de-oracled: predicted (content) salience gated vs uniform under matched storage',
    seed: 0,
    conditions: [
      { name: 'gated', description: 'DEFAULT_GATING — content-salience-driven durability', params: { gating: 'DEFAULT_GATING' } },
      { name: 'uniform', description: 'NO_GATING — identity gate, uniform decay', params: { gating: 'NO_GATING' } },
    ],
    metrics: ['predictor.pooledAuc', 'evidenceRecall@K', 'gap.gatedMinusUniform'],
    notes: 'Reports predictor quality (pooled + per-conversation AUC) and the gated−uniform recall gap under content-salience gating. Re-frame (commit 0683600): oracle/predicted injection and α-mixing are obsolete; both collapse to the same content-salience gate. Falsifiable: gap still > 0 means the gate uses a predictable signal; gap ≈ 0 means the prior H2 gain was oracle leakage (→ v3 §10 fuse-point).',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const path = process.argv[2] ?? '/tmp/locomo10.json'
  const convs = loadLocomo(path)

  console.info('=== H2 去 oracle 化：预测（内容）salience 下的 gated vs uniform ===')
  console.info(`corpus        : ${path}`)
  console.info(`conversations : ${convs.length}`)
  console.info(`horizon       : +${HORIZON_DAYS}d`)
  console.info(`budgets       : ${BUDGETS.map(b => `${Math.round(b * 100)}%`).join(', ')}`)
  console.info(`metric        : evidenceRecall@${TOP_K} after budget truncation`)
  console.info()

  // ---- 1. 预测器质量（只读，不改动 conversations）----
  console.info('--- 预测器质量（predicted vs oracle 标注）---')
  const allScores: number[] = []
  const allLabels: number[] = []
  const perConvAuc: number[] = []
  for (const conv of convs) {
    const scores = computePredictedScores(conv)
    const labels = conv.episodes.map(e => (conv.evidenceIds.has(e.id) ? 1 : 0))
    allScores.push(...scores)
    allLabels.push(...labels)
    perConvAuc.push(auc(scores, labels))
  }
  console.info(`  pooled AUC : ${auc(allScores, allLabels).toFixed(3)}   (0.5 = 随机)`)
  console.info(`  逐对话 AUC : [${perConvAuc.map(a => a.toFixed(2)).join(' ')}]  mean=${avg(perConvAuc).toFixed(3)}`)
  console.info()

  // ---- 2. 内容显著性门控下的 H2（gated vs uniform）----
  const out: Record<Cond, Record<string, number[]>> = { gated: {}, uniform: {} }

  for (const cond of CONDS) {
    for (const b of BUDGETS) {
      const perConv: number[] = []
      for (const conv of convs) {
        const now = conv.endTs + HORIZON_DAYS * DAY
        const mem = await build(conv, cond)
        truncateToBudget(mem, now, b)
        mem.setNow(now)
        perConv.push(evidenceRecall(mem, conv, TOP_K).overall)
      }
      out[cond][String(b)] = [avg(perConv)]
    }
  }

  console.info('--- H2 对照：gated vs uniform（预测/内容显著性门控）---')
  console.info('  budget |  gated  | uniform |  gap')
  for (const b of BUDGETS) {
    const g = avg(out.gated[String(b)])
    const u = avg(out.uniform[String(b)])
    const gap = g - u
    console.info(`  ${String(Math.round(b * 100)).padStart(4)}%  | ${g.toFixed(3)} | ${u.toFixed(3)} | ${(gap >= 0 ? '+' : '')}${gap.toFixed(3)}`)
  }
  console.info()
  console.info('判据：')
  console.info('  · predicted（内容）显著性下 gap 仍为正 ⇒ 门控利用的是可预测信号，机制主张可辩护。')
  console.info('  · gap 塌到 ~0 ⇒ 上一个 H2 的增益主要来自偷看金标准，应回到 v3 §10 熔断点。')
  console.info('  · 重框定（0683600）后 store 内部计算内容显著性，oracle/predicted 注入与 α 混合均收敛到同一门控，已移除。')

  const artifact = {
    experiment: 'H2 de-oracled: predicted (content) salience gated vs uniform',
    corpus: path,
    conversations: convs.length,
    horizonDays: HORIZON_DAYS,
    budgets: BUDGETS,
    topK: TOP_K,
    predictor: {
      pooledAuc: auc(allScores, allLabels),
      perConversationAuc: perConvAuc,
    },
    results: out,
    summary: BUDGETS.map(b => ({
      budget: b,
      gated: avg(out.gated[String(b)]),
      uniform: avg(out.uniform[String(b)]),
      gap: avg(out.gated[String(b)]) - avg(out.uniform[String(b)]),
    })),
    note: 'After re-frame (commit 0683600) the store computes content salience internally, so the oracle-vs-predicted distinction and the α-mixing sensitivity block are obsolete (both collapse to the same content-salience gate). The re-runnable core is content-salience gated vs NO_GATING uniform.',
  }
  mkdirSync('eval/results', { recursive: true })
  writeFileSync('eval/results/p2-h2-salience.json', `${JSON.stringify(artifact, null, 2)}\n`)
  console.info()
  console.info('artifact written: eval/results/p2-h2-salience.json')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
