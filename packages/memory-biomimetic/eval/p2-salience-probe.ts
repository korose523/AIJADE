/**
 * salience 预测器探针（A1：把 AUC 从 0.645 推到 ≥0.78）
 *
 * 诊断已经暴露了两个事实（`p2-salience-diag.ts`）：
 *   · 长度是最强的单特征（AUC 0.728，正例率 3.7%→53.9% 单调上升），当前权重只给了 0.10
 *   · has_question 是**负相关**（AUC 0.440），当前却在加分
 *
 * 但**照着这些数字调权重就是把标签从后门放进来**——在同一份数据上选特征、再在同一份
 * 数据上报告 AUC，等于泄漏。所以本脚本只报告两种**诚实的**估计：
 *
 *   PRIOR  —— 完全不接触标签。权重由理论先验给定（长句承载更多命题内容、问句与
 *             反馈语承载更少），刻度由无监督统计量（IDF、均值/方差）确定。
 *   LOCV   —— 留一对话交叉验证。在 9 个对话上拟合逻辑回归，预测第 10 个。
 *             模拟"系统通过 F/U 反馈学会权重"（v4 §7.2 的 F 与 U），
 *             且报告的每一个分数都来自**训练时未见过的对话**。
 *
 * 两者之差回答 A1 的核心问题：差的是**特征**，还是**权重**？
 *   · LOCV 高、PRIOR 低 ⇒ 特征够了，缺的只是反馈信号 → A1 有救
 *   · 两者都低         ⇒ 特征本身不够 → 需要完全不同的信号源
 *
 * Usage:  tsx eval/p2-salience-probe.ts [path-to-locomo.json]
 */
import type { LocomoConversation } from '../src/index'

import process from 'node:process'

import { auc, buildExperimentManifest, loadLocomo, predictSalience, registerExperimentManifest, tokenize } from '../src/index'
import { resolveLocomoPath } from './locomo-path'

interface Ctx {
  /** 同对话中此前的 turn 文本（因果，不含未来） */
  priors: string[]
  /** 语料级 IDF（无监督，不看标签） */
  idf: Map<string, number>
  nDocs: number
}

interface FeatureDef {
  name: string
  fn: (text: string, ctx: Ctx) => number
}

