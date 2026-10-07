/**
 * 任务 #20-(1)：0.1985 vs 0.2064 的**实证复现**（不是重找根因）。
 *
 * ── 待解释的事实 ─────────────────────────────────────────────────────────
 * 两个数都自陈为"基线：无门控、不剪枝"、10 对话、K=8、recall@8，但不相等：
 *
 *   · `0.1985` —— `eval/results/p2-quantile-retention-sweep-2026-09-19.json`
 *     的 `arms["baseline-nogating"]`（generatedAt 2026-09-19T11:42:14.619Z，
 *     poolSize 1176.4）。
 *   · `0.2064` —— 本仓库族 B 端到端臂 `store-default`
 *     （`j5-rrf-e2e-decomposition` / `j5-rrf-ablation`，
 *     generatedAt 2026-10-02/03，standardized + 去重）。
 *
 * 差 +0.0079。`j5-caliber-verification` 已把差异**定位到代码行**：
 * 建库时显著性来源不同 ——
 *   · `p2-quantile-retention-sweep.ts:163` 走
 *     `buildMemory(conv, gating, undefined, { salienceOf })`，注入
 *     `sigmoid(predictSalienceV2(content, ctx))`；
 *   · `j5-rrf-ablation.ts:333` / `j5-rrf-e2e-decomposition.ts:178` 走
 *     `buildMemory(conv, NO_GATING)`，不传第 3/4 参 ⇒ 用 store 默认显著性。
 * 显著性经 `store.ts:254-255` 的 `salienceOverride` 分支进入
 * `encoding.salience`，再进 `retrievalStrength` ⇒ 排序不同。
 *
 * 但**"定位到代码行"不等于"复现"**：根因若成立，把显著性来源单独切回去，
 * 两臂的差应当恰好等于 0.1985 与 0.2064 的差。本脚本就是做这个受控验证。
 *
 * ── 设计（唯一自变量 = 显著性来源）────────────────────────────────────────
 * 两臂**共用**：同一 `NO_GATING`（不门控、不剪枝）、同一默认 `distiller`、
 * 同一 `retrievalScoreMode`（standardized）、同一 `dedupeByContent`（true）、
 * 同一 `weights`、同一 `retrievalFloor`、同一 `measure()`（`./eval-metrics`，
 * 与 p2-quantile 逐位同定义）。
 * **唯一差别**：A 臂注入 `salienceOf`（p2-quantile 式），B 臂不注入（store 默认式）。
 * 脚本对两臂的 config 做逐字段断言，不一致直接抛错 —— 防止"名义受控"。
 *
 * ── 预注册读法（先写下来再跑）────────────────────────────────────────────
 *   R1 若 A 臂 ≈ 0.1985 且 B 臂 ≈ 0.2064（|Δ| 在各位 4 位小数内相符）
 *      ⇒ 显著性来源**充分解释**该分歧，任务闭合。
 *   R2 若两臂 recall@8 相同（|Δ| < 0.0005）但 poolSize 也相同
 *      ⇒ 显著性来源**不解释**该分歧；此时须如实说"还缺哪个变量"，
 *         不得回推、不得估算。
 *   R3 无论 R1/R2 哪个成立，都必须报 `poolSize` 与 `encoding.salience`
 *      的实际分布 —— 若两臂池子大小不同，则"显著性"与"池规模"被混淆，
 *      R1 不成立。
 *
 * ── 口径声明（引用前必读）────────────────────────────────────────────────
 *   · 本表属**族 B（端到端）**：`measure()` 每题只调一次 `retrieve(topK=8)`
 *     再按位置还原 R@1/2/4。与族 A（`j5-rrf-ablation`，重排 top-150）**不可互比**。
 *   · 命中判据为 `c.score > mem.config.retrievalFloor`（默认 0.02），
 *     `c.score` 是**本臂自身**分数。两臂同为 standardized ⇒ 阈值语义相同。
 *   · 粒度：turn 级（LoCoMo `dia_id`），与 LongMemEval 的 session 级**不可相减**。
 *
 * 用法：tsx eval/j5-salience-source-repro.ts [path] [conv-limit]
 */
import type { BioticMemory, GatingCoefficients } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { buildMemory, loadLocomo, NO_GATING, predictSalienceV2 } from '../src/index'
import { withProvenance } from './artifact-provenance'
import { avg, goldEvidenceIds, KS, measure } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

/** 两个待解释的历史值（引用来源写进产物，便于核对，不做任何回推）。 */
const TARGETS = {
  /** p2-quantile-retention-sweep-2026-09-19.json · arms["baseline-nogating"]。 */
  p2quantile0919: 0.19853236649084932,
  /** 族 B 端到端 store-default（j5-rrf-e2e-decomposition / j5-rrf-ablation）。 */
  storeDefault: 0.20644511581067473,
} as const

interface ArmSpec {
  key: string
  note: string
  /** 是否注入 p2-quantile 式 `salienceOf`。 */
  injectPredSalience: boolean
}

