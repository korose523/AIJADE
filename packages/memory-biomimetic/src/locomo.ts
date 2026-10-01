import type { Distiller } from './consolidation'
import type { Episode, GatingCoefficients, MemoryConfig, RetrievalWeights } from './types'

import { readFileSync } from 'node:fs'

import { LexicalDistiller } from './consolidation'
import { retrievalStrength } from './forgetting'
import { tokenize } from './sim'
import { BioticMemory } from './store'
import { DEFAULT_MEMORY_CONFIG } from './types'

/** ms per day — used to walk the forgetting horizon. */
export const DAY = 86_400_000

const MONTHS: Record<string, number> = {
  january: 0,
  february: 1,
  march: 2,
  april: 3,
  may: 4,
  june: 5,
  july: 6,
  august: 7,
  september: 8,
  october: 9,
  november: 10,
  december: 11,
  jan: 0,
  feb: 1,
  mar: 2,
  apr: 3,
  jun: 5,
  jul: 6,
  aug: 7,
  sep: 8,
  sept: 8,
  oct: 9,
  nov: 10,
  dec: 11,
}

/**
 * Parse LoCoMo's free-form session timestamps, e.g. "1:56 pm on 8 May, 2023".
 * Falls back to a deterministic per-session offset if unparseable.
 */
export function parseLocomoDate(s: string): number | null {
  const withTime = s.match(/(\d{1,2}):(\d{2})\s*(am|pm).*?(\d{1,2})\s+([a-z]+),?\s*(\d{4})/i)
  if (withTime) {
    let hh = Number(withTime[1])
    const mm = Number(withTime[2])
    const ap = withTime[3].toLowerCase()
    const day = Number(withTime[4])
    const mon = MONTHS[withTime[5].toLowerCase()]
    const yr = Number(withTime[6])
    if (mon === undefined)
      return null
    if (ap === 'pm' && hh !== 12)
      hh += 12
    if (ap === 'am' && hh === 12)
      hh = 0
    return Date.UTC(yr, mon, day, hh, mm, 0)
  }
  const dateOnly = s.match(/(\d{1,2})\s+([a-z]+),?\s*(\d{4})/i)
  if (dateOnly) {
    const day = Number(dateOnly[1])
    const mon = MONTHS[dateOnly[2].toLowerCase()]
    const yr = Number(dateOnly[3])
    if (mon === undefined)
      return null
    return Date.UTC(yr, mon, day, 12, 0, 0)
  }
  return null
}

export interface LocomoQuestion {
  question: string
  answer: string
  evidence: string[]
  category: number
}

export interface LocomoConversation {
  sampleId: string
  episodes: Episode[]
  qa: LocomoQuestion[]
  /** All dia_ids referenced by any question's evidence. */
  evidenceIds: Set<string>
  /** Max session timestamp — used as the "present" for the forgetting sim. */
  endTs: number
}

interface RawConversation {
  sample_id: string
  conversation: Record<string, unknown>
  qa: LocomoQuestion[]
}

/**
 * Map a LoCoMo conversation into episodes.
 *
 * Salience assumption (stated, not hidden): a turn whose `dia_id` is referenced
 * by some question's gold `evidence` is treated as a "salient" memory — the kind
 * an upstream salience detector would flag. Salient turns are encoded with high
 * dopamine and social weight; the rest with low. This is the input the gating
 * is allowed to act on; under NO_GATING the gate ignores it.
 */
