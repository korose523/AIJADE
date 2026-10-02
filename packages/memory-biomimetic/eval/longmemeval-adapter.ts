/**
 * LongMemEval → 记忆构建器的适配层。
 *
 * ── 目标 ──────────────────────────────────────────────────────────────────
 * 把 LongMemEval 的 item 结构映射为 `src/locomo.ts` 的 `LocomoConversation`，
 * 从而**复用 `buildMemory()` / `BioticMemory.retrieve()` 这条完全相同的打分代码路径**。
 *
 * 这一点是刻意的：跨语料复现只有在"两次测量跑的是同一段打分代码"时才配叫复现。
 * 若为本语料另写一套检索，LoCoMo 的 0.0906 与 LongMemEval 的数字就不可比，
 * 论文里那句"跨语料得到同向结果"会变成没有承载的结论。
 *
 * ── 实测 schema（非假设）───────────────────────────────────────────────────
 * 对 `longmemeval_s_cleaned.json`（500 项，sha256 d6f21ea9…）逐字段核对：
 *
 *   question_id           string
 *   question_type         string   6 种取值，见 QUESTION_TYPE_CODES
 *   question              string
 *   question_date         string   "2023/05/30 (Tue) 23:40"
 *   answer                string   （500 项中 `"answer": null` 计数为 0）
 *   answer_session_ids    string[] 金标准证据会话 id
 *   haystack_dates        string[] 与 haystack_session_ids 平行
 *   haystack_session_ids  string[]
 *   haystack_sessions     { role: 'user'|'assistant', content: string }[][]  ← 会话 × 轮次
 *
 * 顶层键**恰好**是这 9 个，没有多余字段。
 *
 * ── 映射中三处必须声明的设计决定 ──────────────────────────────────────────
 *
 * ① 粒度：一条 episode = 一个 haystack session（不是一轮 turn）。
 *    理由：LongMemEval 官方指标就是 **session 级** —— 证据由 `answer_session_ids`
 *    给出，官方 recall@k / NDCG@k 判的是"证据会话是否进 top-k"。若按 turn 编码，
 *    一个多轮会话会占据多个 top-K 名额，**系统性抬高 recall@K**，且这个抬高与
 *    LongMemEval 官方口径无关。按 session 编码则 episode id === 会话 id，
 *    命中判定与官方口径一致。
 *    代价（明确承认）：与 LoCoMo 侧按 turn（`dia_id`）编码的粒度不同，两侧
 *    recall@K 的**绝对值**不可直接相减比较；可比较的是三臂之间的**相对顺序**。
 *    J5 的主张是"recency 抑制 ≫ 现状"这个**顺序**，所以这是可接受的代价。
 *
 * ② 显著性：证据会话 salience = 0.9，其余 = 0.25。
 *    与 `src/locomo.ts::parseConversation` **完全一致**的 oracle 显著性约定
 *    （LoCoMo 里 `evidenceIds.has(dia_id)` 的轮次取高显著性）。两侧都不预测显著性，
 *    都用金标准标注 —— 这是"同一套输入假设"的一部分。
 *
 * ③ now = `question_date`。
 *    `BioticMemory(config, endTs)` 的 `endTs` 是"当下"，遗忘与 recency 都相对它计算。
 *    LongMemEval 的语义正是"在 question_date 这一刻提问"，故取该时刻。
 *
 * ── abstention（拒答）能力项 ──────────────────────────────────────────────
 * 论文把 abstention 列为第五项能力（正确行为是**不回答**）。但**官方 cleaned 版
 * 语料里不含该题型**：500 项的 `question_type` 分布实测为
 *   multi-session 133 / temporal-reasoning 133 / knowledge-update 78 /
 *   single-session-user 70 / single-session-assistant 56 / single-session-preference 30
 * （合计 500，无 abstention），且全文 `"answer": null` 计数为 0
 * （唯一的 "abstention" 字样出现在某条会话正文里，不是题型）。
 *
 * 因此本适配层**不需要**排除任何题目 —— 不是我们选择忽略 abstention，而是
 * 官方 cleaned 变体已经把它移除了。若将来改用含 abstention 的变体，必须在此处
 * 显式分支：recall@K 对拒答题**无定义**（没有可召回的证据），把它们计入分母
 * 会把所有臂的 recall 一起拉低，属于口径错误。
 */
import type { Episode, LocomoConversation, LocomoQuestion } from '../src/index'

import { tokenize } from '../src/index'

/** 单条 LongMemEval 记录（字段名照抄上游，不做改写）。 */
export interface LongMemEvalItem {
  question_id: string
  question_type: string
  question: string
  question_date: string
  answer: string | null
  answer_session_ids: string[]
  haystack_dates: string[]
  haystack_session_ids: string[]
  haystack_sessions: { role: string, content: string }[][]
}

