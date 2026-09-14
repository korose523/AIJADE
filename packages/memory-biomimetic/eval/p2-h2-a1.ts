/**
 * H2-A1（救门控）：v2 预测 salience（AUC≈0.81）下重跑熔断点。
 *
 * 背景：commit 01b9988 去 oracle 化显示，旧预测器（AUC 0.645）下门控增益塌缩
 * （gated−uniform gap = +0.010/−0.006/−0.022），据此熔断点应触发。但诊断表明旧
 * 预测器是**特征选错**（把疑问当正信号、长度只给 0.10），并非机制不存在。v2 预测器
 * LOCV AUC=0.812（嵌套 0.815），稳定过 0.78 门槛。
 *
 * 本实验回答两问：
 *   1. v2 预测 salience 下门控增益是否恢复？
 *      · 现在门控由**内容显著性**驱动（commit 0683600 重框定），不再接收多巴胺注入；
 *        因此 oracle/prior/locv 三种"注入模式"已无意义——它们都收敛到同一个
 *        内容显著性门控。本脚本只保留可复跑的核心：gated（内容显著性）vs uniform（NO_GATING）。
 *      · predictor 质量（PRIOR/LOCV AUC）仍作为独立诊断保留并报告。
 *   2. H2c 状态依赖性：旧版"变化心情 vs 固定中性心情"现已无意义——重框定后生理层
 *      只做可关闭的表达调制、不门控记忆，故保留/遗忘完全由内容显著性决定，与心情无关。
 *      结论从"生理门控"收窄为"话语显著性驱动的保留"，并在本脚本中直接成立。
 *
 * 编码/显著性：gated 条件经 encode 内部用 predictSalienceV2 计算内容显著性 → durability；
 * uniform 条件（NO_GATING）所有系数 0 → durability≡1、衰减一致，只能按新旧排序。
 *
 * Usage:  tsx eval/p2-h2-a1.ts [path-to-locomo.json]
 */
import type { ForgettingConfig, GatingCoefficients, LocomoConversation, MemoryConfig } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'

