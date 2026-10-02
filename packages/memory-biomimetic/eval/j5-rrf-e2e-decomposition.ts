import type { BioticMemory, GatingCoefficients, RetrievalScoreMode, RetrievalWeights } from '../src/index'

import process from 'node:process'

/**
 * 端到端口径（族 B）复跑：RRF 在**全池**上到底值多少？
 *
 * ── 为什么另起一个脚本 ──────────────────────────────────────────────────
 * `eval/j5-rrf-ablation.ts`（族 A）是**重排口径**：每题取 store 默认打分的前 150
 * 条，只用 `parts` 重新排序，且统一排除了检索噪声与冲突惩罚。它的数字（current
 * 0.0906 / sim-only 0.3580 / rrf 0.2422）是**上界/下界性质的人工对照**，不是
 * "系统实际交付的召回"。
 *
 * J5 §4.2 口径声明第 2 条已经点破：表里的 `current`(0.0906) **不等于** store 自身
 * 输出的 recall@8。而 store 自身输出才是能被引为"系统检索质量"的数。故本脚本
 * 只做**端到端**：改 store 的 `retrievalScoreMode` 配置，让 `retrieve()` 自己在
 * **全池（≈1176）**上打分并截断。
 *
 * ── 口径契约（族 A / 族 B 不得混用）────────────────────────────────────
 * 族 A（重排，top-150，`parts` 重排，排除噪声与冲突惩罚）与族 B（端到端，全池，
 * 含噪声与冲突惩罚）是**两个独立的口径族**。族内可比，**跨族并列即假结论**。
 * 本脚本的全部数字属族 B；基线**只能**配本脚本同批跑出的 `store-default`，
 * 不得配族 A 的 0.0906 / 0.3580 / 0.2422。
 *
 * ── 同 build 保证 ───────────────────────────────────────────────────────
 * 每个对话**只 build 一次**，随后通过翻转 `mem.config` 的
 * `retrievalScoreMode` / `dedupeByContent` / `weights` 在同一实例上跑各臂。
 * `retrieve(..., bump = false)` 不写 accessCount，且未启用 HAC，故各臂面对的是
 * 逐字相同的记忆实例——不存在跨 build 漂移。
 *
 * ── 臂 ──────────────────────────────────────────────────────────────────
 *   store-default        standardized + 去重   ← 基线（族 B 唯一基线）
 *   rrf-e2e              rrf + 去重
 *   rrf-e2e-no-recency   rrf + 去重 + CORRECTED 权重
 *   additive-e2e         additive + 去重        ← 与基线对照，隔离打分模式
 *   prefix-e2e           additive + **不去重**  ← 014b17b 之前配置的**近似**
 *
 * 后两臂用于把历史数字 0.0817（09-15 制品）→ 0.1985 / 0.2064（修复后）拆成
 * "去重的贡献"与"打分模式的贡献"——13 号文档 §2.4 把这段因果标为**推断、未重跑**，
 * 本脚本即为那次受控重跑。
 *
 * ── 指标 ────────────────────────────────────────────────────────────────
 * · recall@K：与 `eval/eval-metrics.ts` 的 `measure()` 逐位同定义（top-K 中有金
 *   标准证据且 `score > retrievalFloor` 的题目比例，分母为全部题目）。本脚本用
 *   `measure()` 对基线臂做一次**交叉校验**，证明自己没有写歪。
 * · MRR@8：top-8 中首个金标准（且过 floor）名次的倒数，未命中记 0。
 * · **不报 NDCG**：IDCG 需要"池中金标准总数"，而在端到端 top-8 截断下该量不可知，
 *   硬凑只会造出一个无法复核的数。宁缺。
 *
 * ── 已知限制 ────────────────────────────────────────────────────────────
 * · `additive` 两臂沿用 legacy 的 **K 依赖**冲突重排头（`penaltyHead = topK`），
 *   故其 recall@1/2/4 是"从一次 topK=8 的检索里按位置还原"得来的，**不等于**
 *   逐 K 各调一次 `retrieve()`。这是 legacy 路径的固有性质，不是脚本缺陷；
 *   standardized 与 rrf 两臂无此问题（K 无关的常量头）。
 *
 * ── 文件名说明 ────────────────────────────────────────────────────────────
 * 本脚本原名 `j5-rrf-e2e.ts`，与 `j5-rrf-e2e-independent.ts`（另一名成员的独立
 * 复核脚本）发生过**同路径写冲突**。为避免产物互相覆盖，本脚本改名为
 * `-decomposition`，产物前缀 `j5-rrf-e2e-decomp-*`。
 * 两者的分工：对方脚本负责 rrf / standardized 各权重档的端到端对照；本脚本负责
 * 0.0817 → 修复后 的**因果拆分**（去重 vs 打分模式），并自带 recall 实现交叉校验。
 *
 * 用法：tsx eval/j5-rrf-e2e-decomposition.ts [path-to-locomo.json] [conv-limit]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import {
  buildMemory,
  CORRECTED_RETRIEVAL_WEIGHTS,
  DEFAULT_MEMORY_CONFIG,
  loadLocomo,
  NO_GATING,
} from '../src/index'
import { withProvenance } from './artifact-provenance'
import { avg, KS, measure } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

const MAXK = Math.max(...KS)

interface E2EArm {
  key: string
  note: string
  scoreMode: RetrievalScoreMode
  dedupeByContent: boolean
  weights: RetrievalWeights
  /** 族 B 的唯一基线。 */
  baseline?: boolean
}