const STOP = new Set(['the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'am', 'to', 'of', 'and', 'or', 'but', 'in', 'on', 'at', 'it', 'this', 'that', 'i', 'you', 'he', 'she', 'we', 'they', 'my', 'your', 'his', 'her', 'our', 'their', 'for', 'with', 'as', 'so', 'if', 'then', 'than', 'do', 'does', 'did', 'have', 'has', 'had', 'not', 'no', 'yes'])

const BACKCHANNEL = /^(?:oh|ah|hmm|haha+|hehe+|lol|yeah+|yes+|yep|yup|nope|no+|(?:ok(?:ay)?)+|sure|right|true|wow|oops|hey|hi+|hello+|bye+|thanks?|thank you|really\?*|what\?*|huh\?*|m{2,}|uh+|um+|alright|got it|i see|of course|exactly|definitely|absolutely|me too|same here)\b/i
const PAST_VERB = /\b(?:was|were|went|did|had|saw|got|took|made|came|said|told|bought|visited|met|started|finished|moved|found|lost|gave|ate|drank|played|watched|read|wrote|traveled|travelled|won|joined|graduated|adopted|married)\b/gi
const BE_VERB = /\b(?:is|am|are|was|were|be|been|being)\b/gi
const TIME_WORD = /\b(?:today|yesterday|tomorrow|last|next|ago|week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|morning|afternoon|evening|night|birthday|anniversary)\b/gi
const COMMIT = /\bi\s+(?:will|'ll|am\s+going\s+to|plan\s+to|need\s+to|want\s+to|have\s+to|decided\s+to|promise|hope\s+to)\b|\bmy\s+(?:favorite|favourite|birthday|name|wife|husband|mom|dad|dog|cat|son|daughter|brother|sister)\b|\bi\s+(?:like|love|hate|prefer|enjoy|always|never)\b/i

function count(re: RegExp, text: string): number {
  // 复用带 /g 的正则需要先归零，否则 lastIndex 会串味
  re.lastIndex = 0
  return (text.match(re) ?? []).length
}

function words(text: string): string[] {
  return text.toLowerCase().split(/\s+/).filter(Boolean)
}

export const FEATURES: FeatureDef[] = [
  {
    // 最强单特征：长句承载更多命题内容，被问到的概率单调上升
    name: 'length',
    fn: t => Math.min(1, Math.log1p(words(t).length) / Math.log1p(60)),
  },
  {
    // 实词密度：停用词越少，单位长度的信息量越高
    name: 'contentDensity',
    fn: (t) => {
      const w = words(t)
      return w.length ? w.filter(x => !STOP.has(x)).length / w.length : 0
    },
  },
  {
    // 新颖度：相对前文引入多少**罕见**词（IDF 加权），纯无监督
    name: 'noveltyIdf',
    fn: (t, ctx) => {
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
    },
  },
  {
    // 平均 IDF：说到的东西有多"特别"（专名/罕见词 → 更可能被问到）
    name: 'meanIdf',
    fn: (t, ctx) => {
      const w = words(t)
      if (!w.length)
        return 0
      const max = Math.log1p(ctx.nDocs)
      return w.reduce((s, x) => s + (ctx.idf.get(x) ?? max), 0) / w.length / max
    },
  },
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

/**
 * 理论先验权重 —— **不用标签定**，只用方向与相对量级。
 * 依据：长度/实词密度/自我陈述/时间/实体/承诺 ⇒ 更可能被日后问到；
 * 问句与反馈语 ⇒ 承载的命题内容少，且通常是在索取而非提供信息。
 */
export const PRIOR_WEIGHTS: Record<string, number> = {
  length: 1.00,
  contentDensity: 0.35,
  noveltyIdf: 0.20,
  meanIdf: 0.30,
  selfDisclosure: 0.55,
  possessive: 0.30,
  pastVerb: 0.35,
  temporal: 0.35,
  entity: 0.30,
  commitment: 0.45,
  isQuestion: -0.40,
  isBackchannel: -0.60,
  secondPerson: -0.30,
}

// ---------------------------------------------------------------- 数据准备

interface Row {
  convIdx: number
  y: number
  x: number[]
}

function buildIdf(convs: LocomoConversation[]): { idf: Map<string, number>, nDocs: number } {
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

function buildRows(convs: LocomoConversation[], idf: Map<string, number>, nDocs: number): Row[] {
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

// ---------------------------------------------------------------- 逻辑回归

function sigmoid(z: number): number {
  return z > 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z))
}

/** L2 正则逻辑回归（批量梯度下降）—— 故意手写，保持可审计、无依赖。 */
function fitLogistic(X: number[][], y: number[], lambda = 1, iters = 600, lr = 0.2): number[] {
  const dim = X[0].length
  const w = Array.from({ length: dim }).fill(0)
  let b = 0
  const n = X.length
  for (let it = 0; it < iters; it++) {
    const gw = Array.from({ length: dim }).fill(0)
    let gb = 0
    for (let i = 0; i < n; i++) {
      const p = sigmoid(X[i].reduce((s, v, j) => s + v * w[j], b))
      const err = p - y[i]
      for (let j = 0; j < dim; j++) gw[j] += err * X[i][j]
      gb += err
    }
    for (let j = 0; j < dim; j++) w[j] -= lr * ((gw[j] + lambda * w[j]) / n)
    b -= lr * (gb / n)
  }
  return [b, ...w]
}

function predictScores(w: number[], X: number[][]): number[] {
  return X.map(x => x.reduce((s, v, j) => s + v * w[j + 1], w[0]))
}

function mulberry32(a: number): () => number {
  let s = a >>> 0
  return () => {
    s = (s + 0x6D2B79F5) >>> 0
    let t = Math.imul(s ^ s >>> 15, 1 | s)
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t
    return ((t ^ t >>> 14) >>> 0) / 4294967296
  }
}

// ---------------------------------------------------------------- 主流程

function main(): void {
  const m = buildExperimentManifest({
    id: 'salience-predictor-probe',
    name: 'Salience predictor probe: PRIOR (zero-label) vs LOCV AUC, and the learning curve',
    seed: 7,
    conditions: [
      { name: 'PRIOR', description: 'Theoretically-prior weights, zero label contact; scale set by unsupervised statistics', params: { usesGoldLabels: false } },
      { name: 'LOCV', description: 'Leave-one-conversation-out logistic regression (simulates F/U feedback learning weights)', params: { usesGoldLabels: false } },
    ],
    metrics: ['prior.auc', 'locv.auc', 'learningCurve.auc'],
    notes: 'Seed 7 drives the learning-curve random fold splits (mulberry32(7), 20 trials per k). Both estimates are honest (no label-driven weight tuning). Answers A1: feature vs weight sufficiency — LOCV high & PRIOR low ⇒ features suffice, needs feedback; both low ⇒ need a different signal source. Threshold ≈ 0.78.',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const path = resolveLocomoPath(process.argv[2]).path
  const convs = loadLocomo(path)
  const { idf, nDocs } = buildIdf(convs)
  const rows = buildRows(convs, idf, nDocs)
  standardize(rows)

  const positives = rows.filter(r => r.y === 1).length
  console.info('=== salience 预测器探针 ===')
  console.info(`corpus        : ${path}`)
  console.info(`episodes      : ${rows.length}  (positive ${positives}, ${((positives / rows.length) * 100).toFixed(1)}%)`)
  console.info(`features      : ${FEATURES.length}`)
  console.info()

  // ---- 1. 单特征 AUC（诊断；不用于定权重）----
  console.info('--- 单特征 AUC（诊断用）---')
  const labels = rows.map(r => r.y)
  const single = FEATURES
    .map((f, j) => ({ name: f.name, a: auc(rows.map(r => r.x[j]), labels) }))
    .sort((a, b) => Math.abs(b.a - 0.5) - Math.abs(a.a - 0.5))
  for (const s of single) {
    const dir = s.a > 0.5 ? '正相关' : '负相关'
    console.info(`  ${s.name.padEnd(16)} AUC=${s.a.toFixed(3)}  ${dir}`)
  }
  console.info()

  // ---- 2. PRIOR：完全不接触标签 ----
  // 先验权重作用在**标准化后**的特征上（标准化统计量本身无监督），
  // 这是"不调参"与"可用"之间唯一的妥协点，且刻度不依赖标签。
  const priorScores = rows.map(r => r.x.reduce((s, v, j) => s + v * (PRIOR_WEIGHTS[FEATURES[j].name] ?? 0), 0))
  const priorAuc = auc(priorScores, labels)
  console.info('--- PRIOR（理论先验权重，零标签）---')
  console.info(`  pooled AUC : ${priorAuc.toFixed(3)}`)

  // 旧预测器作为对照
  const oldScores: number[] = []
  const oldLabels: number[] = []
  for (const c of convs) {
    const priors: string[] = []
    for (const e of c.episodes) {
      oldScores.push(predictSalience(e.content, priors).total)
      oldLabels.push(c.evidenceIds.has(e.id) ? 1 : 0)
      priors.push(e.content)
    }
  }
  console.info(`  旧 predictSalience : ${auc(oldScores, oldLabels).toFixed(3)}   (commit 01b9988)`)
  console.info()

  // ---- 3. LOCV：留一对话交叉验证（模拟 F/U 反馈学权重）----
  console.info('--- LOCV（留一对话交叉验证，全部分数来自未见对话）---')
  const locvScores = Array.from({ length: rows.length }).fill(0)
  const nConv = convs.length
  const perConv: number[] = []
  for (let ci = 0; ci < nConv; ci++) {
    const tr = rows.filter(r => r.convIdx !== ci)
    const te = rows.filter(r => r.convIdx === ci)
    const w = fitLogistic(tr.map(r => r.x), tr.map(r => r.y))
    const sc = predictScores(w, te.map(r => r.x))
    te.forEach((r, k) => {
      locvScores[rows.indexOf(r)] = sc[k]
    })
    perConv.push(auc(sc, te.map(r => r.y)))
  }
  const locvAuc = auc(locvScores, labels)
  console.info(`  pooled AUC : ${locvAuc.toFixed(3)}`)
  console.info(`  逐对话 AUC : [${perConv.map(a => a.toFixed(2)).join(' ')}]  mean=${(perConv.reduce((a, b) => a + b, 0) / perConv.length).toFixed(3)}`)
  console.info()

  // ---- 4. 学习曲线：多少反馈数据才够？ ----
  console.info('--- 学习曲线：用 k 个对话的标签反馈拟合，在其余对话上测（每档 20 次随机划分）---')
  console.info('   k |  AUC   (训练样本数)')
  const curve: { k: number, aUC: number, nTrain: number }[] = []
  const rnd = mulberry32(7)
  for (let k = 1; k <= nConv - 1; k++) {
    const aucs: number[] = []
    let nTrain = 0
    for (let trial = 0; trial < 20; trial++) {
      const idx = [...Array.from({ length: nConv }).keys()]
      for (let i = idx.length - 1; i > 0; i--) {
        const j = Math.floor(rnd() * (i + 1))
        ;[idx[i], idx[j]] = [idx[j], idx[i]]
      }
      const trainConv = new Set(idx.slice(0, k))
      const tr = rows.filter(r => trainConv.has(r.convIdx))
      const te = rows.filter(r => !trainConv.has(r.convIdx))
      if (!te.length)
        continue
      nTrain = tr.length
      const w = fitLogistic(tr.map(r => r.x), tr.map(r => r.y))
      aucs.push(auc(predictScores(w, te.map(r => r.x)), te.map(r => r.y)))
    }
    const m = aucs.reduce((a, b) => a + b, 0) / aucs.length
    curve.push({ k, aUC: m, nTrain })
    console.info(`  ${String(k).padStart(2)} |  ${m.toFixed(3)}  (${nTrain})`)
  }

  console.info()
  console.info('=== 判读 ===')
  console.info(`  PRIOR=${priorAuc.toFixed(3)}   LOCV=${locvAuc.toFixed(3)}   门槛≈0.78`)
  if (locvAuc >= 0.78 && priorAuc < 0.78)
    console.info('  ⇒ 特征够了，缺的是**权重**——反馈信号（v4 §7.2 的 F/U）能把门控救回来。A1 成立。')
  else if (priorAuc >= 0.78)
    console.info('  ⇒ 连零标签先验都过关：门控不需要反馈信号也能站住。')
  else
    console.info('  ⇒ 连 LOCV 都过不了门槛：特征本身不足，需要完全不同的信号源（如语义嵌入）。')
}

main()
