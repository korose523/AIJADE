/**
 * 任务 #20-(1) 续：0.1985 vs 0.2064 的残差归因 —— **聚合口径**而非显著性。
 *
 * ── 上一步已排除的 ───────────────────────────────────────────────────────
 * `j5-salience-source-repro.ts`（10 对话，全量）已证明：
 *   · 注入 `salienceOf`（p2-quantile 式 `sigmoid(predictSalienceV2(...))`）与
 *     store 默认显著性**逐条完全相同**（0/5882 条有差异）⇒ 显著性来源是**空操作**，
 *     不是 0.1985 / 0.2064 之差的成因（代码级依据：`src/store.ts:251-255`
 *     的默认分支就是同一个公式、同一个 `ctx`）。
 *   · `pred-salience` 臂**逐位复现** p2-quantile 09-19 的 0.198532（Δ=0.000000）。
 *   · `default-salience` 臂**未复现** store-default 的 0.206445（Δ=−0.007913）。
 * ⇒ 0.1985 是可复现的；**0.2064 才是那个对不上的数**。本脚本去找它对不上的原因。
 *
 * ── 本脚本的假设：宏平均 vs 微平均 ────────────────────────────────────────
 * 两个脚本用的是**同一个** `buildMemory(conv, NO_GATING)` 与**逐位同定义**的命中判据，
 * 但**汇总方式**不同：
 *
 *   · `p2-quantile-retention-sweep.ts:172` —— `push(m.recall[k])`，其中
 *     `m.recall[k] = covered[k] / conv.qa.length`，最后 `avg()`。
 *     ⇒ **每对话先算比例，再对 10 个对话取均值（宏平均 / per-conversation mean）**。
 *   · `j5-rrf-e2e-decomposition.ts:213` —— `push(hitAtK[k] ? 1 : 0)`，
 *     把**每题**的 0/1 累加，最后 `avg()`。
 *     ⇒ **所有题 pooled 后除以总题数（微平均 / question-level micro）**。
 *
 * 各对话题数不等时两者**必然不等**，且没有任何一方算错。
 *
 * ── 为什么既有交叉校验没抓到 ─────────────────────────────────────────────
 * `j5-rrf-e2e-decomposition.ts:224` 的校验 compares
 * `measure(mem, conv, gold)` 与 `avg(convHit[k])`，**在单个对话内部**。
 * 同一对话内 `covered/qa.length` 与 `avg(0/1)` 的分母相同 ⇒ 恒等，
 * 因此该校验**在结构上无法发现跨对话的聚合差异**，报出 0.000000 也不构成证据。
 * 本脚本显式给出两套聚合，闭合这一点。
 *
 * ── 预注册读法 ───────────────────────────────────────────────────────────
 *   A1 若 micro ≈ 0.206445 且 macro ≈ 0.198532
 *      ⇒ 残差**完全**由聚合口径解释，检索侧无差异；0.2064 不是"另一个配置下的数"，
 *         而是**同一批命中数除以不同分母**的结果。
 *   A2 若 micro 也不等于 0.206445 ⇒ 还缺变量，如实报告，不回推、不估算。
 *
 * 用法：tsx eval/j5-aggregation-caliber.ts [path] [conv-limit]
 */
import type { GatingCoefficients } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { buildMemory, DEFAULT_MEMORY_CONFIG, loadLocomo, NO_GATING } from '../src/index'
import { withProvenance } from './artifact-provenance'
import { avg, KS } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