export function parseConversation(raw: RawConversation): LocomoConversation {
  const conv = raw.conversation
  const episodes: Episode[] = []
  const evidenceIds = new Set<string>()
  for (const q of raw.qa) {
    for (const e of q.evidence) evidenceIds.add(e)
  }

  let endTs = 0
  for (const key of Object.keys(conv)) {
    const m = key.match(/^session_(\d+)$/)
    if (!m)
      continue
    const sessNo = Number(m[1])
    const turns = conv[key] as any[]
    if (!Array.isArray(turns))
      continue
    const dtStr = conv[`${key}_date_time`] as string
    const parsed = parseLocomoDate(dtStr)
    const tsBase = parsed ?? (Date.UTC(2023, 0, 1) + sessNo * 86_400_000)
    if (parsed && parsed > endTs)
      endTs = parsed

    for (const t of turns) {
      const diaId = t.dia_id as string
      const salient = evidenceIds.has(diaId)
      const encoding = salient
        ? { salience: 0.9, socialSalience: 0.7, novelty: 0.5, affect: { valence: 0.85, arousal: 0.6, dominance: 0.7 } }
        : { salience: 0.25, socialSalience: 0.15, novelty: 0.5, affect: { valence: 0.5, arousal: 0.4, dominance: 0.5 } }
      const tags: string[] = []
      if (typeof t.query === 'string')
        tags.push(...tokenize(t.query))
      if (typeof t.blip_caption === 'string')
        tags.push(...tokenize(t.blip_caption).slice(0, 5))
      episodes.push({
        id: diaId,
        content: (t.text as string) ?? '',
        createdAt: tsBase + turns.indexOf(t) * 60_000,
        lastAccessedAt: tsBase,
        accessCount: 0,
        baseStrength: 1,
        durability: 1, // set properly by BioticMemory.encode
        encoding,
        context: { sessionId: `session_${sessNo}`, interlocutor: t.speaker as string, task: undefined, tags },
        consolidated: false,
        memoryType: 'episodic',
        status: 'active',
        validTime: {},
      })
    }
  }

  return { sampleId: raw.sample_id, episodes, qa: raw.qa, evidenceIds, endTs }
}

export function loadLocomo(path: string): LocomoConversation[] {
  const raw = JSON.parse(readFileSync(path, 'utf8')) as RawConversation[]
  return raw.map(parseConversation)
}

/**
 * 实验专用选项 —— 让「显著性来源」与「剪枝开关」成为可独立操纵的维度。
 *
 * 引入理由：`DEFAULT_GATING` 同时打开了两个**本应分开考察**的机制
 *   ① 编码期的显著性 → durability/decay 重加权（连续、影响排序）
 *   ② consolidate 的选择性剪枝（离散、影响池子成员）
 * `diag-prune-accounting.ts` 已测出 ② 在本语料上几乎惰性（剪 4/5882，证据零损失），
 * 但"几乎惰性"不等于"零"；要**证明**符号反转出自 ①，必须能把 ② 关掉重跑。
 */
export interface BuildMemoryOptions {
  /**
   * 覆盖单条 episode 的显著性。返回 `undefined` 表示该条走预测器。
   * 用于 oracle（证据=1/其余=0）与 shuffled（保边际、打乱指派）对照。
   */
  salienceOf?: (episode: { id: string, content: string }) => number | undefined
  /** 显式指定 consolidate 是否做选择性剪枝；缺省沿用 gating 推导。 */
  selectiveConsolidation?: boolean
  /**
   * 剪枝**保留比例**（0–1）。给定时启用**排名制**保留策略：保留显著性最高的前
   * `keepFraction` 比例，而不是沿用绝对阈值 `salience > 0.5`。
   *
   * 为什么要这个开关：绝对阈值让"保留多少"由预测器的输出尺度隐含决定，
   * 而 `predictSalienceV2` 的分数几乎恒为正 ⇒ 阈值判定几乎永不触发，
   * 剪枝通道形同关闭（见 `eval/diag-oracle-vs-predicted-salience.ts`）。
   * 给定 keepFraction 后，压缩率变成**显式**的实验变量。
   */
  keepFraction?: number
}

/** Build a memory instance for one conversation under a given gating config. */
export async function buildMemory(
  conv: LocomoConversation,
  gating: GatingCoefficients,
  distiller: Distiller = new LexicalDistiller(),
  opts: BuildMemoryOptions = {},
): Promise<BioticMemory> {
  const config: MemoryConfig = { ...DEFAULT_MEMORY_CONFIG, gating }
  const mem = new BioticMemory(config, conv.endTs)
  for (const ep of conv.episodes) {
    mem.encode({
      id: ep.id,
      content: ep.content,
      createdAt: ep.createdAt,
      context: ep.context,
      baseStrength: ep.baseStrength,
      salienceOverride: opts.salienceOf?.({ id: ep.id, content: ep.content }),
    })
  }
  await mem.consolidate(distiller, {
    selective: opts.selectiveConsolidation,
    keepFraction: opts.keepFraction,
  })
  return mem
}

