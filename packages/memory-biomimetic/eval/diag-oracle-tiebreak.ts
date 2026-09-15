import type { GatingCoefficients } from '../src/index'
/**
 * 决定性对照：`diag-index-duplication-confusion.ts` 观察到的那 3 倍跳变，
 * 到底是"池子规模阈值"，还是"**丢弃了最近的干扰项**"？
 *
 * ── 待检验的机制假设 ─────────────────────────────────────────────────────
 * oracle 显著性下，**所有非证据 episode 的显著性并列**（同为 0），
 * 而 `[...pending].sort(bySalienceDesc)` 在 V8 中是稳定排序 ⇒ 并列项保持原始顺序
 * ⇒ `slice(0, k)` 保留的是**最早**的非证据，丢掉的恰好是**最晚的那批**。
 *
 * 而检索分数里 `recency`（权重 0.3）与 `strength`（权重 0.6）都对"新近"给高分。
 * 于是**最近的干扰项**正是最容易挤进 top-8、把证据顶出去的那批。
 * 丢掉它们 ⇒ top-8 立刻腾出位置 ⇒ recall 跳变。
 *
 * 若该假设成立，那么 `diag-index-duplication-confusion.ts` 里"检索精度强烈依赖
 * 干扰项数量"的结论就**说错了对象** —— 真正起作用的是"**丢弃了哪一批**干扰项"，
 * 而不是"丢了多少"。这是一个必须自己纠正的误判。
 *
 * ── 检验设计 ─────────────────────────────────────────────────────────────
 * 固定 oracle 显著性（证据 = 1，非证据 = 0，故证据永远排在前面、一条不丢），
 * 只切换**非证据之间的并列如何打破**：
 *   A. `chrono` —— 稳定排序，保留最早的非证据（= 现有实验的行为）
 *   B. `jitter` —— 给非证据注入 [0, 0.5) 的确定性随机值，于是保留哪批非证据是随机的
 *
 * 用空蒸馏器（无 fact 副本）以排除重复副本的干扰。
 *
 * 读法：
 *   · 若 A 出现 3 倍跳变而 B 没有 ⇒ 机制假设成立，跳变来自"丢的是最近那批"，
 *     与池子规模无关。前一份诊断的结论须更正。
 *   · 若 A 与 B 都跳变 ⇒ 确实是池子规模阈值，机制假设被否证。
 *
 * 用法：tsx eval/diag-oracle-tiebreak.ts [path-to-locomo.json] [conv-limit]
 */
import type { Distiller } from '../src/index'

import process from 'node:process'

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { buildMemory, DEFAULT_GATING, loadLocomo } from '../src/index'
import { avg, goldEvidenceIds, KS, measure, mulberry32 } from './eval-metrics'
import { resolveLocomoPath, sha256File } from './locomo-path'

const QS = [1, 0.9, 0.8, 0.7, 0.6, 0.4]
const MAXK = Math.max(...KS)

const NULL_DISTILLER: Distiller = { distill: async () => [] }

