/**
 * 嵌套交叉验证审计（可发表性前提） —— **只审计，不改实验逻辑**。
 *
 * 目标：把 `p2-salience-probe.ts` 报出的 LOCV=0.812 里"特征选择泄漏"的贡献量化出来，
 * 并独立核查是否存在其它形式的标签/测试折泄漏。
 *
 * 三层对照（都在本脚本内用同一套特征与同一套拟合代码跑，保证可比）：
 *   1) LOCV-original ：完全复刻 probe.ts —— 全语料 standardize + 13 特征全用 + 留一对话拟权重。
 *                      预期 ≈0.812，用来确认本脚本复刻无误。
 *   2) LOCV-trainStd  ：同上，但 standardize 的均值/方差**只**算在训练折 9 对话上（修正一种泄漏）。
 *                      与 (1) 的差 = standardize 把测试折算进去的残留乐观偏倚。
 *   3) Nested-Train   ：外层留一对话；**内层在 9 个训练对话上做贪心前向特征选择**
 *                      （选择准则 = 这 9 个对话的平均 AUC，未做二次嵌套 / 见报告），
 *                      再在训练折上拟权重、预测第 10 个对话。
 *                      这才是可写进论文的诚实 pooled AUC。
 *                      (2) 与 (3) 的差 ≈ 特征选择泄漏贡献；(1) 与 (3) 的差 = 总泄漏。
 *
 * 另外独立核查：
 *   - buildIdf/tokenize 是否接触 evidenceIds 或 encoding（标签代理）。
 *   - buildRows 的 priors 是否严格因果（仅当前 turn 之前）。
 *   - standardize 的统计量算在哪些样本上。
 *   - probe.ts LOCV 用 rows.indexOf(r) 回填分数是否与行对齐（抽查 + 一致性断言）。
 *
 * Usage: tsx eval/p2-salience-nested.ts [path-to-locomo.json]
 */
import type { LocomoConversation } from '../src/index'

import process from 'node:process'

import { auc, buildExperimentManifest, loadLocomo, registerExperimentManifest, tokenize } from '../src/index'
import { resolveLocomoPath } from './locomo-path'

// ============================================================ 复刻 probe.ts 的特征与拟合（审计保真，逐字复制）

interface Ctx {
  priors: string[]
  idf: Map<string, number>
  nDocs: number
}

interface FeatureDef {
  name: string
  fn: (text: string, ctx: Ctx) => number
}