export interface RecallResult {
  overall: number
  covered: number
  total: number
  byCategory: Record<number, number>
}

/**
 * Evidence recall: for each question, is its gold-evidence content (the source
 * episode and/or its distilled fact) present in the top-K retrieved candidates
 * and above the retrieval floor? This isolates the *memory dynamics* from any
 * LLM answer skill — it only asks "did the right memory surface?".
 */
export function evidenceRecall(mem: BioticMemory, conv: LocomoConversation, topK = 10, weights?: Partial<RetrievalWeights>): RecallResult {
  let covered = 0
  const byCat: Record<number, { cov: number, tot: number }> = {}
  for (const q of conv.qa) {
    const candidates = new Set<string>()
    for (const e of q.evidence) {
      if (!conv.evidenceIds.has(e))
        continue
      candidates.add(e)
      candidates.add(`fact_${e}`)
    }
    const top = mem.retrieve(q.question, topK, false, weights)
    const hit = top.some(c => candidates.has(c.id) && c.score > mem.config.retrievalFloor)
    if (hit)
      covered++
    const cat = q.category
    byCat[cat] = byCat[cat] ?? { cov: 0, tot: 0 }
    byCat[cat].tot++
    if (hit)
      byCat[cat].cov++
  }
  const byCategory: Record<number, number> = {}
  for (const k of Object.keys(byCat)) byCategory[Number(k)] = byCat[Number(k)].cov / byCat[Number(k)].tot
  return { overall: covered / conv.qa.length, covered, total: conv.qa.length, byCategory }
}

export interface SurvivalResult {
  /** Fraction of IMPORTANT memories (gold-evidence referenced) still retrievable. */
  important: number
  /** Fraction of TRIVIAL memories still retrievable. */
  trivial: number
  importantTotal: number
  trivialTotal: number
}

/**
 * Retention curves — the core, similarity-independent measure of what gating
 * actually does.
 *
 * For every memory we compute its retrieval strength at `now` and ask whether it
 * is still above the retrieval floor. Memories are split into IMPORTANT (their
 * id is referenced by some question's gold evidence) and TRIVIAL (everything
 * else). The falsifiable prediction:
 *
 *   - ON  : important survival stays high (durable facts, selective pruning);
 *           trivial survival collapses (pruned at consolidation).
 *   - OFF : important and trivial survival are identical (no selectivity) —
 *           both kept, both decaying at the same base rate.
 *
 * The gap (important − trivial) under ON should be large and positive; under OFF
 * it should be ~0. That gap IS the contribution.
 */
export function retentionCurve(mem: BioticMemory, conv: LocomoConversation, horizonDays: number): SurvivalResult {
  const now = conv.endTs + horizonDays * DAY
  mem.setNow(now)
  const g = mem.config.gating
  const f = mem.config.forgetting
  const floor = mem.config.retrievalFloor
  const important = new Set(conv.evidenceIds)
  const score = (createdAt: number, accessCount: number, baseStrength: number, durability: number, salience: number) =>
    retrievalStrength({ createdAt, accessCount, baseStrength, durability }, now, f, g, salience)

  let impTot = 0
  let impKeep = 0
  let triTot = 0
  let triKeep = 0

  for (const e of mem.episodes) {
    if (e.forgotten)
      continue
    const isImp = important.has(e.id)
    if (score(e.createdAt, e.accessCount, e.baseStrength, e.durability, e.encoding.salience) >= floor) {
      if (isImp)
        impKeep++
      else triKeep++
    }
    if (isImp)
      impTot++
    else triTot++
  }
  for (const fact of mem.facts) {
    const isImp = fact.derivedFrom.some(id => important.has(id))
    if (score(fact.createdAt, fact.accessCount, fact.baseStrength, fact.durability, fact.salience) >= floor) {
      if (isImp)
        impKeep++
      else triKeep++
    }
    if (isImp)
      impTot++
    else triTot++
  }

  return {
    important: impTot ? impKeep / impTot : 0,
    trivial: triTot ? triKeep / triTot : 0,
    importantTotal: impTot,
    trivialTotal: triTot,
  }
}