const ARMS: E2EArm[] = [
  {
    key: 'store-default',
    note: '【基线】standardized + 去重（014b17b 后的 shipped path）',
    scoreMode: 'standardized',
    dedupeByContent: true,
    weights: DEFAULT_MEMORY_CONFIG.weights,
    baseline: true,
  },
  {
    key: 'rrf-e2e',
    note: 'rrf（k=60）+ 去重 + DEFAULT 权重',
    scoreMode: 'rrf',
    dedupeByContent: true,
    weights: DEFAULT_MEMORY_CONFIG.weights,
  },
  {
    key: 'rrf-e2e-no-recency',
    note: 'rrf + 去重 + CORRECTED 权重（recency 置 0）',
    scoreMode: 'rrf',
    dedupeByContent: true,
    weights: CORRECTED_RETRIEVAL_WEIGHTS,
  },
  {
    key: 'std-no-dedupe',
    note: 'standardized + **不去重**（隔离去重，打分模式与基线相同）',
    scoreMode: 'standardized',
    dedupeByContent: false,
    weights: DEFAULT_MEMORY_CONFIG.weights,
  },
  {
    key: 'additive-e2e',
    note: 'additive + 去重（隔离打分模式，去重条件与基线相同）',
    scoreMode: 'additive',
    dedupeByContent: true,
    weights: DEFAULT_MEMORY_CONFIG.weights,
  },
  {
    key: 'prefix-e2e',
    note: 'additive + 不去重 —— 014b17b 之前配置的**近似**（推断，非实测确证）',
    scoreMode: 'additive',
    dedupeByContent: false,
    weights: DEFAULT_MEMORY_CONFIG.weights,
  },
]