const STOP = new Set(['the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'am', 'to', 'of', 'and', 'or', 'but', 'in', 'on', 'at', 'it', 'this', 'that', 'i', 'you', 'he', 'she', 'we', 'they', 'my', 'your', 'his', 'her', 'our', 'their', 'for', 'with', 'as', 'so', 'if', 'then', 'than', 'do', 'does', 'did', 'have', 'has', 'had', 'not', 'no', 'yes'])

const BACKCHANNEL = /^(?:oh|ah|hmm|haha+|hehe+|lol|yeah+|yes+|yep|yup|nope|no+|(?:ok(?:ay)?)+|sure|right|true|wow|oops|hey|hi+|hello+|bye+|thanks?|thank you|really\??|what\??|huh\??|m{2,}|uh+|um+|alright|got it|i see|of course|exactly|definitely|absolutely|me too|same here)\b/i
const PAST_VERB = /\b(?:was|were|went|did|had|saw|got|took|made|came|said|told|bought|visited|met|started|finished|moved|found|lost|gave|ate|drank|played|watched|read|wrote|traveled|travelled|won|joined|graduated|adopted|married)\b/gi
const BE_VERB = /\b(?:is|am|are|was|were|be|been|being)\b/gi
const TIME_WORD = /\b(?:today|yesterday|tomorrow|last|next|ago|week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|morning|afternoon|evening|night|birthday|anniversary)\b/gi
const COMMIT = /\bi\s+(?:will|'ll|am\s+going\s+to|plan\s+to|need\s+to|want\s+to|have\s+to|decided\s+to|promise|hope\s+to)\b|\bmy\s+(?:favorite|favourite|birthday|name|wife|husband|mom|dad|dog|cat|son|daughter|brother|sister)\b|\bi\s+(?:like|love|hate|prefer|enjoy|always|never)\b/i

function count(re: RegExp, text: string): number {
  re.lastIndex = 0
  return (text.match(re) ?? []).length
}

function words(text: string): string[] {
  return text.toLowerCase().split(/\s+/).filter(Boolean)
}

const FEATURES: FeatureDef[] = [
  { name: 'length', fn: t => Math.min(1, Math.log1p(words(t).length) / Math.log1p(60)) },
  { name: 'contentDensity', fn: (t) => {
    const w = words(t)
    return w.length ? w.filter(x => !STOP.has(x)).length / w.length : 0
  } },
  { name: 'noveltyIdf', fn: (t, ctx) => {
    const w = words(t)
    if (!w.length || !ctx.priors.length)
      return 0.5
    const seen = new Set<string>()
    for (const p of ctx.priors.slice(-10)) {
      for (const x of words(p)) seen.add(x)
    }
    let newMass = 0
    let total = 0
    for (const x of w) {
      const w8 = ctx.idf.get(x) ?? Math.log1p(ctx.nDocs)
      total += w8
      if (!seen.has(x))
        newMass += w8
    }
    return total ? newMass / total : 0
  } },
  { name: 'meanIdf', fn: (t, ctx) => {
    const w = words(t)
    if (!w.length)
      return 0
    const max = Math.log1p(ctx.nDocs)
    return w.reduce((s, x) => s + (ctx.idf.get(x) ?? max), 0) / w.length / max
  } },
  { name: 'selfDisclosure', fn: t => Math.min(1, (count(/\b(?:i|my|me|mine|myself)\b/gi, t) + count(BE_VERB, t) * 0.5 + count(PAST_VERB, t) * 0.5) / 5) },
  { name: 'possessive', fn: t => Math.min(1, count(/\b(?:my|his|her|their|our|its)\b/gi, t) / 3) },
  { name: 'pastVerb', fn: t => Math.min(1, count(PAST_VERB, t) / 3) },
  { name: 'temporal', fn: t => Math.min(1, count(TIME_WORD, t) / 2) },
  { name: 'entity', fn: (t) => {
    const raw = t.split(/\s+/)
    let hits = 0
    for (let i = 0; i < raw.length; i++) {
      const w = raw[i].replace(/[^a-z0-9'-]/gi, '')
      if (!w)
        continue
      if (i > 0 && /^[A-Z][a-z]+$/.test(w))
        hits++
      else if (/\d/.test(w))
        hits++
    }
    return Math.min(1, hits / 3)
  } },
  { name: 'commitment', fn: t => (COMMIT.test(t) ? 1 : 0) },
  { name: 'isQuestion', fn: t => (t.includes('?') ? 1 : 0) },
  { name: 'isBackchannel', fn: t => (BACKCHANNEL.test(t.trim()) ? 1 : 0) },
  { name: 'secondPerson', fn: t => Math.min(1, count(/\b(?:you|your|yours|yourself)\b/gi, t) / 3) },
]

const ITERS = 600
const LR = 0.2
const LAMBDA = 1

interface Row {
  convIdx: number
  y: number
  x: number[]
}

function buildIdfLocal(convs: LocomoConversation[]): { idf: Map<string, number>, nDocs: number } {
  const df = new Map<string, number>()
  let nDocs = 0
  for (const c of convs) {
    for (const e of c.episodes) {
      nDocs++
      for (const t of new Set(tokenize(e.content))) df.set(t, (df.get(t) ?? 0) + 1)
    }
  }
  const idf = new Map<string, number>()
  for (const [t, d] of df) idf.set(t, Math.log1p(nDocs / d))
  return { idf, nDocs }
}

function buildRowsLocal(convs: LocomoConversation[], idf: Map<string, number>, nDocs: number): Row[] {
  const rows: Row[] = []
  for (let ci = 0; ci < convs.length; ci++) {
    const c = convs[ci]
    const priors: string[] = []
    for (const e of c.episodes) {
      rows.push({
        convIdx: ci,
        y: c.evidenceIds.has(e.id) ? 1 : 0,
        x: FEATURES.map(f => f.fn(e.content, { priors, idf, nDocs })),
      })
      priors.push(e.content)
    }
  }
  return rows
}

/**
 * 全局 standardize（逐字复刻 probe.ts：把**全语料**都算进去）。
 *
 * 累加器必须从 0 起算。这里曾写作 `fill(1)`，使 sd[j] 恒为
 * `1 + Σ(x−mean)²` 而非 `Σ(x−mean)²`，于是标准差被整体抬高。后果有二：
 *  ① 它就不是 probe.ts 的逐字复刻了（probe.ts 用 `fill(0)`），与文档声明不符；
 *  ② 本文件用它作为"全局标准化（有泄漏）"基线，与"仅训练折标准化"的
 *     `standardizeStats` 对比——但那两臂本就只该在**数据范围**上不同
 *     （全语料 vs 训练折）。`fill(1)` 引入了第二个变量（尺度），使这一消融
 *     无法把差异归因于泄漏。改回 0 后两臂只差数据范围。
 */
function standardize(rows: Row[]): { mean: number[], sd: number[] } {
  const dim = rows[0].x.length
  const mean = Array.from({ length: dim }).fill(0)
  const sd = Array.from({ length: dim }).fill(0)
  for (const r of rows) {
    for (let j = 0; j < dim; j++) mean[j] += r.x[j]
  }
  for (let j = 0; j < dim; j++) mean[j] /= rows.length
  for (const r of rows) {
    for (let j = 0; j < dim; j++) sd[j] += (r.x[j] - mean[j]) ** 2
  }
  for (let j = 0; j < dim; j++) sd[j] = Math.sqrt(sd[j] / rows.length) || 1
  for (const r of rows) {
    for (let j = 0; j < dim; j++) r.x[j] = (r.x[j] - mean[j]) / sd[j]
  }
  return { mean, sd }
}

/** 只在给定 rows 上算统计量（用于"训练折内"的标准化，避免测试折泄漏）。 */
function standardizeStats(rows: Row[]): { mean: number[], sd: number[] } {
  const dim = rows[0].x.length
  const mean = Array.from({ length: dim }).fill(0)
  const sd = Array.from({ length: dim }).fill(0)
  for (const r of rows) {
    for (let j = 0; j < dim; j++) mean[j] += r.x[j]
  }
  for (let j = 0; j < dim; j++) mean[j] /= rows.length
  for (const r of rows) {
    for (let j = 0; j < dim; j++) sd[j] += (r.x[j] - mean[j]) ** 2
  }
  for (let j = 0; j < dim; j++) sd[j] = Math.sqrt(sd[j] / rows.length) || 1
  return { mean, sd }
}

function applyStd(rows: Row[], s: { mean: number[], sd: number[] }): void {
  for (const r of rows) {
    for (let j = 0; j < r.x.length; j++) r.x[j] = (r.x[j] - s.mean[j]) / s.sd[j]
  }
}

function sigmoid(z: number): number {
  return z > 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z))
}

/** L2 正则逻辑回归（手写，与 probe.ts 同算法）。 */
function fitLogistic(X: number[][], y: number[], lambda = LAMBDA, iters = ITERS, lr = LR): number[] {
  const n = X.length
  const dim = X[0].length
  const w = new Float64Array(dim)
  const gw = new Float64Array(dim)
  let b = 0
  for (let it = 0; it < iters; it++) {
    gw.fill(0)
    let gb = 0
    for (let i = 0; i < n; i++) {
      const xi = X[i]
      let z = b
      for (let j = 0; j < dim; j++) z += xi[j] * w[j]
      const err = sigmoid(z) - y[i]
      for (let j = 0; j < dim; j++) gw[j] += err * xi[j]
      gb += err
    }
    for (let j = 0; j < dim; j++) w[j] -= lr * ((gw[j] + lambda * w[j]) / n)
    b -= lr * (gb / n)
  }
  const out = [b]
  for (let j = 0; j < dim; j++) out.push(w[j])
  return out
}

function predictScores(w: number[], X: number[][]): number[] {
  return X.map(x => x.reduce((s, v, j) => s + v * w[j + 1], w[0]))
}

function subX(rows: Row[], idx: number[]): number[][] {
  return rows.map((r) => {
    const v = Array.from({ length: idx.length })
    for (let k = 0; k < idx.length; k++) v[k] = r.x[idx[k]]
    return v
  })
}

// ============================================================ 审计 1&2：复刻 LOCV（全局 / 训练折内 standardize）

interface LocvResult {
  pooled: number
  perConv: number[]
  /** indexOf 回填分数与"按行预存索引"回填是否逐元素一致（验证 probe.ts 的对齐）。 */
  indexOfAligned: boolean
  spot: { idx: number, convIdx: number, y: number, score: number }[]
}

function locvReproduce(convs: LocomoConversation[], useTrainStd: boolean): LocvResult {
  const { idf, nDocs } = buildIdfLocal(convs) // 原始 probe 也是全语料建 IDF（无监督，不涉及标签）
  const rows = buildRowsLocal(convs, idf, nDocs)
  if (!useTrainStd)
    standardize(rows) // 全局 standardize（原始做法：测试折泄漏进统计量）

  const nConv = convs.length
  const locvScores = Array.from({ length: rows.length }).fill(Number.NaN)
  const perConv: number[] = []
  let indexOfAligned = true
  const spot: { idx: number, convIdx: number, y: number, score: number }[] = []

  for (let ci = 0; ci < nConv; ci++) {
    const tr = rows.filter(r => r.convIdx !== ci)
    const te = rows.filter(r => r.convIdx === ci)
    let Xtr: number[][]
    let Xte: number[][]
    if (useTrainStd) {
      const s = standardizeStats(tr) // 仅训练折
      Xtr = tr.map(r => r.x.map((v, j) => (v - s.mean[j]) / s.sd[j]))
      Xte = te.map(r => r.x.map((v, j) => (v - s.mean[j]) / s.sd[j]))
    }
    else {
      Xtr = tr.map(r => r.x)
      Xte = te.map(r => r.x)
    }
    const w = fitLogistic(Xtr, tr.map(r => r.y))
    const sc = predictScores(w, Xte)

    // 预存每个 test 行在全 rows 中的真实索引（独立于 rows.indexOf）
    const teIdx: number[] = []
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].convIdx === ci)
        teIdx.push(i)
    }
    if (teIdx.length !== te.length)
      throw new Error(`teIdx/te length mismatch at fold ${ci}`)

    te.forEach((r, k) => {
      const viaIndexOf = rows.indexOf(r)
      if (viaIndexOf !== teIdx[k])
        indexOfAligned = false
      locvScores[teIdx[k]] = sc[k] // 用预存索引回填（与 probe 的 rows.indexOf 等价）
    })
    perConv.push(auc(sc, te.map(r => r.y)))
  }

  // 抽查：前若干、中、后若干行的 (idx, convIdx, y, score)
  const picks = [0, 1, 500, 1500, 3000, rows.length - 1]
  for (const p of picks) {
    if (p >= 0 && p < rows.length)
      spot.push({ idx: p, convIdx: rows[p].convIdx, y: rows[p].y, score: locvScores[p] })
  }
  return { pooled: auc(locvScores, rows.map(r => r.y)), perConv, indexOfAligned, spot }
}

