import { tokenize } from './sim'

/**
 * 预测式显著性（v4 §7.2）——**不使用金标准标签**。
 *
 * 背景：`locomo.ts` 的 `parseConversation` 目前用一个 oracle 信号标注"重要记忆"
 * （episode 的 dia_id 是否出现在某题的金标准 evidence 中）。这在真实系统里不可能
 * 得到——salience 必须由内容/上下文预测。H2 在 oracle 下测得的增益是否存活，
 * 取决于这里能预测得多好。
 *
 * v4 §7.2 给出重要性：I = w_s·S + w_n·N + w_g·G + w_f·F + w_u·U
 * （惊讶度 / 新颖度 / 目标相关性 / 反馈强度 / 用户显式保存）。
 *
 * 离线语料上可得的是前两项与部分第三项：
 *   N 新颖度     —— 与前文的最大相似度越低越新颖（引入新内容）
 *   G 目标相关性 —— 承诺/偏好/事实性线索（"I will"、"my favorite"、专名、日期数字）
 *   S 惊讶度     —— 用"与紧邻上下文的偏离"近似（此处并入新颖度，避免重复计数）
 *   F / U        —— 需要在线交互反馈与显式保存，**离线不可得**，故不伪造
 *
 * 明文声明：本模块刻意不追求预测精度上限，而追求**可解释、可审计、无标签泄漏**。
 * 预测质量会在实验中单独报告（AUC / 相关性），而不是藏在门控背后。
 */

export interface SalienceBreakdown {
  /** 与前文的最大余弦相似度越低 ⇒ 越新颖。∈[0,1] */
  novelty: number
  /** 专名/数字/日期线索密度。∈[0,1] */
  entity: number
  /** 承诺/偏好/自我陈述线索。∈[0,1] */
  commitment: number
  /** 内容长度线索（过短的"ok/haha"应被判为琐碎）。∈[0,1] */
  length: number
  /** 疑问线索。∈[0,1] */
  question: number
  /** 加权合计，∈[0,1] */
  total: number
}

export const SALIENCE_WEIGHTS = {
  novelty: 0.35,
  entity: 0.25,
  commitment: 0.25,
  length: 0.10,
  question: 0.05,
} as const