/** 把 store 的检索配置切成某一臂。就地改，保证"同 build"。 */
function applyArm(mem: BioticMemory, arm: E2EArm): void {
  mem.config.retrievalScoreMode = arm.scoreMode
  mem.config.dedupeByContent = arm.dedupeByContent
  mem.config.weights = { ...arm.weights }
}

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== 端到端口径（族 B）：全池、含噪声与冲突惩罚 ===')
  console.info(`corpus   : ${path}`)
  console.info(`sha256   : ${sha256File(path)}`)
  console.info(`convs    : ${convs.length}`)
  console.info(`condition: NO_GATING；每题 retrieve(topK=${MAXK}, bump=false)`)
  console.info(`同 build : 每对话 build 一次，翻转 mem.config 跑各臂`)
  console.info(`⚠️ 本表属族 B，与族 A（j5-rrf-ablation，重排 top-150）**不可互比**`)
  console.info()

  const recall: Record<string, Record<number, number[]>> = {}
  const mrr: Record<string, number[]> = {}
  for (const a of ARMS) {
    recall[a.key] = Object.fromEntries(KS.map(k => [k, [] as number[]]))
    mrr[a.key] = []
  }
  let questions = 0

  // 交叉校验：基线臂用仓库共用的 `measure()` 再算一遍，确认本脚本的 recall 没写歪。
  const crossCheck: number[] = []

  for (const conv of convs) {
    const gold = new Set<string>()
    for (const q of conv.qa) {
      for (const e of q.evidence ?? []) {
        if (conv.evidenceIds.has(e))
          gold.add(e)
      }
    }
    const mem = await buildMemory(conv, NO_GATING as GatingCoefficients)

    const perQuestion = conv.qa.map((q) => {
      const cand = new Set<string>()
      for (const e of q.evidence ?? []) {
        if (!conv.evidenceIds.has(e))
          continue
        cand.add(e)
        cand.add(`fact_${e}`)
      }
      return { question: q.question, cand }
    })
    questions += perQuestion.length

    for (const arm of ARMS) {
      applyArm(mem, arm)
      const floor = mem.config.retrievalFloor
      // 本对话内基线臂的逐题命中，仅用于与 `measure()` 的**逐对话**交叉校验。
      const convHit: Record<number, number[]> = Object.fromEntries(KS.map(k => [k, [] as number[]]))
      for (const pq of perQuestion) {
        const ranking = mem.retrieve(pq.question, MAXK, false)
        const hitAtK: Record<number, boolean> = Object.fromEntries(KS.map(k => [k, false]))
        let rr = 0
        for (let i = 0; i < ranking.length; i++) {
          const c = ranking[i]
          if (!pq.cand.has(c.id) || !(c.score > floor))
            continue
          if (rr === 0)
            rr = 1 / (i + 1)
          for (const k of KS) {
            if (i + 1 <= k)
              hitAtK[k] = true
          }
        }
        for (const k of KS) {
          recall[arm.key][k].push(hitAtK[k] ? 1 : 0)
          if (arm.baseline)
            convHit[k].push(hitAtK[k] ? 1 : 0)
        }
        mrr[arm.key].push(rr)
      }

      if (arm.baseline) {
        // 同一对话、同一配置，用仓库共用的实现再算一遍。
        const shared = measure(mem, conv, gold)
        for (const k of KS)
          crossCheck.push(shared.recall[k] - avg(convHit[k]))
      }
    }
  }

  // ---------------------------------------------------------------- 输出
  const row = (a: E2EArm) =>
    `  ${a.key.padEnd(20)}${KS.map(k => avg(recall[a.key][k]).toFixed(4).padStart(9)).join('')}${avg(mrr[a.key]).toFixed(4).padStart(9)}   ${a.note}`
  console.info(`  ${'arm'.padEnd(20)}${KS.map(k => `R@${k}`.padStart(9)).join('')}${'MRR@8'.padStart(9)}`)
  for (const a of ARMS) console.info(row(a))
  console.info()

  // ---------------------------------------------------------------- 校验
  const maxCross = Math.max(...crossCheck.map(Math.abs))
  console.info('--- 校验 ---')
  console.info(`  recall 实现交叉校验（对标 eval-metrics.measure）：最大偏差 ${maxCross.toFixed(6)}  ${maxCross < 1e-9 ? '✅ 逐位一致' : '❌ 口径写歪了'}`)
  console.info('  历史数字对照（来自 13 号文档 §2.4，仅作定位，非本脚本产物）：')
  console.info(`    014b17b 之前基线（09-15 制品） 0.0817  ← 本脚本 prefix-e2e    ${avg(recall['prefix-e2e'][MAXK]).toFixed(4)}`)
  console.info(`    014b17b 之后基线（09-19 制品） 0.1985  ← 本脚本 store-default ${avg(recall['store-default'][MAXK]).toFixed(4)}`)
  console.info('    注：0.0817 / 0.1985 是历史制品，其配置是本脚本的**推断**，未独立确证。')
  console.info()

  // ---------------------------------------------------------------- 判读
  const R = (key: string) => avg(recall[key][MAXK])
  const base = R('store-default')
  const rrf = R('rrf-e2e')
  const rrfNoRec = R('rrf-e2e-no-recency')
  const add = R('additive-e2e')
  const pre = R('prefix-e2e')
  const stdNoDedup = R('std-no-dedupe')
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`

  const verdicts: string[] = []
  verdicts.push(`【① 端到端 recall@${MAXK}（族 B）】`)
  verdicts.push(`  store-default      ${base.toFixed(4)}   （族 B 唯一基线）`)
  verdicts.push(`  rrf-e2e            ${rrf.toFixed(4)}   ${fmt(rrf - base)}`)
  verdicts.push(`  rrf-e2e-no-recency ${rrfNoRec.toFixed(4)}   ${fmt(rrfNoRec - base)}`)
  verdicts.push('')
  verdicts.push(`【② 0.0817 → 修复后 的因果拆分（13 号文档 §2.4 的受控重跑）】`)
  verdicts.push(`  additive + 不去重      ${pre.toFixed(4)}   （014b17b 前配置的近似）`)
  verdicts.push(`  additive + 去重        ${add.toFixed(4)}   ${fmt(add - pre)}  ← additive 下去重的贡献`)
  verdicts.push(`  standardized + 不去重  ${stdNoDedup.toFixed(4)}   ${fmt(stdNoDedup - pre)}  ← 打分模式的贡献（去重条件相同）`)
  verdicts.push(`  standardized + 去重    ${base.toFixed(4)}   ${fmt(base - stdNoDedup)}  ← standardized 下去重的贡献`)
  verdicts.push('')
  verdicts.push(`  ⇒ 两条路径都试过了：去重的贡献是 ${fmt(add - pre)}（additive 下）与 ${fmt(base - stdNoDedup)}（standardized 下），`)
  verdicts.push(`     打分模式的贡献是 ${fmt(stdNoDedup - pre)}（去重条件不变）。谁主导一目了然。`)
  verdicts.push('')
  verdicts.push('【③ 结论】')
  if (rrf > base + 0.005) {
    verdicts.push(`  ⇒ 端到端 RRF ${rrf.toFixed(4)} **优于** shipped 默认 ${base.toFixed(4)}（${fmt(rrf - base)}）。`)
  }
  else if (rrf < base - 0.005) {
    verdicts.push(`  ⇒ 端到端 RRF ${rrf.toFixed(4)} **劣于** shipped 默认 ${base.toFixed(4)}（${fmt(rrf - base)}）。`)
  }
  else {
    verdicts.push(`  ⇒ 端到端 RRF ${rrf.toFixed(4)} 与 shipped 默认 ${base.toFixed(4)} **无实质差异**（${fmt(rrf - base)}）。`)
  }
  verdicts.push('')
  verdicts.push('⚠️ 口径：本表全部数字属**族 B（端到端、全池、含噪声与冲突惩罚）**，')
  verdicts.push('   基线只能配本表的 store-default；与族 A（j5-rrf-ablation，重排 top-150）的任何数字都不可相减。')
  verdicts.push('   additive 两臂沿用 legacy 的 K 依赖冲突重排头，其 R@1/2/4 由一次 topK=8 检索按位置还原，')
  verdicts.push('   不等于逐 K 各调一次 retrieve()。')

  console.info('--- 判读（由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts) console.info(v)

  // ---------------------------------------------------------------- 产物
  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })

  const payloadFor = (a: E2EArm) => ({
    arm: a.key,
    note: a.note,
    baseline: a.baseline === true,
    config: {
      retrievalScoreMode: a.scoreMode,
      dedupeByContent: a.dedupeByContent,
    },
    questions,
    recall: Object.fromEntries(KS.map(k => [k, avg(recall[a.key][k])])),
    mrrAtMaxK: avg(mrr[a.key]),
  })

  const written: string[] = []
  for (const a of ARMS) {
    const p = join(outDir, `j5-rrf-e2e-decomp-${a.key}-${stamp}.json`)
    writeFileSync(p, `${JSON.stringify(withProvenance({
      generatedAt: new Date().toISOString(),
      experiment: 'j5-rrf-e2e',
      calibrationFamily: 'B-end-to-end',
      corpus: { path, sha256: sha256File(path), conversations: convs.length },
      condition: 'NO_GATING',
      topK: MAXK,
      ks: KS,
      ...payloadFor(a),
    }, { scoreMode: a.scoreMode, weights: a.weights }), null, 2)}\n`, 'utf8')
    written.push(p)
  }

  const summaryPath = join(outDir, `j5-rrf-e2e-decomp-${stamp}.json`)
  writeFileSync(summaryPath, `${JSON.stringify(withProvenance({
    generatedAt: new Date().toISOString(),
    experiment: 'j5-rrf-e2e',
    calibrationFamily: 'B-end-to-end',
    corpus: { path, sha256: sha256File(path), conversations: convs.length },
    condition: 'NO_GATING',
    topK: MAXK,
    ks: KS,
    questions,
    arms: ARMS.map(a => ({ ...payloadFor(a), scoreMode: a.scoreMode, weights: a.weights })),
    calibration: {
      recallImplementationMaxDeltaVsMeasure: maxCross,
      historical: {
        note: '历史制品数字，仅作定位；其配置为本脚本的推断，未独立确证。',
        before014b17b_2026_09_15: 0.0817,
        after014b17b_2026_09_19: 0.1985,
      },
    },
    verdicts,
  }), null, 2)}\n`, 'utf8')
  written.push(summaryPath)

  console.info()
  for (const p of written) console.info(`artifact: ${p}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