/**
 * `question_type` → 整数类别码。
 *
 * `LocomoQuestion.category` 是 number，且 `evidenceRecall()` 的 `byCategory`
 * 以它为键。这里用稳定编码，并在产物里同时输出回名字，避免读者面对裸数字。
 */
export const QUESTION_TYPE_CODES: Record<string, number> = {
  'single-session-user': 1,
  'single-session-assistant': 2,
  'single-session-preference': 3,
  'multi-session': 4,
  'knowledge-update': 5,
  'temporal-reasoning': 6,
}

/** 类别码 → 名字（产物可读性）。 */
export const QUESTION_TYPE_NAMES: Record<number, string> = Object.fromEntries(
  Object.entries(QUESTION_TYPE_CODES).map(([name, code]) => [code, name]),
)

/**
 * 论文的能力项分组：三个 single-session 类型合并为 information extraction。
 * 这里只做**分组标签**，不改变任何打分行为。
 */
export const ABILITY_OF_TYPE: Record<string, string> = {
  'single-session-user': 'information-extraction',
  'single-session-assistant': 'information-extraction',
  'single-session-preference': 'information-extraction',
  'multi-session': 'multi-session-reasoning',
  'knowledge-update': 'knowledge-update',
  'temporal-reasoning': 'temporal-reasoning',
}

/**
 * 解析 "2023/05/20 (Sat) 02:21" → epoch ms（UTC）。
 * 解析失败返回 null，由调用方决定兜底（不允许静默编造一个时间）。
 */
export function parseLongMemEvalDate(s: string): number | null {
  const m = s.match(/(\d{4})\/(\d{2})\/(\d{2})\s*\(\s*[A-Z]{3}\s*\)\s*(\d{1,2}):(\d{2})/i)
  if (!m)
    return null
  const y = Number(m[1])
  const mo = Number(m[2]) - 1
  const d = Number(m[3])
  const hh = Number(m[4])
  const mm = Number(m[5])
  const ts = Date.UTC(y, mo, d, hh, mm, 0)
  return Number.isFinite(ts) ? ts : null
}

/** 一个会话序列化为 episode 文本。`role` 前缀保留 —— user/assistant 之别是题型语义的一部分。 */
export function sessionToContent(turns: { role: string, content: string }[]): string {
  return turns.map(t => `${t.role}: ${t.content ?? ''}`).join('\n')
}

export interface ParseDiagnostics {
  /** `answer_session_ids` 中**不**在 `haystack_session_ids` 里的 id（应恒为空，非空即语料异常）。 */
  danglingAnswerSessionIds: string[]
  /** 未能解析出时间的会话数（用确定性偏移兜底，并在产物里报告）。 */
  unparsedSessionDates: number
  /** `question_date` 是否无法解析（无法解析则 endTs 取最晚会话时间 + 1 天）。 */
  questionDateUnparsed: boolean
}

export interface ParsedLongMemEvalItem {
  conv: LocomoConversation
  item: LongMemEvalItem
  diagnostics: ParseDiagnostics
}

/**
 * 把一条 LongMemEval 记录映射为 `LocomoConversation`，供 `buildMemory()` 直接消费。
 *
 * 不做任何筛选/重排 —— 500 项全部可解析；确实无解的情况由
 * `parseLongMemEval()` 汇总后**如实报告**，而不是静默丢题。
 */