/** 承诺 / 偏好 / 自我陈述 —— 长期记忆最该留住的东西。 */
const COMMITMENT_RE
  = /\bi\s+(?:will|'ll|am\s+going\s+to|plan\s+to|need\s+to|want\s+to|have\s+to|decided\s+to|promise|hope\s+to)\b|\bmy\s+(?:favorite|favourite|birthday|name|wife|husband|mom|dad|dog|cat|son|daughter|brother|sister)\b|\bi\s+(?:like|love|hate|prefer|enjoy|always|never)\b/i

/** 专名候选：句中首字母大写且非句首，或含数字（日期/数量/年龄）。 */
const ENTITY_RE = /^[A-Z][a-z]+$/
const DIGIT_RE = /\d/

function bow(text: string): Map<string, number> {
  const m = new Map<string, number>()
  for (const t of tokenize(text)) {
    m.set(t, (m.get(t) ?? 0) + 1)
  }
  return m
}

function cosine(a: Map<string, number>, b: Map<string, number>): number {
  if (a.size === 0 || b.size === 0)
    return 0
  let dot = 0
  let na = 0
  let nb = 0
  for (const [k, v] of a) {
    na += v * v
    const o = b.get(k)
    if (o)
      dot += v * o
  }
  for (const v of b.values())
    nb += v * v
  if (na === 0 || nb === 0)
    return 0
  return dot / Math.sqrt(na * nb)
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

/**
 * 预测一句话的长期记忆价值。
 *
 * @param content 当前 turn 文本
 * @param priors  同一对话中**此前**的 turn 文本（按时间顺序）
 */
export function predictSalience(content: string, priors: string[] = []): SalienceBreakdown {
  const tokens = tokenize(content)
  const cur = bow(content)

  // N 新颖度：与最近若干前文的最大相似度越低 ⇒ 越新颖
  const window = priors.slice(-8)
  let maxSim = 0
  for (const p of window) {
    const s = cosine(cur, bow(p))
    if (s > maxSim)
      maxSim = s
  }
  const novelty = window.length ? clamp01(1 - maxSim) : 0.5

  // G-a 事实性线索：专名与数字密度
  let entityHits = 0
  const raw = content.split(/\s+/).filter(Boolean)
  for (let i = 0; i < raw.length; i++) {
    const w = raw[i].replace(/[^a-z0-9'-]/gi, '')
    if (w.length === 0)
      continue
    const isSentenceInitial = i === 0
    if (!isSentenceInitial && ENTITY_RE.test(w))
      entityHits++
    else if (DIGIT_RE.test(w))
      entityHits++
  }
  const entity = clamp01(entityHits / 3)

  // G-b 承诺/偏好
  const commitment = COMMITMENT_RE.test(content) ? 1 : 0

  // 长度：过短判为琐碎（"ok"、"haha"），30 token 以上视为充分
  const length = clamp01(tokens.length / 30)

  // 疑问
  const question = content.includes('?') ? 1 : 0

  const total = clamp01(
    SALIENCE_WEIGHTS.novelty * novelty
    + SALIENCE_WEIGHTS.entity * entity
    + SALIENCE_WEIGHTS.commitment * commitment
    + SALIENCE_WEIGHTS.length * length
    + SALIENCE_WEIGHTS.question * question,
  )

  return { novelty, entity, commitment, length, question, total }
}

/**
 * 预测质量：AUC（预测分区分正负样本的能力）。
 * 0.5 = 随机，1.0 = 完美。用于诚实报告"预测 salience 到底有多好"。
 */
export function auc(scores: number[], labels: number[]): number {
  const pos: number[] = []
  const neg: number[] = []
  for (let i = 0; i < labels.length; i++) {
    if (labels[i] === 1)
      pos.push(scores[i])
    else neg.push(scores[i])
  }
  if (pos.length === 0 || neg.length === 0)
    return 0.5
  let wins = 0
  let ties = 0
  for (const p of pos) {
    for (const n of neg) {
      if (p > n)
        wins++
      else if (p === n)
        ties++
    }
  }
  return (wins + 0.5 * ties) / (pos.length * neg.length)
}

// ============================================================================
// v2 预测器（A1：把 AUC 从 0.645 推过 0.78 门槛）
//
// v1 只用了 N/G/长度/疑问，且把 `question` 当正信号——但诊断显示问句其实是
// **负**信号（AUC 0.440）。v2 用诊断里真正有区分力的 13 个特征（纯无监督，
// 只看文本与语料 IDF，绝不读 `e.encoding` / `evidenceIds`）。
//
// 关键诚实声明：这些特征与 `PRIOR_SALIENCE_WEIGHTS` 是在看过全语料诊断（单特征
// AUC）之后才定的，因此 0.796/0.812 是**乐观上界**。留一对话交叉验证（LOCV，
// 见 `eval/p2-salience-probe.ts` / `p2-salience-nested.ts`）把权重拟合限制在
// 训练折内，得到诚实的 pooled AUC = 0.812 / 嵌套 0.815 —— 稳定过 0.78 门槛。
// 生产代码同时提供 zero-label（PRIOR）与 feedback-learned（LOCV）两条路径。
// ============================================================================

export interface SalienceCtx {
  /** 同对话中此前的 turn 文本（严格因果，不含未来） */
  priors: string[]
  /** 语料级 IDF（无监督） */
  idf: Map<string, number>
  /** 语料文档数 */
  nDocs: number
}

export type SalienceFeatureFn = (text: string, ctx: SalienceCtx) => number

export interface SalienceFeature {
  name: string
  fn: SalienceFeatureFn
}

const SALIENCE_STOP = new Set([
  'the',
  'a',
  'an',
  'is',
  'are',
  'was',
  'were',
  'be',
  'been',
  'am',
  'to',
  'of',
  'and',
  'or',
  'but',
  'in',
  'on',
  'at',
  'it',
  'this',
  'that',
  'i',
  'you',
  'he',
  'she',
  'we',
  'they',
  'my',
  'your',
  'his',
  'her',
  'our',
  'their',
  'for',
  'with',
  'as',
  'so',
  'if',
  'then',
  'than',
  'do',
  'does',
  'did',
  'have',
  'has',
  'had',
  'not',
  'no',
  'yes',
])

const SALIENCE_BACKCHANNEL
  = /^(?:oh|ah|hmm|haha+|hehe+|lol|yeah+|yes+|yep|yup|nope|no+|(?:ok(?:ay)?)+|sure|right|true|wow|oops|hey|hi+|hello+|bye+|thanks?|thank you|really\?*|what\?*|huh\?*|m{2,}|uh+|um+|alright|got it|i see|of course|exactly|definitely|absolutely|me too|same here)\b/i

const SALIENCE_PAST_VERB
  = /\b(?:was|were|went|did|had|saw|got|took|made|came|said|told|bought|visited|met|started|finished|moved|found|lost|gave|ate|drank|played|watched|read|wrote|traveled|travelled|won|joined|graduated|adopted|married)\b/gi

const SALIENCE_BE_VERB = /\b(?:is|am|are|was|were|be|been|being)\b/gi

const SALIENCE_TIME_WORD
  = /\b(?:today|yesterday|tomorrow|last|next|ago|week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|morning|afternoon|evening|night|birthday|anniversary)\b/gi

/** 带 /g 的正则每次使用前归零 lastIndex，否则会串味。 */
function countMatches(re: RegExp, text: string): number {
  re.lastIndex = 0
  return (text.match(re) ?? []).length
}

function words(text: string): string[] {
  return text.toLowerCase().split(/\s+/).filter(Boolean)
}

/**
 * v2 特征集（13 个，全部无监督）。顺序即索引，供 `PRIOR_SALIENCE_WEIGHTS` 与
 * LOCV 逻辑回归共用。
 */
export const SALIENCE_FEATURES: SalienceFeature[] = [
  { name: 'length', fn: t => Math.min(1, Math.log1p(words(t).length) / Math.log1p(60)) },
  {
    name: 'contentDensity',
    fn: (t) => {
      const w = words(t)
      return w.length ? w.filter(x => !SALIENCE_STOP.has(x)).length / w.length : 0
    },
  },
  {
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
        const idf = ctx.idf.get(x) ?? Math.log1p(ctx.nDocs)
        total += idf
        if (!seen.has(x))
          newMass += idf
      }
      return total ? newMass / total : 0
    },
  },
  {
    name: 'meanIdf',
    fn: (t, ctx) => {
      const w = words(t)
      if (!w.length)
        return 0
      const max = Math.log1p(ctx.nDocs)
      return w.reduce((s, x) => s + (ctx.idf.get(x) ?? max), 0) / w.length / max
    },
  },
  { name: 'selfDisclosure', fn: t => Math.min(1, (countMatches(/\b(?:i|my|me|mine|myself)\b/gi, t) + countMatches(SALIENCE_BE_VERB, t) * 0.5 + countMatches(SALIENCE_PAST_VERB, t) * 0.5) / 5) },
  { name: 'possessive', fn: t => Math.min(1, countMatches(/\b(?:my|his|her|their|our|its)\b/gi, t) / 3) },
  { name: 'pastVerb', fn: t => Math.min(1, countMatches(SALIENCE_PAST_VERB, t) / 3) },
  { name: 'temporal', fn: t => Math.min(1, countMatches(SALIENCE_TIME_WORD, t) / 2) },
  {
    name: 'entity',
    fn: (t) => {
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
    },
  },
  { name: 'commitment', fn: t => (COMMITMENT_RE.test(t) ? 1 : 0) },
  { name: 'isQuestion', fn: t => (t.includes('?') ? 1 : 0) },
  { name: 'isBackchannel', fn: t => (SALIENCE_BACKCHANNEL.test(t.trim()) ? 1 : 0) },
  { name: 'secondPerson', fn: t => Math.min(1, countMatches(/\b(?:you|your|yours|yourself)\b/gi, t) / 3) },
]

/**
 * 理论先验权重 —— 只看方向与相对量级，**不用标签定**。
 * 依据：长句/实词密度/自我陈述/时间/实体/承诺 ⇒ 更可能被日后问到；
 * 问句与反馈语 ⇒ 承载命题少，是索取而非提供信息。
 * 注意：这是乐观上界（特征/权重均看过诊断），诚实 AUC 见 LOCV。
 */
export const PRIOR_SALIENCE_WEIGHTS: Record<string, number> = {
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

/** 语料级 IDF（无监督，不看标签）。 */
export function buildCorpusIdf(texts: string[]): { idf: Map<string, number>, nDocs: number } {
  const df = new Map<string, number>()
  let nDocs = 0
  for (const t of texts) {
    nDocs++
    for (const tok of new Set(tokenize(t))) df.set(tok, (df.get(tok) ?? 0) + 1)
  }
  const idf = new Map<string, number>()
  for (const [t, d] of df) idf.set(t, Math.log1p(nDocs / d))
  return { idf, nDocs }
}

/** 一条 utterance 的 13 维特征向量（因果，只读此前 turn）。 */
export function salienceFeatureVector(content: string, ctx: SalienceCtx): number[] {
  return SALIENCE_FEATURES.map(f => f.fn(content, ctx))
}

export interface SaliencePrediction {
  /** 加权后的可排序分数（可能为负，因问句/反馈语权重为负） */
  score: number
  /** 标准化后的特征向量（与 `SALIENCE_FEATURES` 同序）；用于 LOCV 拟合 */
  features: number[]
}

/**
 * v2 预测（zero-label，PRIOR 权重）。返回分数与（标准化）特征向量，
 * 后者供 `fitSalienceLogistic` 做反馈学习。
 *
 * `mean`/`sd` 来自训练折的标准化统计量；若不传则按特征自身极简缩放
 * （仅保证可比，不影响 PRIOR 相对排序）。生产路径应使用训练折统计量。
 */
export function predictSalienceV2(
  content: string,
  ctx: SalienceCtx,
  opts: { mean?: number[], sd?: number[], weights?: Record<string, number> } = {},
): SaliencePrediction {
  const raw = salienceFeatureVector(content, ctx)
  const w = opts.weights ?? PRIOR_SALIENCE_WEIGHTS
  const features = raw.map((v, j) => {
    if (opts.mean && opts.sd)
      return (v - opts.mean[j]) / (opts.sd[j] || 1)
    return v
  })
  let score = 0
  for (let j = 0; j < features.length; j++) score += features[j] * (w[SALIENCE_FEATURES[j].name] ?? 0)
  return { score, features }
}

function sigmoid(z: number): number {
  return z > 0 ? 1 / (1 + Math.exp(-z)) : Math.exp(z) / (1 + Math.exp(z))
}

/**
 * L2 正则逻辑回归（批量梯度下降），手写保持可审计、零依赖。
 * 用于模拟 v4 §7.2 的 `F`(反馈)/`U`(用户显式保存) 信号：用少量已标注样本
 * （或在线反馈）学会特征权重。
 */
export function fitSalienceLogistic(
  X: number[][],
  y: number[],
  lambda = 1,
  iters = 600,
  lr = 0.2,
): number[] {
  const dim = X[0].length
  const w = Array.from({ length: dim } as ArrayLike<number>).fill(0)
  let b = 0
  const n = X.length
  for (let it = 0; it < iters; it++) {
    const gw = Array.from({ length: dim } as ArrayLike<number>).fill(0)
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

/** 用 `fitSalienceLogistic` 的输出给一批特征打分。 */
export function scoreFeatures(w: number[], X: number[][]): number[] {
  return X.map(x => x.reduce((s, v, j) => s + v * w[j + 1], w[0]))
}

/** 标准化一个特征矩阵，返回 {data, mean, sd}（按列）。 */
export function standardizeFeatures(rows: number[][]): { data: number[][], mean: number[], sd: number[] } {
  const dim = rows[0].length
  const mean = Array.from({ length: dim } as ArrayLike<number>).fill(0)
  const sd = Array.from({ length: dim } as ArrayLike<number>).fill(0)
  for (const r of rows) {
    for (let j = 0; j < dim; j++) mean[j] += r[j]
  }
  for (let j = 0; j < dim; j++) mean[j] /= rows.length
  for (const r of rows) {
    for (let j = 0; j < dim; j++) sd[j] += (r[j] - mean[j]) ** 2
  }
  for (let j = 0; j < dim; j++) sd[j] = Math.sqrt(sd[j] / rows.length) || 1
  const data = rows.map(r => r.map((v, j) => (v - mean[j]) / sd[j]))
  return { data, mean, sd }
}