const TARGETS = {
  /** p2-quantile-retention-sweep-2026-09-19.json · arms["baseline-nogating"]（宏平均）。 */
  p2quantile0919_macro: 0.19853236649084932,
  /** 族 B 端到端 store-default（逐题 pooled，微平均）。 */
  storeDefault_micro: 0.20644511581067473,
} as const

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const all = loadLocomo(path)
  const convs = limit ? all.slice(0, limit) : all
  const sha = sha256File(path)

  console.info('=== 聚合口径检验：宏平均(每对话先算比例) vs 微平均(逐题 pooled) ===')
  console.info(`corpus : ${path}`)
  console.info(`sha256 : ${sha}`)
  console.info(`convs  : ${convs.length}${limit ? `（limit=${limit}）` : ''}`)
  console.info()

  // 每对话：命中数 / 题数；同时 pooled 每题 0/1。
  const perConv: { conv: number, hits: Record<number, number>, qa: number }[] = []
  const pooled: Record<number, number[]> = Object.fromEntries(KS.map(k => [k, [] as number[]]))
  let configDrift = 0

  for (const [ci, conv] of convs.entries()) {
    const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)

    // 记录 buildMemory 交付的 config 是否就是 shipped 默认（decomp 的 applyArm 会覆写它）。
    if (mem.config.retrievalScoreMode !== 'standardized'
      || mem.config.dedupeByContent !== true
      || JSON.stringify(mem.config.weights) !== JSON.stringify(DEFAULT_MEMORY_CONFIG.weights)
      || mem.config.retrievalFloor !== DEFAULT_MEMORY_CONFIG.retrievalFloor) {
      configDrift++
    }

    const floor = mem.config.retrievalFloor
    const maxK = Math.max(...KS)
    const hits: Record<number, number> = Object.fromEntries(KS.map(k => [k, 0]))

    for (const q of conv.qa) {
      const cand = new Set<string>()
      for (const e of q.evidence ?? []) {
        if (!conv.evidenceIds.has(e))
          continue
        cand.add(e)
        cand.add(`fact_${e}`)
      }
      const ranking = mem.retrieve(q.question, maxK, false)
      const hitAtK: Record<number, boolean> = Object.fromEntries(KS.map(k => [k, false]))
      for (let i = 0; i < ranking.length; i++) {
        const c = ranking[i]
        if (!cand.has(c.id) || !(c.score > floor))
          continue
        for (const k of KS) {
          if (i + 1 <= k)
            hitAtK[k] = true
        }
      }
      for (const k of KS) {
        const v = hitAtK[k] ? 1 : 0
        hits[k] += v
        pooled[k].push(v)
      }
    }
    perConv.push({ conv: ci, hits, qa: conv.qa.length })
  }

  const macro = Object.fromEntries(KS.map(k => [k, avg(perConv.map(c => c.hits[k] / c.qa))]))
  const micro = Object.fromEntries(KS.map(k => [k, avg(pooled[k])]))
  const totalQ = perConv.reduce((s, c) => s + c.qa, 0)
  const totalHits8 = perConv.reduce((s, c) => s + c.hits[8], 0)

  console.info(`  各对话题数：${perConv.map(c => c.qa).join(', ')}   合计 ${totalQ}`)
  console.info(`  题数不等 ⇒ 宏平均与微平均必然不等：`)
  console.info()
  console.info(`  ${'K'.padEnd(4)}${'macro(每对话→均值)'.padStart(24)}${'micro(逐题 pooled)'.padStart(22)}${'差'.padStart(12)}`)
  for (const k of KS)
    console.info(`  ${String(k).padEnd(4)}${macro[k].toFixed(6).padStart(24)}${micro[k].toFixed(6).padStart(22)}${(micro[k] - macro[k]).toFixed(6).padStart(12)}`)
  console.info()
  console.info(`  R@8 命中数合计 ${totalHits8} / 总题数 ${totalQ} = ${(totalHits8 / totalQ).toFixed(6)}（= micro）`)
  console.info(`  各对话 R@8：${perConv.map(c => `${(c.hits[8] / c.qa).toFixed(4)}(n=${c.qa})`).join('  ')}`)
  console.info()
  console.info(`  buildMemory 交付的 config 与 shipped 默认不一致的对话数：${configDrift} ${configDrift === 0 ? '✅' : '⚠️'}`)
  console.info()

  const near = (x: number, y: number) => Math.abs(x - y) < 5e-5
  console.info('  与历史值对照（判据 |Δ| < 5e-5 即视为复现）：')
  console.info(`    macro R@8 ${macro[8].toFixed(6)}  vs 0.198532 (p2-quantile 09-19)  ${near(macro[8], TARGETS.p2quantile0919_macro) ? '✅ 复现' : '❌ 未复现'}   Δ=${(macro[8] - TARGETS.p2quantile0919_macro).toFixed(6)}`)
  console.info(`    micro R@8 ${micro[8].toFixed(6)}  vs 0.206445 (store-default)   ${near(micro[8], TARGETS.storeDefault_micro) ? '✅ 复现' : '❌ 未复现'}   Δ=${(micro[8] - TARGETS.storeDefault_micro).toFixed(6)}`)
  console.info()

  const macroHit = near(macro[8], TARGETS.p2quantile0919_macro)
  const microHit = near(micro[8], TARGETS.storeDefault_micro)
  console.info('  判读（由上方实测数字生成，无硬编码结论）：')
  if (macroHit && microHit) {
    console.info('  ⇒ A1 成立：残差**完全**由聚合口径解释 —— 同一批命中数，宏平均得 0.1985、微平均得 0.2064。')
    console.info('     检索侧没有任何差异；0.2064 不是"另一个配置下的数"，而是换了分母。')
  }
  else if (!macroHit && !microHit) {
    console.info('  ⇒ A2 成立：两套聚合都不能复现对应历史值 ⇒ 还缺变量，如实报告，不回推、不估算。')
  }
  else {
    console.info('  ⇒ 部分复现：只有一套聚合对上，说明聚合口径**不是**唯一变量，仍缺变量。')
  }

  const artifact = {
    generatedAt: new Date().toISOString(),
    experiment: 'j5-aggregation-caliber',
    question: '0.1985 与 0.2064 之差是否只是宏平均/微平均的聚合口径差',
    corpus: { path, sha256: sha, conversations: convs.length },
    condition: 'NO_GATING（不门控、不剪枝）',
    buildConfigDriftConvs: configDrift,
    hitCriterion: 'c.score > mem.config.retrievalFloor（0.02），c.score 为本臂自身分数；每题一次 retrieve(topK=8)',
    aggregation: {
      macro: '每对话先算 hits/qa，再对各对话取均值（p2-quantile-retention-sweep.ts:172 口径）',
      micro: '所有题的 0/1 pooled 后除以总题数（j5-rrf-e2e-decomposition.ts:207 口径）',
    },
    perConvQuestions: perConv.map(c => ({ conv: c.conv, qa: c.qa, recall: Object.fromEntries(KS.map(k => [k, c.hits[k] / c.qa])) })),
    totals: { totalQuestions: totalQ, hitsAt8: totalHits8 },
    macro,
    micro,
    deltaMicroMinusMacro: Object.fromEntries(KS.map(k => [k, micro[k] - macro[k]])),
    targets: TARGETS,
    reproduced: { macroVs_p2quantile0919: macroHit, microVs_storeDefault: microHit },
    caliber: {
      family: '族 B（端到端，全池）',
      doNotCompareWith: '族 A（j5-rrf-ablation，重排 top-150）',
      granularity: 'turn 级（LoCoMo dia_id）；与 LongMemEval session 级不可相减',
    },
  }
  const prov = withProvenance(artifact)
  const out = join('eval', 'results', 'j5-aggregation-caliber-2026-10-03.json')
  mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, `${JSON.stringify(prov, null, 2)}\n`)
  console.info()
  console.info(`artifact: ${out}`)
  console.info(`provenance: scoreMode=${prov.provenance.scoreMode} gitSha=${prov.provenance.gitSha} gitDirty=${prov.provenance.gitDirty}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
