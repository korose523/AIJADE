/**
 * 诊断：LoCoMo 的 gold-evidence 标签**覆盖率**。
 *
 * ── 为什么必须单独测这个 ─────────────────────────────────────────────────
 * `src/locomo.ts` 的 `evidenceRecall()` 在遇到"证据 id 不在 `conv.evidenceIds` 里"时
 * 执行的是 `continue` —— **静默跳过**。后果是：
 *
 *   · 某题的证据 id 全部未匹配 ⇒ `candidates` 为空集 ⇒ `hit` 恒为 false；
 *   · 该题被计为"未召回"，与"检索器没找到"**无法区分**；
 *   · 最终 recall@K 偏低时，读者会归因于检索器弱，而不是标签没对上。
 *
 * 这正是本脚本要排除的可能：在讨论"门控是否提升检索"之前，
 * 必须先确认**金标准标签本身解析成功了**。
 *
 * 输出三项：
 *   1. 题目级覆盖率    —— 有 ≥1 个证据 id 能匹配上的题目占比；
 *   2. 证据级覆盖率    —— 所有证据 id 中能匹配上的比例；
 *   3. 未匹配 id 的样例与形态 —— 用于判断是 id 体系不同还是数据损坏。
 *
 * 用法：tsx eval/diag-evidence-coverage.ts [path-to-locomo.json]
 */
import process from 'node:process'

import { loadLocomo } from '../src/index'
import { resolveLocomoPath, sha256File } from './locomo-path'

const path = resolveLocomoPath(process.argv[2]).path
const conversations = loadLocomo(path)

console.info('=== LoCoMo gold-evidence 覆盖率诊断 ===')
console.info(`corpus       : ${path}`)
console.info(`sha256       : ${sha256File(path)}`)
console.info(`conversations: ${conversations.length}`)
console.info()

let qTotal = 0
let qWithEvidenceField = 0
let qWithAtLeastOneMatch = 0
let qWithZeroMatch = 0
let evTotal = 0
let evMatched = 0
const unmatchedSamples: string[] = []
const matchedSamples: string[] = []
/** 每题的 (题目索引, 证据数, 匹配数)，用于看分布 */
const perQuestion: { q: number, ev: number, hit: number }[] = []

for (const conv of conversations) {
  const ids: Set<string> = conv.evidenceIds
  conv.qa.forEach((q, qi) => {
    qTotal++
    const ev = q.evidence ?? []
    if (ev.length > 0)
      qWithEvidenceField++
    let hits = 0
    for (const e of ev) {
      evTotal++
      if (ids.has(e)) {
        evMatched++
        hits++
        if (matchedSamples.length < 8)
          matchedSamples.push(e)
      }
      else if (unmatchedSamples.length < 12) {
        unmatchedSamples.push(`${e}   (样本 ${conv.sampleId ?? '?'}, 题 ${qi})`)
      }
    }
    if (ev.length > 0) {
      if (hits > 0)
        qWithAtLeastOneMatch++
      else
        qWithZeroMatch++
    }
    perQuestion.push({ q: qi, ev: ev.length, hit: hits })
  })
}

const pct = (a: number, b: number) => (b === 0 ? 'n/a' : `${(a / b * 100).toFixed(1)}%`)

console.info('--- 1. 题目级 ---')
console.info(`  题目总数                     : ${qTotal}`)
console.info(`  有 evidence 字段的题目        : ${qWithEvidenceField}  (${pct(qWithEvidenceField, qTotal)})`)
console.info(`  ≥1 个证据 id 能匹配           : ${qWithAtLeastOneMatch}  (${pct(qWithAtLeastOneMatch, qTotal)})`)
console.info(`  有证据但**一个都匹配不上**     : ${qWithZeroMatch}  (${pct(qWithZeroMatch, qTotal)})   ← 这些题恒判未召回`)
console.info()
console.info('--- 2. 证据级 ---')
console.info(`  证据 id 总数                  : ${evTotal}`)
console.info(`  能匹配上                      : ${evMatched}  (${pct(evMatched, evTotal)})`)
console.info()
console.info('--- 3. 匹配样例 ---')
console.info(`  匹配上的 id 样例 : ${matchedSamples.join(', ') || '(无)'}`)
console.info(`  未匹配的 id 样例 : ${unmatchedSamples.join('\n                     ') || '(无)'}`)
console.info()
console.info('--- 4. 诊断结论 ---')
if (evTotal === 0) {
  console.info('  🔴 全部题目都没有 evidence 字段 ⇒ 语料 schema 与代码预期不符，任何 recall 数字都无意义。')
}
else if (evMatched === 0) {
  console.info('  🔴 证据 id **一个都没匹配上**。')
  console.info('     ⇒ recall@K 恒为 0，与检索器/门控无关。')
  console.info('     ⇒ 在读任何 recall 数字之前必须先修标签解析。')
}
else if (evMatched / evTotal < 0.5) {
  console.info(`  🔴 证据级覆盖率仅 ${pct(evMatched, evTotal)} ⇒ recall@K 被系统性压低，`)
  console.info('     现有 recall 数字**不可用于比较 ON/OFF**（两侧被同等压低，但压低幅度未知）。')
}
else {
  console.info(`  🟢 证据级覆盖率 ${pct(evMatched, evTotal)}，标签解析基本正常；`)
  console.info('     recall@K 的组间比较可以用，但仍需在论文中报告该覆盖率。')
}
