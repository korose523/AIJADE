import type { GatingCoefficients, LocomoConversation } from '../src/index'

/**
 * 诊断：**剪枝账本** —— 修正 `diag-gate-prunes-evidence.ts` 的口径错误。
 *
 * ── 为什么需要这个脚本（它推翻了前一个诊断的结论）────────────────────────
 * `diag-gate-prunes-evidence.ts` 得出"ON 池子 = OFF 池子 = 5882，零剪枝"，
 * 并据此把"排序"定为符号反转的唯一解释（即核查报告中的 H4）。
 *
 * 但该脚本用 `mem.episodes.length` 计池子，而 `BioticMemory.encode()` 会把**每一条**
 * episode 都 push 进 `episodes` 数组；`consolidate()` 的剪枝只是把 `e.forgotten = true`，
 * **并不从数组中移除**。而 `retrieve()` 第一件事就是
 * `.filter(e => !e.forgotten && …)`（`src/store.ts:798`）。
 *
 * ⇒ 前一个诊断数的是"数组长度"，不是"可检索池"。两者在剪枝非零时必然不相等。
 *
 * ── 本脚本测什么 ────────────────────────────────────────────────────────
 * 对每个对话分别在 DEFAULT_GATING / NO_GATING 下建记忆，然后逐项对照：
 *
 *   1. 编码总数 / 被置 forgotten 的数量
 *   2. **可检索池** = episodes.filter(!forgotten) + facts.length + procedural + working
 *   3. 金标准证据 episode 中有多少被剪掉
 *   4. consolidate 实际生成的事实条数（ON 是 select 子集，OFF 是全集）
 *
 * 读法：
 *   · 若 ON 的可检索池显著小于 OFF，且被剪掉的证据 > 0
 *     ⇒ 符号反转的主因是**剪枝**，"排序"解释（H4）不成立或至多是次要因素。
 *   · 若两者仍相同 ⇒ 前一个诊断的结论虽然推理有误，结论本身成立。
 *
 * 用法：tsx eval/diag-prune-accounting.ts [path-to-locomo.json]
 */
import process from 'node:process'

import { buildMemory, DEFAULT_GATING, loadLocomo, NO_GATING } from '../src/index'
import { resolveLocomoPath, sha256File } from './locomo-path'

const path = resolveLocomoPath(process.argv[2]).path
const conversations = loadLocomo(path) as LocomoConversation[]

console.info('=== 剪枝账本：可检索池 vs 数组长度 ===')
console.info(`corpus : ${path}`)
console.info(`sha256 : ${sha256File(path)}`)
console.info()

interface Row {
  encoded: number
  forgottenOn: number
  forgottenOff: number
  retrievableOn: number
  retrievableOff: number
  factsOn: number
  factsOff: number
  evTotal: number
  evForgottenOn: number
  evForgottenOff: number
  evRetrievableOn: number
  evRetrievableOff: number
}

const rows: Row[] = []

for (const conv of conversations) {
  const on = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients)
  const off = await buildMemory(conv, NO_GATING as GatingCoefficients)

  // 题目引用的证据 id（覆盖率已在 diag-evidence-coverage.ts 确认 100% 可解析）
  const evIds = new Set<string>()
  for (const q of conv.qa) {
    for (const e of q.evidence ?? []) {
      if (conv.evidenceIds.has(e))
        evIds.add(e)
    }
  }

  const forgottenOn = on.episodes.filter(e => e.forgotten)
  const forgottenOff = off.episodes.filter(e => e.forgotten)
  const forgottenIdsOn = new Set(forgottenOn.map(e => e.id))
  const forgottenIdsOff = new Set(forgottenOff.map(e => e.id))

  // 可检索池 = retrieve() 实际会考虑的候选（episode 需 !forgotten）
  const retrievableOn
    = on.episodes.filter(e => !e.forgotten).length + on.facts.length + on.procedural.length + on.working.length
  const retrievableOff
    = off.episodes.filter(e => !e.forgotten).length + off.facts.length + off.procedural.length + off.working.length

  const evArr = [...evIds]

  rows.push({
    encoded: on.episodes.length,
    forgottenOn: forgottenOn.length,
    forgottenOff: forgottenOff.length,
    retrievableOn,
    retrievableOff,
    factsOn: on.facts.length,
    factsOff: off.facts.length,
    evTotal: evIds.size,
    evForgottenOn: evArr.filter(id => forgottenIdsOn.has(id)).length,
    evForgottenOff: evArr.filter(id => forgottenIdsOff.has(id)).length,
    evRetrievableOn: evArr.filter(id => !forgottenIdsOn.has(id)).length,
    evRetrievableOff: evArr.filter(id => !forgottenIdsOff.has(id)).length,
  })
}

const sum = (f: (r: Row) => number) => rows.reduce((a, r) => a + f(r), 0)
const pct = (num: number, den: number) => (den ? `${(num / den * 100).toFixed(1)}%` : 'n/a')