const ARMS: ArmSpec[] = [
  { key: 'pred-salience', note: '注入 salienceOf = sigmoid(predictSalienceV2(content, ctx))，p2-quantile 式', injectPredSalience: true },
  { key: 'default-salience', note: '不传第 3/4 参 ⇒ store 默认显著性（本仓库族 B 各臂的写法）', injectPredSalience: false },
]

/** 两臂必须逐字段相同，否则本实验不是"只切显著性来源"。 */
function assertSameConfig(a: BioticMemory, b: BioticMemory): void {
  const keys = ['retrievalScoreMode', 'dedupeByContent', 'retrievalFloor'] as const
  for (const k of keys) {
    if (a.config[k] !== b.config[k])
      throw new Error(`两臂 ${k} 不同：${String(a.config[k])} vs ${String(b.config[k])} —— 存在显著性以外的变量，本实验无效`)
  }
  const wa = JSON.stringify(a.config.weights)
  const wb = JSON.stringify(b.config.weights)
  if (wa !== wb)
    throw new Error(`两臂 weights 不同：${wa} vs ${wb} —— 存在显著性以外的变量，本实验无效`)
}

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const all = loadLocomo(path)
  const convs = limit ? all.slice(0, limit) : all
  const sha = sha256File(path)

  console.info('=== 显著性来源受控复现：0.1985（p2-quantile 式） vs 0.2064（store 默认式）===')
  console.info(`corpus : ${path}`)
  console.info(`sha256 : ${sha}`)
  console.info(`convs  : ${convs.length}${limit ? `（limit=${limit}）` : ''}`)
  console.info(`唯一自变量：显著性来源；其余字段逐项断言相同`)
  console.info()

  const acc: Record<string, { recall: Record<number, number[]>, surv: number[], pool: number[] }> = {}
  for (const a of ARMS)
    acc[a.key] = { recall: Object.fromEntries(KS.map(k => [k, [] as number[]])), surv: [], pool: [] }

  let questions = 0
  let configChecked = 0
  // 显著性机制证据：两臂下 episode 的 encoding.salience 分布差异。
  const sal: Record<string, { diff: number[], pred: number[], def: number[] }> = {
    'pred-salience': { diff: [], pred: [], def: [] },
    'default-salience': { diff: [], pred: [], def: [] },
  }

  for (const conv of convs) {
    const gold = goldEvidenceIds(conv)

    // 与 p2-quantile-retention-sweep.ts:144 逐字同构：ctx 为空先验。
    const ctx = { priors: [] as string[], idf: new Map<string, number>(), nDocs: 1 }
    const predSal = conv.episodes.map(ep => 1 / (1 + Math.exp(-predictSalienceV2(ep.content, ctx).score)))
    const idxOf = new Map(conv.episodes.map((ep, i) => [ep.id, i]))

    const built: Record<string, BioticMemory> = {}
    for (const arm of ARMS) {
      built[arm.key] = arm.injectPredSalience
        ? await buildMemory(conv, NO_GATING as GatingCoefficients, undefined, {
            salienceOf: ({ id }) => {
              const i = idxOf.get(id)
              return i === undefined ? undefined : predSal[i]
            },
          })
        : await buildMemory(conv, NO_GATING as GatingCoefficients)
    }
    assertSameConfig(built['pred-salience'], built['default-salience'])
    configChecked++

    // 显著性分布对照（同一批 id，两臂分别取值）。
    const defById = new Map(built['default-salience'].episodes.map(e => [e.id, e.encoding.salience]))
    for (const e of built['pred-salience'].episodes) {
      sal['pred-salience'].pred.push(e.encoding.salience)
      const d = defById.get(e.id)
      if (d !== undefined) {
        sal['pred-salience'].def.push(d)
        sal['pred-salience'].diff.push(e.encoding.salience - d)
      }
    }

    for (const arm of ARMS) {
      const m = measure(built[arm.key], conv, gold)
      for (const k of KS) acc[arm.key].recall[k].push(m.recall[k])
      acc[arm.key].surv.push(m.evidenceSurvival)
      acc[arm.key].pool.push(m.poolSize)
    }
    questions += conv.qa.length
  }

  const armsOut = ARMS.map((a) => {
    const r = acc[a.key]
    return {
      arm: a.key,
      note: a.note,
      recall: Object.fromEntries(KS.map(k => [k, avg(r.recall[k])])),
      evidenceSurvival: avg(r.surv),
      poolSize: avg(r.pool),
    }
  })

  const [pred, def] = armsOut
  const delta8 = pred.recall[8] - def.recall[8]
  const poolDelta = pred.poolSize - def.poolSize

  console.info(`  ${'arm'.padEnd(18)}${KS.map(k => `R@${k}`.padStart(10)).join('')}${'poolSize'.padStart(12)}${'evSurv'.padStart(9)}`)
  for (const a of armsOut)
    console.info(`  ${a.arm.padEnd(18)}${KS.map(k => a.recall[k].toFixed(6).padStart(10)).join('')}${a.poolSize.toFixed(1).padStart(12)}${a.evidenceSurvival.toFixed(4).padStart(9)}`)
  console.info()
  console.info(`  断言通过：${configChecked}/${convs.length} 个对话的两臂 config（mode/dedupe/floor/weights）逐字段相同 ✅`)
  console.info()

  // 显著性机制证据。
  const d = sal['pred-salience'].diff
  const nDiff = d.filter(x => Math.abs(x) > 1e-12).length
  console.info('  显著性机制（episode.encoding.salience，同一批 id）：')
  console.info(`    pred 臂均值    ${avg(sal['pred-salience'].pred).toFixed(6)}`)
  console.info(`    default 臂均值 ${avg(sal['pred-salience'].def).toFixed(6)}`)
  console.info(`    差值均值       ${avg(d).toFixed(6)}   |差|>1e-12 的条数 ${nDiff}/${d.length}`)
  console.info()

  // 与两个历史值对照（复现 / 未复现，如实报告）。
  const near = (x: number, y: number) => Math.abs(x - y) < 5e-5
  console.info('  与历史值对照（判据 |Δ| < 5e-5 即视为复现）：')
  console.info(`    pred-salience    R@8 ${pred.recall[8].toFixed(6)}  vs 0.198532 (p2-quantile 09-19)  ${near(pred.recall[8], TARGETS.p2quantile0919) ? '✅ 复现' : '❌ 未复现'}   Δ=${(pred.recall[8] - TARGETS.p2quantile0919).toFixed(6)}`)
  console.info(`    default-salience R@8 ${def.recall[8].toFixed(6)}  vs 0.206445 (store-default)   ${near(def.recall[8], TARGETS.storeDefault) ? '✅ 复现' : '❌ 未复现'}   Δ=${(def.recall[8] - TARGETS.storeDefault).toFixed(6)}`)
  console.info()
  console.info(`  两臂差 ΔR@8 = ${delta8.toFixed(6)}   历史两数差 = ${(TARGETS.storeDefault - TARGETS.p2quantile0919).toFixed(6)}`)
  console.info(`  池大小差 ΔpoolSize = ${poolDelta.toFixed(4)}`)
  console.info()
  console.info('  判读（由上方实测数字生成，无硬编码结论）：')
  const reproducedBoth = near(pred.recall[8], TARGETS.p2quantile0919) && near(def.recall[8], TARGETS.storeDefault)
  if (Math.abs(poolDelta) < 0.05) {
    if (reproducedBoth) {
      console.info('  ⇒ R1 成立：仅切显著性来源即复现两个历史值 ⇒ 显著性来源**充分解释** 0.1985 vs 0.2064 的分歧。')
      console.info('     且两臂池大小相同 ⇒ 无池规模混淆（R3 通过）。')
    }
    else if (Math.abs(delta8) < 5e-4) {
      console.info('  ⇒ R2 成立：两臂 recall@8 实质相同 ⇒ 显著性来源**不解释**该分歧。')
      console.info('     缺口：还缺哪个变量未确定 —— 如实报告，不回推、不估算。')
    }
    else {
      console.info('  ⇒ 两臂均未复现对应历史值，且两臂互不相等 ⇒ 存在第三变量，不能归因于显著性来源。')
    }
  }
  else {
    console.info(`  ⇒ ⚠️ 两臂池大小不同（Δ=${poolDelta.toFixed(2)}）⇒ 显著性与池规模被混淆，R1 不成立，需另设实验拆开。`)
  }

  const artifact = {
    generatedAt: new Date().toISOString(),
    experiment: 'j5-salience-source-repro',
    question: '0.1985（p2-quantile 式显著性）vs 0.2064（store 默认显著性）在受控只切显著性来源下能否各自复现',
    corpus: { path, sha256: sha, conversations: convs.length },
    condition: 'NO_GATING（不门控、不剪枝）',
    controlledVariable: 'salience source only',
    configAsserted: { fields: ['retrievalScoreMode', 'dedupeByContent', 'retrievalFloor', 'weights'], convsChecked: configChecked },
    measure: 'eval-metrics.measure（每题一次 retrieve(topK=8)，与 p2-quantile 逐位同定义）',
    hitCriterion: 'c.score > mem.config.retrievalFloor（0.02），c.score 为本臂自身分数',
    caliber: {
      family: '族 B（端到端，全池）',
      doNotCompareWith: '族 A（j5-rrf-ablation，重排 top-150）',
      granularity: 'turn 级（LoCoMo dia_id）；与 LongMemEval session 级不可相减',
    },
    targets: TARGETS,
    questions,
    arms: armsOut,
    deltaRecall8_predMinusDefault: delta8,
    deltaPoolSize: poolDelta,
    salienceMechanism: {
      predMean: avg(sal['pred-salience'].pred),
      defaultMean: avg(sal['pred-salience'].def),
      diffMean: avg(d),
      diffCount: d.length,
      diffNonZero: nDiff,
    },
    reproduced: {
      predSalienceVs_p2quantile0919: near(pred.recall[8], TARGETS.p2quantile0919),
      defaultSalienceVs_storeDefault: near(def.recall[8], TARGETS.storeDefault),
    },
  }
  const prov = withProvenance(artifact)
  const out = join('eval', 'results', 'j5-salience-source-repro-2026-10-03.json')
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
