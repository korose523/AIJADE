import type { GatingCoefficients, LocomoConversation } from '../src/index'

/**
 * 诊断：门控 ON 是否**把金标准证据本身剪掉了**？
 *
 * ── 这一步要回答什么 ────────────────────────────────────────────────────
 * 已排除两条解释：
 *   · 标签失配      —— 证据 id 覆盖率 100%（`diag-evidence-coverage.ts`）
 *   · 指标阈值      —— 0% 命中项跌破 floor，带/不带 floor 结果完全相同（`diag-floor-effect.ts`）
 *
 * 剩下一个更根本的可能：
 *   **ON 剪枝时把问题所引用的证据记忆一并剪掉了。**
 *   若如此，"ON 检索精度更高"在前提上就不成立 —— 不在池子里的东西不可能被检索到。
 *   这也解释了重跑观察到的组合特征：ON 命中项**平均分更高**（竞争者被清掉了）
 *   但**命中率更低**（证据自己也被清掉了）。
 *
 * ── 与 P1 的关系 ─────────────────────────────────────────────────────────
 * `p1-evidence-retention` 这一对比是本项目**最早的核心主张**：
 * 门控 ON 应当"重要记忆存活率高、琐碎记忆崩塌"。
 * 本脚本直接测其前提：证据记忆在 ON 下是否真的存活。
 *
 * 用法：tsx eval/diag-gate-prunes-evidence.ts [path-to-locomo.json]
 */
import process from 'node:process'

import { buildMemory, DEFAULT_GATING, loadLocomo, NO_GATING } from '../src/index'
import { resolveLocomoPath, sha256File } from './locomo-path'

const path = resolveLocomoPath(process.argv[2]).path
const conversations = loadLocomo(path) as LocomoConversation[]

console.info('=== 门控是否剪掉金标准证据 ===')
console.info(`corpus : ${path}`)
console.info(`sha256 : ${sha256File(path)}`)
console.info()

interface Row {
  poolOn: number
  poolOff: number
  evTotal: number
  evKeptOn: number
  evKeptOff: number
  trivialDropped: number
}

const rows: Row[] = []

for (const conv of conversations) {
  const on = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients)
  const off = await buildMemory(conv, NO_GATING as GatingCoefficients)

  // 题目引用的证据 id（已确认 100% 可解析）
  const evIds = new Set<string>()
  for (const q of conv.qa) {
    for (const e of q.evidence ?? []) {
      if (conv.evidenceIds.has(e))
        evIds.add(e)
    }
  }

  const poolOn = on.episodes.length
  const poolOff = off.episodes.length

  // 记忆池中仍存活的证据（episode id 可能是裸 id 或 fact_ 前缀）
  const idsOn = new Set(on.episodes.map(e => e.id))
  const idsOff = new Set(off.episodes.map(e => e.id))
  const evKept = (ids: Set<string>) => [...evIds].filter(id => ids.has(id) || ids.has(`fact_${id}`)).length

  rows.push({
    poolOn,
    poolOff,
    evTotal: evIds.size,
    evKeptOn: evKept(idsOn),
    evKeptOff: evKept(idsOff),
    trivialDropped: poolOff - poolOn,
  })
}

const sum = (f: (r: Row) => number) => rows.reduce((a, r) => a + f(r), 0)
const poolOn = sum(r => r.poolOn)
const poolOff = sum(r => r.poolOff)
const evTotal = sum(r => r.evTotal)
const evKeptOn = sum(r => r.evKeptOn)
const evKeptOff = sum(r => r.evKeptOff)

console.info('--- 记忆池规模（10 个对话合计）---')
console.info(`  ON  池子 : ${poolOn}`)
console.info(`  OFF 池子 : ${poolOff}`)
console.info(`  被剪掉   : ${poolOff - poolOn}  (${((poolOff - poolOn) / poolOff * 100).toFixed(1)}% 的 OFF 池子)`)
console.info()
console.info('--- 金标准证据的存活 ---')
console.info(`  题目引用的证据 id 总数 : ${evTotal}`)
console.info(`  ON  下存活             : ${evKeptOn}  (${(evKeptOn / evTotal * 100).toFixed(1)}%)`)
console.info(`  OFF 下存活             : ${evKeptOff}  (${(evKeptOff / evTotal * 100).toFixed(1)}%)`)
console.info(`  差额 (ON - OFF)        : ${evKeptOn - evKeptOff}`)
console.info()
console.info('--- 判定 ---')
const lost = evKeptOff - evKeptOn
if (lost <= 0) {
  console.info('  🟢 ON 没有比 OFF 少留证据 ⇒ 剪枝未伤及证据；')
  console.info('     那么 ON 命中率更低的原因在**排序**而非**剪枝**，需查 src/retrieval.ts。')
}
else {
  const pct = lost / evKeptOff * 100
  console.info(`  🔴 ON 比 OFF **少留了 ${lost} 条证据**（占 OFF 存活证据的 ${pct.toFixed(1)}%）。`)
  console.info('     ⇒ 门控在剪掉"琐碎"记忆的同时，也剪掉了问题真正引用的记忆。')
  console.info('     ⇒ "门控只剪琐碎、保留重要"这一前提在本语料上**不成立**。')
  if (pct > 10)
    console.info(`     ⇒ 损失幅度 ${pct.toFixed(1)}% 足以解释 recall@K 的符号反转（ON 0.058 < OFF 0.070）。`)
  console.info('     ⇒ 后续必须先修显著性准则（当前 predictSalienceV2 AUC≈0.81，会误剪），')
  console.info('        或把门控改为"部分衰减"而非二元剪枝，否则任何检索层比较都不成立。')
}