// ============================================================ 审计 3：嵌套 CV（外层留一 + 内层贪心前向特征选择）

interface NestedResult {
  pooled: number
  perFold: { ci: number, auc: number, selected: number[] }[]
}

/**
 * 内层选择准则：在给定 rows（9 个训练对话）上拟逻辑回归，取这 9 个对话的平均（重代入）AUC。
 *  未做二次嵌套（见报告：可接受降级方案，残留轻微乐观偏倚）。
 */
function trainAverageAuc(rows: Row[], idx: number[]): number {
  const X = subX(rows, idx)
  const y = rows.map(r => r.y)
  const w = fitLogistic(X, y)
  const sc = predictScores(w, X)
  const convs = [...new Set(rows.map(r => r.convIdx))].sort((a, b) => a - b)
  let sum = 0
  for (const c of convs) {
    const ys: number[] = []
    const ss: number[] = []
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].convIdx === c) {
        ys.push(rows[i].y)
        ss.push(sc[i])
      }
    }
    sum += auc(ss, ys)
  }
  return sum / convs.length
}

function greedyForward(rows: Row[]): number[] {
  const nFeat = rows[0].x.length
  const selected: number[] = []
  let best = 0.5
  while (selected.length < nFeat) {
    let add = -1
    let addAuc = best
    for (let f = 0; f < nFeat; f++) {
      if (selected.includes(f))
        continue
      const a = trainAverageAuc(rows, [...selected, f])
      if (a > addAuc) {
        addAuc = a
        add = f
      }
    }
    if (add === -1)
      break
    selected.push(add)
    best = addAuc
  }
  return selected
}