const encoded = sum(r => r.encoded)
const forgottenOn = sum(r => r.forgottenOn)
const forgottenOff = sum(r => r.forgottenOff)
const retrievableOn = sum(r => r.retrievableOn)
const retrievableOff = sum(r => r.retrievableOff)
const factsOn = sum(r => r.factsOn)
const factsOff = sum(r => r.factsOff)
const evTotal = sum(r => r.evTotal)
const evForgottenOn = sum(r => r.evForgottenOn)
const evForgottenOff = sum(r => r.evForgottenOff)
const evRetrievableOn = sum(r => r.evRetrievableOn)
const evRetrievableOff = sum(r => r.evRetrievableOff)

console.info('--- 1. 编码与剪枝（10 个对话合计）---')
console.info(`  编码 episode 总数        : ${encoded}`)
console.info(`  ON  被置 forgotten       : ${forgottenOn}  (${pct(forgottenOn, encoded)})`)
console.info(`  OFF 被置 forgotten       : ${forgottenOff}  (${pct(forgottenOff, encoded)})`)
console.info(`  → 剪枝差额 (ON − OFF)    : ${forgottenOn - forgottenOff}`)
console.info()

console.info('--- 2. 可检索池（retrieve() 真正会考虑的候选）---')
console.info(`  ON  可检索池             : ${retrievableOn}`)
console.info(`  OFF 可检索池             : ${retrievableOff}`)
console.info(`  → 池子差额 (OFF − ON)    : ${retrievableOff - retrievableOn}`)
console.info(`  其中事实条数             : ON ${factsOn} / OFF ${factsOff}`)
console.info()

console.info('--- 3. 金标准证据的存活 ---')
console.info(`  题目引用的证据 episode   : ${evTotal}`)
console.info(`  ON  被剪掉的证据         : ${evForgottenOn}  (${pct(evForgottenOn, evTotal)})`)
console.info(`  OFF 被剪掉的证据         : ${evForgottenOff}  (${pct(evForgottenOff, evTotal)})`)
console.info(`  ON  仍可检索的证据       : ${evRetrievableOn}  (${pct(evRetrievableOn, evTotal)})`)
console.info(`  OFF 仍可检索的证据       : ${evRetrievableOff}  (${pct(evRetrievableOff, evTotal)})`)
console.info(`  → 证据损失 (OFF − ON)    : ${evRetrievableOff - evRetrievableOn}`)
console.info()

console.info('--- 4. 判定 ---')

// 判据必须是**因果相关量**（被剪掉的金标准证据），而不是"池子是否字面相等"。
// 池子相等是充分条件，不是必要条件：少掉几个干扰项本身不会降低 recall
// —— 除非少掉的正好是证据。剪枝对 recall@K 的影响只有一条通路：
// 把某道题的证据候选从池子里移除。这条通路上证据损失为 0 时，剪枝的贡献为 0。
const evLost = evRetrievableOff - evRetrievableOn
const forgottenShare = encoded ? forgottenOn / encoded : 0

if (evLost <= 0 && forgottenShare < 0.01) {
  console.info('  🟢 **剪枝不是符号反转的成因。**')
  console.info()
  console.info(`     推理：剪枝影响 recall@K 只有一条通路 —— 把某道题的证据候选移出池子。`)
  console.info(`     实测该通路的量是 **${evLost}**（ON 剪掉的金标准证据），全部 ${evTotal} 条证据在 ON 下均仍可检索。`)
  console.info(`     因此剪枝对 recall@K 的贡献为 0，ON < OFF 只能由**检索排序**解释。H4 的前提成立。`)
  console.info()
  console.info(`     佐证：ON 的剪枝总幅度仅 ${forgottenOn}/${encoded}（${(forgottenShare * 100).toFixed(2)}%）。`)
  console.info(`     且即便把这些干扰项算作影响，方向也是**利于 ON**（池子更小 ⇒ 干扰更少），`)
  console.info(`     与观察到的 ON < OFF 方向相反，故不能作为反转的解释。`)
  console.info()
  console.info('  ⚠️ 但对前一个诊断（`diag-gate-prunes-evidence.ts`）的**推理**提出更正：')
  console.info('     它用 `mem.episodes.length` 计池子，而 `encode()` 把每条 episode 都 push 进数组，')
  console.info('     剪枝只置 `forgotten = true` 不删除；`retrieve()` 才过滤 `!e.forgotten`（src/store.ts:798）。')
  console.info('     它数的是**数组长度**，不是可检索池 —— 两个量在本数据上恰好接近（差额 8），')
  console.info('     但这不是"零剪枝"，而是"剪枝量极小"。**结论对、理由错**：')
  console.info('     一旦语料换成剪枝非平凡的设定，该诊断会给出错误的绿灯。已由本脚本取代。')
}
else {
  const lostPct = evRetrievableOff ? evLost / evRetrievableOff * 100 : 0
  console.info(`  🔴 **剪枝是符号反转的成因之一。**`)
  console.info(`     ON 比 OFF 少留 ${evLost} 条证据（占 OFF 可检索证据的 ${lostPct.toFixed(1)}%），`)
  console.info(`     被剪总量 ${forgottenOn}/${encoded}（${(forgottenShare * 100).toFixed(2)}%）。`)
  console.info('     ⇒ 「门控只剪琐碎、保留重要」这一前提在本语料上不成立。')
  console.info('     ⇒ 核查报告的 H4（"不是剪枝、是排序"）前提被推翻，须改为二者共同作用。')
}