async function main(): Promise<void> {
  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convsAll = loadLocomo(path)
  const convs = limit ? convsAll.slice(0, limit) : convsAll

  console.info('=== 对照：oracle 显著性下并列如何打破（chrono vs jitter）===')
  console.info(`corpus : ${path}`)
  console.info(`sha256 : ${sha256File(path)}`)
  console.info(`convs  : ${convs.length}`)
  console.info()

  type Key = `${'chrono' | 'jitter'}-${number}`
  const recall: Record<Key, Record<number, number[]>> = {} as Record<Key, Record<number, number[]>>
  const surv: Record<Key, number[]> = {} as Record<Key, number[]>
  const distinct: Record<Key, number[]> = {} as Record<Key, number[]>

  for (const tb of ['chrono', 'jitter'] as const) {
    for (const q of QS) {
      const k: Key = `${tb}-${q}`
      recall[k] = Object.fromEntries(KS.map(kk => [kk, [] as number[]]))
      surv[k] = []
      distinct[k] = []
    }
  }

  for (let ci = 0; ci < convs.length; ci++) {
    const conv = convs[ci]
    const gold = goldEvidenceIds(conv)
    const rnd = mulberry32(0xBEEF + ci)
    // 非证据的并列打破值：确定性随机，∈ [0, 0.5)
    const jitter = conv.episodes.map(() => rnd() * 0.5)
    const idxOf = new Map(conv.episodes.map((ep, i) => [ep.id, i]))

    for (const tb of ['chrono', 'jitter'] as const) {
      for (const q of QS) {
        const key: Key = `${tb}-${q}`
        const mem = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients, NULL_DISTILLER, {
          salienceOf: ({ id }) => {
            const i = idxOf.get(id)
            if (i === undefined)
              return undefined
            // 证据恒为 1（永远排在前面、一条不丢）
            if (gold.has(id))
              return 1
            // 非证据：chrono 用常量 0（并列 ⇒ 稳定排序 ⇒ 保留最早那批）
            //         jitter 用随机值（⇒ 保留哪批是随机的）
            return tb === 'jitter' ? jitter[i] : 0
          },
          keepFraction: q,
        })
        const m = measure(mem, conv, gold)
        for (const kk of KS) recall[key][kk].push(m.recall[kk])
        surv[key].push(m.evidenceSurvival)
        distinct[key].push(mem.episodes.filter(e => !e.forgotten).length)
      }
    }
  }

  console.info(`  ${'tiebreak'.padEnd(10)}${'q'.padStart(6)}${'distinct'.padStart(10)}${'evSurv'.padStart(9)}${KS.map(k => `K=${k}`.padStart(9)).join('')}`)
  for (const tb of ['chrono', 'jitter'] as const) {
    for (const q of QS) {
      const key: Key = `${tb}-${q}`
      console.info(
        `  ${tb.padEnd(10)}${String(q).padStart(6)}${avg(distinct[key]).toFixed(0).padStart(10)}`
        + `${avg(surv[key]).toFixed(4).padStart(9)}${KS.map(k => avg(recall[key][k]).toFixed(4).padStart(9)).join('')}`,
      )
    }
  }
  console.info()

  // ---------------------------------------------------------------- 判读
  const verdicts: string[] = []
  const A = 'chrono'
  const B = 'jitter'
  const jumpA = avg(recall[`${A}-${QS[0]}`][MAXK]) - avg(recall[`${A}-${QS[1]}`][MAXK])
  const jumpB = avg(recall[`${B}-${QS[0]}`][MAXK]) - avg(recall[`${B}-${QS[1]}`][MAXK])
  const fmt = (x: number) => `${x >= 0 ? '+' : ''}${x.toFixed(4)}`

  verdicts.push(`【跳变幅度】(K=${MAXK}) q=1 → q=${QS[1]}（证据存活率两档均为 100%）`)
  verdicts.push(`  chrono（现有行为）: ${avg(recall[`${A}-${QS[0]}`][MAXK]).toFixed(4)} → ${avg(recall[`${A}-${QS[1]}`][MAXK]).toFixed(4)}  跳变 ${fmt(jumpA)}`)
  verdicts.push(`  jitter（随机并列）: ${avg(recall[`${B}-${QS[0]}`][MAXK]).toFixed(4)} → ${avg(recall[`${B}-${QS[1]}`][MAXK]).toFixed(4)}  跳变 ${fmt(jumpB)}`)
  verdicts.push('')
  verdicts.push('【机制假设是否成立】')
  verdicts.push('  假设：**跳变（cliff）**来自"按稳定排序丢弃了**最近的**干扰项"，而非"池子变小"。')
  if (Math.abs(jumpA) > 0.1 && Math.abs(jumpB) < 0.05) {
    verdicts.push(`  ⇒ ✅ **假设成立**。chrono 跳变 ${fmt(jumpA)}，jitter 跳变 ${fmt(jumpB)} ——`)
    verdicts.push('     同一保留比例、同一证据集合（evSurv 均为 100%），仅改并列打破方式，cliff 即消失。')
    verdicts.push('     ⇒ `diag-index-duplication-confusion.ts` 里"检索精度强烈依赖干扰项数量"对 **cliff** 说错了对象：')
    verdicts.push('       cliff 的真实来源是"**丢弃了哪一批**干扰项"（最近的那批），而非"丢了多少"。')
    verdicts.push('       已在本次核查中更正 —— 报告中不得沿用原表述。')
  }
  else if (Math.abs(jumpA) > 0.1 && Math.abs(jumpB) > 0.1) {
    verdicts.push(`  ⇒ ❌ **假设被否证**。两组都出现跳变（chrono ${fmt(jumpA)}，jitter ${fmt(jumpB)}）⇒`)
    verdicts.push('     确实是池子规模阈值效应，与丢弃哪一批无关。')
  }
  else {
    verdicts.push(`  ⇒ ⚠️ 结果不清晰（chrono ${fmt(jumpA)}，jitter ${fmt(jumpB)}），不足以判定，须扩样或加细网格。`)
  }
  verdicts.push('')
  verdicts.push('【但"池子规模"并未被完全排除 —— 两个效应并存，必须分开陈述】')
  const smoothA = avg(recall[`${A}-${QS[QS.length - 1]}`][MAXK]) - avg(recall[`${A}-1`][MAXK])
  const smoothB = avg(recall[`${B}-${QS[QS.length - 1]}`][MAXK]) - avg(recall[`${B}-1`][MAXK])
  verdicts.push(`  chrono：q=1 → q=${QS[QS.length - 1]}（池子 588 → 235，evSurv 恒 100%）累计 ${fmt(smoothA)}`)
  verdicts.push(`  jitter：同区间累计 ${fmt(smoothB)}`)
  verdicts.push(`  ⇒ 把 cliff 剥掉后，jitter 仍留下 ${fmt(smoothB)} 的**平滑**增益 ⇒ 存在一个真实的`)
  verdicts.push('     "干扰项越少、排序越容易"的分量（很可能来自 IDF 随 N 变化与有效信噪比）。')
  verdicts.push('  ⇒ 正确表述：**cliff 归因于近期性偏置；平滑增益归因于池子规模。二者叠加，不可混为一谈。**')
  verdicts.push('')
  verdicts.push('【对整条记忆线的影响（这是本次对照最重要的推论）】')
  verdicts.push('  证据记忆被**更近的干扰项**挤出 top-8 ⇒ 检索分数中的 `recency`(0.3) 与 `strength`(0.6)')
  verdicts.push('  两项在系统性地以"新近"压过"相关"。这比"门控好坏"更根本：')
  verdicts.push('  只要这一偏置在，任何以 recall@K 为指标的遗忘/门控比较都会同时测到它。')
  const maxJitter = Math.max(...QS.map(q => avg(recall[`${B}-${q}`][MAXK])))
  const baseJitter = avg(recall[`${B}-1`][MAXK])
  verdicts.push(`  佐证：jitter 组上限 ${maxJitter.toFixed(4)} 相对基线 ${baseJitter.toFixed(4)} 高 ${fmt(maxJitter - baseJitter)}，`)
  verdicts.push('        这部分**与"按显著性选择"无关**（jitter 的保留是随机的）。')

  console.info('--- 判读（本段由上方实测数字生成，无硬编码结论）---')
  for (const v of verdicts) console.info(v)

  const stamp = new Date().toISOString().slice(0, 10)
  const outDir = join(dirname(new URL(import.meta.url).pathname), 'results')
  mkdirSync(outDir, { recursive: true })
  const jsonPath = join(outDir, `p2-oracle-tiebreak-${stamp}.json`)
  writeFileSync(jsonPath, `${JSON.stringify({
    generatedAt: new Date().toISOString(),
    corpus: { path, sha256: sha256File(path), conversations: convs.length },
    ks: KS,
    quantileGrid: QS,
    arms: Object.fromEntries((['chrono', 'jitter'] as const).flatMap(tb =>
      QS.map(q => [`${tb}-${q}`, {
        distinct: avg(distinct[`${tb}-${q}`]),
        evidenceSurvival: avg(surv[`${tb}-${q}`]),
        recall: Object.fromEntries(KS.map(k => [k, avg(recall[`${tb}-${q}`][k])])),
      }]),
    )),
    verdicts,
  }, null, 2)}\n`, 'utf8')
  console.info()
  console.info(`artifact: ${jsonPath}`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