function nestedCv(convs: LocomoConversation[]): NestedResult {
  const nConv = convs.length
  const pooledScores: number[] = []
  const pooledLabels: number[] = []
  const perFold: { ci: number, auc: number, selected: number[] }[] = []

  for (let ci = 0; ci < nConv; ci++) {
    const trainConvs = convs.filter((_, i) => i !== ci)
    const testConv = [convs[ci]]
    const { idf, nDocs } = buildIdfLocal(trainConvs) // IDF 也只建在训练折（无监督，但严格隔离测试折）
    const trainRows = buildRowsLocal(trainConvs, idf, nDocs)
    const testRows = buildRowsLocal(testConv, idf, nDocs)

    const stats = standardizeStats(trainRows) // 仅训练折
    applyStd(trainRows, stats)
    applyStd(testRows, stats)

    const selected = greedyForward(trainRows) // 内层：在 9 个训练对话上选特征
    const w = fitLogistic(subX(trainRows, selected), trainRows.map(r => r.y))
    const sc = predictScores(w, subX(testRows, selected))
    const foldAuc = auc(sc, testRows.map(r => r.y))

    pooledScores.push(...sc)
    pooledLabels.push(...testRows.map(r => r.y))
    perFold.push({ ci, auc: foldAuc, selected })
    console.info(`  outer fold ${ci}: test AUC=${foldAuc.toFixed(3)}  k=${selected.length}  selected=[${selected.map(j => FEATURES[j].name).join(', ')}]`)
  }

  return { pooled: auc(pooledScores, pooledLabels), perFold }
}