export function parseLongMemEvalItem(item: LongMemEvalItem): ParsedLongMemEvalItem {
  const sessionIds = item.haystack_session_ids ?? []
  const sessions = item.haystack_sessions ?? []
  const dates = item.haystack_dates ?? []

  if (sessionIds.length !== sessions.length || (dates.length && dates.length !== sessions.length)) {
    throw new Error(
      `LongMemEval item ${item.question_id} 结构不一致：`
      + `haystack_session_ids=${sessionIds.length} haystack_sessions=${sessions.length} haystack_dates=${dates.length}`,
    )
  }

  const answerIds = new Set<string>(item.answer_session_ids ?? [])
  const danglingAnswerSessionIds = [...answerIds].filter(id => !sessionIds.includes(id))

  // 会话时间：解析失败时用**确定性**偏移（按序 +1 小时），并把失败计数上报。
  // 不用随机、不用 Math.random —— 时间参与了 recency 项，必须可复现。
  let unparsedSessionDates = 0
  const sessionTs: number[] = []
  let maxSessionTs = 0
  for (let i = 0; i < sessions.length; i++) {
    const parsed = dates[i] ? parseLongMemEvalDate(dates[i]) : null
    if (parsed === null) {
      unparsedSessionDates++
      sessionTs.push(Date.UTC(2023, 0, 1) + i * 3_600_000)
    }
    else {
      sessionTs.push(parsed)
      if (parsed > maxSessionTs)
        maxSessionTs = parsed
    }
  }

  const qTs = item.question_date ? parseLongMemEvalDate(item.question_date) : null
  const questionDateUnparsed = qTs === null
  const endTs = qTs ?? (maxSessionTs + 86_400_000)

  const episodes: Episode[] = sessions.map((turns, i) => {
    const content = sessionToContent(turns)
    const salient = answerIds.has(sessionIds[i])
    const encoding = salient
      ? { salience: 0.9, socialSalience: 0.7, novelty: 0.5, affect: { valence: 0.85, arousal: 0.6, dominance: 0.7 } }
      : { salience: 0.25, socialSalience: 0.15, novelty: 0.5, affect: { valence: 0.5, arousal: 0.4, dominance: 0.5 } }
    return {
      id: sessionIds[i],
      content,
      createdAt: sessionTs[i],
      lastAccessedAt: sessionTs[i],
      accessCount: 0,
      baseStrength: 1,
      durability: 1,
      encoding,
      context: {
        sessionId: sessionIds[i],
        interlocutor: 'user',
        task: undefined,
        tags: tokenize(content),
      },
      consolidated: false,
      memoryType: 'episodic',
      status: 'active',
      validTime: {},
    }
  })

  const qa: LocomoQuestion[] = [{
    question: item.question,
    answer: item.answer ?? '',
    evidence: [...answerIds],
    category: QUESTION_TYPE_CODES[item.question_type] ?? 0,
  }]

  const conv: LocomoConversation = {
    sampleId: item.question_id,
    episodes,
    qa,
    evidenceIds: answerIds,
    endTs,
  }

  return {
    conv,
    item,
    diagnostics: { danglingAnswerSessionIds, unparsedSessionDates, questionDateUnparsed },
  }
}

export interface ParseSummary {
  items: ParsedLongMemEvalItem[]
  /** 题型 → 题数（实测分布，用于产物与论文核对）。 */
  typeCounts: Record<string, number>
  /** 能力项 → 题数。 */
  abilityCounts: Record<string, number>
  /** 存在悬空证据 id 的题目数（应为 0）。 */
  itemsWithDanglingEvidence: number
  /** 存在会话时间解析失败的题目数（应为 0）。 */
  itemsWithUnparsedDates: number
  /** `question_date` 解析失败的题目数（应为 0）。 */
  itemsWithUnparsedQuestionDate: number
  /** `question_type` 不在 QUESTION_TYPE_CODES 中的取值（应为空）。 */
  unknownTypes: string[]
}

/** 解析整份语料，并汇总**所有**异常计数 —— 异常要被看见，不能被吞掉。 */
export function parseLongMemEval(data: LongMemEvalItem[]): ParseSummary {
  const items = data.map(parseLongMemEvalItem)
  const typeCounts: Record<string, number> = {}
  const abilityCounts: Record<string, number> = {}
  const unknownTypes = new Set<string>()
  let itemsWithDanglingEvidence = 0
  let itemsWithUnparsedDates = 0
  let itemsWithUnparsedQuestionDate = 0

  for (const { item, diagnostics } of items) {
    typeCounts[item.question_type] = (typeCounts[item.question_type] ?? 0) + 1
    const ability = ABILITY_OF_TYPE[item.question_type] ?? 'unknown'
    abilityCounts[ability] = (abilityCounts[ability] ?? 0) + 1
    if (!(item.question_type in QUESTION_TYPE_CODES))
      unknownTypes.add(item.question_type)
    if (diagnostics.danglingAnswerSessionIds.length)
      itemsWithDanglingEvidence++
    if (diagnostics.unparsedSessionDates)
      itemsWithUnparsedDates++
    if (diagnostics.questionDateUnparsed)
      itemsWithUnparsedQuestionDate++
  }

  return {
    items,
    typeCounts,
    abilityCounts,
    itemsWithDanglingEvidence,
    itemsWithUnparsedDates,
    itemsWithUnparsedQuestionDate,
    unknownTypes: [...unknownTypes],
  }
}

/**
 * 按固定种子做无放回抽样。
 *
 * 为什么需要：`longmemeval_s_cleaned.json` 全量为 500 题 × 各自独立 haystack，
 * 逐题建记忆的实测耗时可能使全量运行在单次会话内不可完成。抽样**必须**是
 * 确定性且可声明的：种子写进产物，谁都能复算同一个子集。绝不用"随便取前 N 题"
 * —— 上游文件未必按题型排序，取前 N 会引入未知的题型偏倚。
 */
export function sampleItems(items: ParsedLongMemEvalItem[], n: number, seed = 0): ParsedLongMemEvalItem[] {
  if (n >= items.length)
    return items
  let a = seed >>> 0
  const rnd = (): number => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4_294_967_296
  }
  const pool = items.slice()
  const out: ParsedLongMemEvalItem[] = []
  for (let i = 0; i < n; i++) {
    const j = Math.floor(rnd() * pool.length)
    out.push(pool[j])
    pool.splice(j, 1)
  }
  return out
}