import {
  auc,
  BioticMemory,
  buildCorpusIdf,
  buildExperimentManifest,
  DAY,
  DEFAULT_FORGETTING,
  DEFAULT_GATING,
  DEFAULT_MEMORY_CONFIG,
  evidenceRecall,
  fitSalienceLogistic,
  LexicalDistiller,
  loadLocomo,
  NO_GATING,
  predictSalienceV2,
  PRIOR_SALIENCE_WEIGHTS,
  registerExperimentManifest,
  retrievalStrength,
  salienceFeatureVector,
  scoreFeatures,
  standardizeFeatures,
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

/** 因果：返回 episode (ci,ei) 之前所有 turn 文本（不含自身、不含未来）。 */
function priorsBefore(convs: LocomoConversation[], ci: number, ei: number): string[] {
  const out: string[] = []
  for (let j = 0; j < ei; j++) out.push(convs[ci].episodes[j].content)
  return out
}

/**
 * 只读地评估 v2 预测器质量（PRIOR / LOCV AUC）。复用了本脚本的因果特征，
 * 与 H2 主实验使用同一个 predictSalienceV2 + 留一对话交叉验证。
 */
function computePredictorQuality(
  convs: LocomoConversation[],
  idf: Map<string, number>,
  nDocs: number,
): { aucPrior: number, aucLocv: number } {
  const flat: { ci: number, ei: number }[] = []
  for (let ci = 0; ci < convs.length; ci++) {
    for (let ei = 0; ei < convs[ci].episodes.length; ei++) flat.push({ ci, ei })
  }

  const priorRaw: number[] = []
  const locvRaw: number[] = []
  const labels: number[] = []
  const featRows: { ci: number, ei: number, feats: number[], label: number }[] = []

  for (const { ci, ei } of flat) {
    const e = convs[ci].episodes[ei]
    const ctx = { priors: priorsBefore(convs, ci, ei), idf, nDocs }
    priorRaw.push(predictSalienceV2(e.content, ctx, { weights: PRIOR_SALIENCE_WEIGHTS }).score)
    const feats = salienceFeatureVector(e.content, ctx)
    const label = convs[ci].evidenceIds.has(e.id) ? 1 : 0
    labels.push(label)
    featRows.push({ ci, ei, feats, label })
  }

  // LOCV：逐对话留一拟合
  for (let held = 0; held < convs.length; held++) {
    const tr = featRows.filter(r => r.ci !== held)
    const te = featRows.filter(r => r.ci === held)
    const { data: trD, mean, sd } = standardizeFeatures(tr.map(r => r.feats))
    const trY = tr.map(r => r.label)
    const w = fitSalienceLogistic(trD, trY)
    const teD = te.map(r => r.feats.map((v, j) => (v - mean[j]) / (sd[j] || 1)))
    const sc = scoreFeatures(w, teD)
    te.forEach((r, k) => {
      locvRaw[flat.findIndex(f => f.ci === r.ci && f.ei === r.ei)] = sc[k]
    })
  }

  return { aucPrior: auc(priorRaw, labels), aucLocv: auc(locvRaw, labels) }
}

async function build(conv: LocomoConversation, cond: Cond): Promise<BioticMemory> {
  const config: MemoryConfig = {
    ...DEFAULT_MEMORY_CONFIG,
    gating: GATING[cond],
    forgetting: FORGETTING[cond],
  }
  const mem = new BioticMemory(config, conv.endTs)
  for (const e of conv.episodes) {
    // v2/P2：encode 内部按内容显著性计算 durability，不再接收 encoding 参数。
    mem.encode({
      id: e.id,
      content: e.content,
      createdAt: e.createdAt,
      context: e.context,
      baseStrength: e.baseStrength,
    })
  }
  await mem.consolidate(new LexicalDistiller())
  return mem
}

interface Row { kind: 'episode' | 'fact', id: string, strength: number, createdAt: number }

/**
 * 存储预算截断：按 strength 降序保留前 budget 比例，其余逐出。
 * v2/P2：衰减指数由**内容显著性**驱动（retrievalStrength 第 5 参），取记忆在 encode
 * 时算好的 e.encoding.salience / fc.salience，不再接收 cortisol / 心情。
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
      createdAt: e.createdAt,
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
    })
  }
  for (const fc of mem.facts) {
    rows.push({
      kind: 'fact',
      id: fc.id,
      createdAt: fc.createdAt,
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
    id: 'h2-a1-v2-predictor-gated',
    name: 'H2-A1: v2 predicted content salience (AUC≈0.81) — gated vs uniform under matched storage',
    seed: 0,
    conditions: [
      { name: 'gated', description: 'DEFAULT_GATING — content-salience-driven durability (predictSalienceV2)', params: { gating: 'DEFAULT_GATING' } },
      { name: 'uniform', description: 'NO_GATING — identity gate, uniform decay', params: { gating: 'NO_GATING' } },
    ],
    metrics: ['predictor.aucPrior', 'predictor.aucLocv', 'evidenceRecall@K', 'gap.gatedMinusUniform'],
    notes: 'Re-runs the H2 fuse-point with the v2 predictor (PRIOR/LOCV AUC reported). Re-frame (commit 0683600): former oracle/prior/locv dopamine-injection modes and gated-varied/fixed mood modes obsolete; collapses to content-salience gated vs NO_GATING uniform. Falsifiable: gap > 0 ⇒ H2 holds, fuse-point does not trigger.',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const path = process.argv[2] ?? '/tmp/locomo10.json'
  const convs = loadLocomo(path)

  console.info('=== H2-A1：v2 预测 salience（内容显著性门控）下的熔断点 ===')
  console.info(`corpus        : ${path}`)
  console.info(`conversations : ${convs.length}`)
  console.info(`horizon       : +${HORIZON_DAYS}d`)
  console.info(`budgets       : ${BUDGETS.map(b => `${Math.round(b * 100)}%`).join(', ')}`)
  console.info(`metric        : evidenceRecall@${TOP_K} after budget truncation`)
  console.info()

  const allTexts: string[] = []
  for (const c of convs) {
    for (const e of c.episodes) allTexts.push(e.content)
  }
  const { idf, nDocs } = buildCorpusIdf(allTexts)

  const { aucPrior, aucLocv } = computePredictorQuality(convs, idf, nDocs)
  console.info('--- v2 预测器质量（复用本脚本的因果特征）---')
  console.info(`  PRIOR AUC : ${aucPrior.toFixed(3)}   LOCV AUC : ${aucLocv.toFixed(3)}   (门槛≈0.78)`)
  console.info()

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

  console.info('--- H2：内容显著性门控 gated − uniform gap ---')
  console.info('  budget |  gated  | uniform |  gap')
  for (const b of BUDGETS) {
    const g = avg(out.gated[String(b)])
    const u = avg(out.uniform[String(b)])
    const gap = g - u
    console.info(`  ${String(Math.round(b * 100)).padStart(4)}%  | ${g.toFixed(3)} | ${u.toFixed(3)} | ${(gap >= 0 ? '+' : '')}${gap.toFixed(3)}`)
  }
  console.info()
  console.info('判读：')
  console.info('  · gap>0 ⇒ 内容显著性门控在同等存储下保留更多证据 ⇒ H2 成立，熔断点不触发')
  console.info('  · gap≈0 ⇒ 门控增益消失 ⇒ 应回到 v3 §10 熔断点讨论（生理层降级为表达调制）')
  console.info('  · 重框定（commit 0683600）后，旧 oracle/prior/locv 注入模式与 gated-varied/fixed 心情维度')
  console.info('    均收敛到同一内容显著性门控，故本脚本只保留可复跑的 gated vs uniform 核心。')

  const summary = BUDGETS.map(b => ({
    budget: b,
    gated: avg(out.gated[String(b)]),
    uniform: avg(out.uniform[String(b)]),
    gap: avg(out.gated[String(b)]) - avg(out.uniform[String(b)]),
  }))

  const artifact = {
    experiment: 'H2-A1: v2 predicted content salience (AUC 0.81) — gated (content-salience) vs uniform under matched storage',
    corpus: path,
    conversations: convs.length,
    horizonDays: HORIZON_DAYS,
    budgets: BUDGETS,
    topK: TOP_K,
    predictor: { aucPrior, aucLocv, threshold: 0.78 },
    results: out,
    summary,
    note: 'After re-frame (commit 0683600) the gate is content-salience driven; the former oracle/prior/locv dopamine-injection modes and gated-varied/gated-fixed mood modes are obsolete (encode computes salience internally; physiology no longer gates retention). This run collapses to the re-runnable core: content-salience gated vs NO_GATING uniform.',
  }
  mkdirSync('eval/results', { recursive: true })
  writeFileSync('eval/results/p2-h2-a1.json', `${JSON.stringify(artifact, null, 2)}\n`)
  console.info()
  console.info('artifact written: eval/results/p2-h2-a1.json')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