// ============================================================ 主流程

function main(): void {
  const m = buildExperimentManifest({
    id: 'salience-nested-cv-audit',
    name: 'Salience nested-CV audit: leak decomposition (standardize + feature-selection leakage)',
    seed: 0,
    conditions: [
      { name: 'LOCV-original', description: 'Global standardize + all 13 features, leave-one-conversation-out (replicates probe.ts)' },
      { name: 'LOCV-trainStd', description: 'Standardize statistics computed on training folds only (fixes standardize leakage)' },
      { name: 'Nested-Train', description: 'Outer LOCV + inner greedy forward feature selection on 9 train conversations (honest pooled AUC)' },
    ],
    metrics: ['pooledAuc.LOCV-original', 'pooledAuc.LOCV-trainStd', 'pooledAuc.Nested-Train', 'leak.standardize', 'leak.featureSelection'],
    notes: 'AUDIT ONLY — quantifies how much of probe.ts LOCV=0.812 is optimistic bias from leakage. All logic copied verbatim from probe.ts for comparability. The Nested-Train pooled AUC is the publishable, honest estimate.',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const path = resolveLocomoPath(process.argv[2]).path
  const convs = loadLocomo(path)
  const nRows = convs.reduce((s, c) => s + c.episodes.length, 0)
  // 实际正例行数 = 被引用且确实存在的 episode（evidenceIds 中可能含对话里不存在的 phantom id）
  const nPos = convs.reduce((s, c) => s + c.episodes.filter(e => c.evidenceIds.has(e.id)).length, 0)

  console.info('=== salience 嵌套交叉验证审计 ===')
  console.info(`corpus       : ${path}`)
  console.info(`conversations: ${convs.length}`)
  console.info(`episodes     : ${nRows}  (positive(被引用) ${nPos}, ${((nPos / nRows) * 100).toFixed(1)}%)`)
  console.info(`features     : ${FEATURES.length}`)
  console.info()

  // ---- (1) 复刻原始 LOCV：全局 standardize + 全 13 特征 ----
  console.info('--- (1) LOCV-original（复刻 probe.ts：全局 standardize，全 13 特征）---')
  const r1 = locvReproduce(convs, false)
  console.info(`  pooled AUC      : ${r1.pooled.toFixed(3)}   (probe 报 0.812，用于确认复刻无误)`)
  console.info(`  indexOf 对齐验证 : ${r1.indexOfAligned ? '通过' : '失败!!'}`)
  console.info(`  逐对话 AUC      : [${r1.perConv.map(a => a.toFixed(2)).join(' ')}]`)
  console.info('  抽查 (idx, convIdx, y, score):')
  for (const s of r1.spot)
    console.info(`    idx=${String(s.idx).padStart(5)} conv=${s.convIdx} y=${s.y} score=${s.score.toFixed(4)}`)
  console.info()

  // ---- (2) LOCV-训练折内 standardize：修正 standardize 泄漏 ----
  console.info('--- (2) LOCV-trainStd（standardize 仅用训练折 9 对话）---')
  const r2 = locvReproduce(convs, true)
  console.info(`  pooled AUC      : ${r2.pooled.toFixed(3)}`)
  console.info(`  与(1)差值(=standardize泄漏贡献) : ${(r1.pooled - r2.pooled).toFixed(3)}`)
  console.info()

  // ---- (3) 嵌套 CV：内层贪心前向特征选择 ----
  console.info('--- (3) Nested-Train（外层留一 + 内层贪心前向特征选择，9对话平均AUC为准则/非二次嵌套）---')
  const r3 = nestedCv(convs)
  console.info()
  console.info('  各折选中特征子集稳定性：')
  for (const pf of r3.perFold)
    console.info(`    fold ${pf.ci}: [${pf.selected.map(j => FEATURES[j].name).join(', ')}]`)
  const union = new Set<number>()
  const intersection = new Set<number>(r3.perFold[0].selected)
  for (const pf of r3.perFold) {
    pf.selected.forEach(j => union.add(j))
    intersection.forEach((j) => {
      if (!pf.selected.includes(j))
        intersection.delete(j)
    })
  }
  console.info(`    始终入选(∩): [${[...intersection].map(j => FEATURES[j].name).join(', ')}]`)
  console.info(`    至少一次入选(∪): [${[...union].map(j => FEATURES[j].name).join(', ')}]`)
  console.info()
  console.info(`  pooled AUC (可写进论文) : ${r3.pooled.toFixed(3)}`)
  console.info(`  逐对话 AUC             : [${r3.perFold.map(p => p.auc.toFixed(2)).join(' ')}]  mean=${(r3.perFold.reduce((a, b) => a + b.auc, 0) / r3.perFold.length).toFixed(3)}`)
  console.info()

  // ---- 汇总：泄漏分解 ----
  console.info('=== 泄漏分解 ===')
  console.info(`  PRIOR (零标签先验, 已知被特征选择+权重污染) : 0.796`)
  console.info(`  LOCV-original (probe 报, 权重留一但特征选择未留一) : ${r1.pooled.toFixed(3)}`)
  console.info(`  LOCV-trainStd (仅修正 standardize 泄漏)            : ${r2.pooled.toFixed(3)}`)
  console.info(`  Nested-Train (再修正特征选择泄漏, 诚实估计)         : ${r3.pooled.toFixed(3)}`)
  console.info(`  → 特征选择泄漏贡献 ≈ ${(r2.pooled - r3.pooled).toFixed(3)}  ( (2)-(3) )`)
  console.info(`  → standardize 泄漏贡献 ≈ ${(r1.pooled - r2.pooled).toFixed(3)}  ( (1)-(2) )`)
  console.info(`  → 总乐观偏倚 (LOCV - Nested) ≈ ${(r1.pooled - r3.pooled).toFixed(3)}`)
}

main()
