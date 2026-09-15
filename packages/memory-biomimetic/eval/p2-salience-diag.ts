import process from 'node:process'

import { auc, buildExperimentManifest, loadLocomo, predictSalience, registerExperimentManifest } from '../src/index'
import { resolveLocomoPath } from './locomo-path'

/**
 * 诊断：什么是"会被问到的句子"？（A1 的第一步）
 *
 * **注意方法学地位**：本脚本**使用金标准标签**做诊断，用来回答
 * "该往预测器里加什么特征"。它本身不是预测器，也不会被提交为结果——
 * 任何用标签调出来的特征/权重，最终都必须在**留一对话交叉验证（LOCV）**
 * 下重新评估，否则就是把标签从后门放进来。
 */

function pct(n: number, d: number): string {
  return d ? `${((n / d) * 100).toFixed(1)}%` : 'n/a'
}

const manifest = buildExperimentManifest({
  id: 'salience-diagnostic-features',
  name: 'Salience diagnostic: which lexical features separate evidence-bearing turns (oracle-label audit)',
  seed: 0,
  conditions: [
    { name: 'diagnostic', description: 'Oracle-label single-feature AUC audit to choose predictor features; NOT a published result', params: { usesGoldLabels: true } },
  ],
  metrics: ['singleFeature.auc', 'positiveRate.byLengthBucket'],
  notes: 'DIAGNOSTIC ONLY — uses gold labels to decide which features to add to the predictor. Any label-tuned feature/weight MUST be re-evaluated under leave-one-conversation cross-validation (LOCV) before publication, or the label leaks back in. Not registered as a result.',
})
registerExperimentManifest(manifest)
console.info(`experiment registered: ${manifest.schema} ${manifest.id}@${manifest.version} (seed ${manifest.seed}, ${manifest.conditions.length} conditions, ${manifest.metrics.length} metrics)`)
console.info()

const convs = loadLocomo(resolveLocomoPath(process.argv[2]).path)

let pos = 0
let neg = 0
for (const c of convs) {
  for (const e of c.episodes) {
    if (c.evidenceIds.has(e.id))
      pos++
    else neg++
  }
}
process.stdout.write(`episodes=${pos + neg}  positives=${pos} (${pct(pos, pos + neg)})  negatives=${neg}\n\n`)

// ---- 正负样本对照 ----
for (const c of convs.slice(0, 2)) {
  process.stdout.write(`\n######## ${c.sampleId} ########\n`)
  const rows = c.episodes.map(e => ({
    id: e.id,
    text: e.content,
    label: c.evidenceIds.has(e.id) ? 1 : 0,
    score: predictSalience(e.content, []).total,
  }))
  process.stdout.write('--- POSITIVE (被引用为证据) ---\n')
  for (const r of rows.filter(r => r.label === 1).slice(0, 12))
    process.stdout.write(`  [${r.score.toFixed(2)}] ${r.text.slice(0, 150)}\n`)
  process.stdout.write('--- NEGATIVE ---\n')
  for (const r of rows.filter(r => r.label === 0).slice(0, 12))
    process.stdout.write(`  [${r.score.toFixed(2)}] ${r.text.slice(0, 150)}\n`)
}

// ---- 单特征 AUC：哪些词面信号真的有区分力？ ----
interface Feat {
  name: string
  fn: (t: string) => number
}

const BACKCHANNEL = /^(?:oh|ah|hmm|haha+|hehe+|lol|yeah+|yes+|yep|yup|nope|no+|(?:ok(?:ay)?)+|sure|right|true|wow|oops|hey|hi+|hello+|bye+|thanks?|thank you|really\?*|what\?*|huh\?*|m{2,}|uh+|um+|alright|got it|i see|of course|exactly|definitely|absolutely|me too|same here|good|great|nice|cool|awesome|amazing|interesting|sounds good|that'?s (?:great|nice|cool|good|awesome))\b/i

const FEATS: Feat[] = [
  { name: 'len_tokens', fn: t => t.split(/\s+/).length },
  { name: 'len_chars', fn: t => t.length },
  { name: 'has_question', fn: t => (t.includes('?') ? 1 : 0) },
  { name: 'is_backchannel', fn: t => (BACKCHANNEL.test(t.trim()) ? 1 : 0) },
  { name: 'n_digits', fn: t => (t.match(/\d+/g) ?? []).length },
  { name: 'n_capitalized', fn: t => (t.split(/\s+/).filter(w => /^[A-Z][a-z]+$/.test(w)).length) },
  { name: 'n_first_person', fn: t => (t.match(/\b(?:i|my|me|mine|myself)\b/gi) ?? []).length },
  { name: 'n_second_person', fn: t => (t.match(/\b(?:you|your|yours|yourself)\b/gi) ?? []).length },
  { name: 'n_past_verb', fn: t => (t.match(/\b(?:was|were|went|did|had|saw|got|took|made|came|said|told|bought|visited|met|started|finished|moved|found|lost|gave|ate|drank|played|watched|read|wrote|traveled|travelled)\b/gi) ?? []).length },
  { name: 'n_be_verb', fn: t => (t.match(/\b(?:is|am|are|was|were|be|been|being)\b/gi) ?? []).length },
  { name: 'n_time_word', fn: t => (t.match(/\b(?:today|yesterday|tomorrow|last|next|ago|week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|morning|afternoon|evening|night|birthday|anniversary|summer|winter|spring|fall|autumn)\b/gi) ?? []).length },
  { name: 'n_possessive', fn: t => (t.match(/\b(?:my|his|her|their|our|its)\b/gi) ?? []).length },
  { name: 'n_commas', fn: t => (t.match(/,/g) ?? []).length },
  { name: 'n_unique_word_ratio', fn: (t) => {
    const w = t.toLowerCase().split(/\s+/).filter(Boolean)
    return w.length ? new Set(w).size / w.length : 0
  } },
  { name: 'cur_predictSalience', fn: t => predictSalience(t, []).total },
]

const allScores: Record<string, number[]> = {}
const labels: number[] = []
for (const c of convs) {
  for (const e of c.episodes) {
    labels.push(c.evidenceIds.has(e.id) ? 1 : 0)
    for (const f of FEATS)
      (allScores[f.name] ??= []).push(f.fn(e.content))
  }
}

process.stdout.write('\n\n=== 单特征 AUC（|AUC−0.5| 越大越有区分力；<0.5 表示方向反了）===\n')
const rows = FEATS
  .map(f => ({ name: f.name, a: auc(allScores[f.name], labels) }))
  .sort((x, y) => Math.abs(y.a - 0.5) - Math.abs(x.a - 0.5))
for (const r of rows) {
  const dir = r.a > 0.5 ? '正相关' : '负相关'
  process.stdout.write(`  ${r.name.padEnd(22)} AUC=${r.a.toFixed(3)}  ${dir}\n`)
}

// ---- 长度分层：长句是否更容易被引用？ ----
process.stdout.write('\n=== 按 token 长度分层的正例率 ===\n')
const buckets: [number, number, string][] = [[0, 4, '1-4'], [5, 9, '5-9'], [10, 19, '10-19'], [20, 39, '20-39'], [40, 9999, '40+']]
for (const [lo, hi, name] of buckets) {
  const idx = allScores.len_tokens.map((v, i) => (v >= lo && v <= hi ? i : -1)).filter(i => i >= 0)
  const p = idx.filter(i => labels[i] === 1).length
  process.stdout.write(`  ${name.padStart(6)} tokens : n=${String(idx.length).padStart(5)}  positive=${pct(p, idx.length)}\n`)
}
