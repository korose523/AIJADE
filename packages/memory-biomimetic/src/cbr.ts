import { tokenF1 } from './sim'

/**
 * v7 §12 — CBR: 因果具身回放 (Causal Embodied Replay)，以及 §25 #13 `ReplayBundle` 契约。
 *
 * 存在的理由（§12 原文动机）：默认是「只做跨样本相关分析」，而相关不能支撑因果主张。
 * CBR 的做法是把一次关键交互**整体**存成可回放束，再让**同一个事件束**在干预
 * （gate=1）与对照（gate=0）下各跑一遍，于是
 *
 *     ITE = Y(do(gate=1)) − Y(do(gate=0))
 *
 * 是**配对**在同一个 bundle 上的差，而不是两个不同样本群的均值差。这是本模块唯一
 * 的科学主张，也是它的可证伪点：若干预与对照的配对差之 95% 置信区间跨 0，
 * 则「门控有因果效应」的主张被证伪。
 *
 * 三类回放（§12）：
 *   1. 观测回放 —— 原样复现原决策（`ReplayLog` 不可变存储 + `validateReplayBundle`）；
 *   2. 干预回放 —— 替换状态 / 记忆 / 模型（`intervene`，纯函数）；
 *   3. 具身回放 —— 重新生成语音、表情、姿态并比较一致性（`replayConsistency`）。
 *
 * 纯函数、无外部依赖（仅复用 `./sim` 的 tokenF1），与 HAC/CDI 同为 opt-in 研究内核模块，
 * 不介入记忆 durability/salience（H2c 兼容护盾）。
 */

/** v7 §25 #13 — 回放束契约版本。 */
export const REPLAY_BUNDLE_SCHEMA = 'aijade.replay_bundle@1'

/** v7 §12 — CBR 研究内核的产品接入配置。独立解耦（P8/§43），opt-in。 */
export interface CbrConfig {
  /** 仅当显式 true 才构造回放日志（否则 store 不持有任何回放束）。 */
  enabled: boolean
}

/** 具身指令（后端无关）。 */
interface SemanticMotion {
  /** 相对回放起点的毫秒偏移。 */
  t: number
  /** 具身指令名（如 'nod' / 'smile' / 'gaze_down'）。 */
  motion: string
  intensity?: number
}

export interface SpeechEvent {
  t: number
  text: string
}

/**
 * v7 §12 / §25 #13 — 完整研究回放束（13 字段）。
 *
 * `state_before` / `state_after` 是**同名**数值向量（HAC 的 7 维 z_t、CDI 的身份层
 * 或其它内生状态皆可），键集合必须一致，否则前后不可比、因果估计会被结构性问题污染。
 */
export interface ReplayBundle {
  schema: typeof REPLAY_BUNDLE_SCHEMA
  bundleId: string
  event_ids: string[]
  state_before: Record<string, number>
  memory_ids_retrieved: string[]
  prompt_digest: string
  model_manifest: { model: string, digest?: string, sampling: Record<string, unknown> }
  action_plan: string[]
  tool_results: Record<string, unknown>[]
  speech_timeline: SpeechEvent[]
  semantic_motion: SemanticMotion[]
  user_feedback: { valence: number, signal: 'F' | 'U' | 'none' }
  state_after: Record<string, number>
}

/** 一次回放的观测结果 Y（越高越好，由调用方定义：成功率、答案 F1、用户评分…）。 */
export interface ReplayRun {
  bundle: ReplayBundle
  outcome: number
}

/** §12 干预回放：可替换状态 / 记忆 / 模型三者之一或全部。 */
export interface ReplayIntervention {
  state_before?: Record<string, number>
  memory_ids_retrieved?: string[]
  model_manifest?: ReplayBundle['model_manifest']
}

/** §12 具身回放一致性：语音 / 姿态 / 总体 ∈ [0,1]。 */
export interface ReplayConsistency {
  speech: number
  motion: number
  overall: number
}

/** 配对差：同一 bundle 在 treated(gate=1) 与 control(gate=0) 下的结果。 */
export interface ItePair {
  bundleId: string
  treated: number
  control: number
}

/**
 * ITE 因果估计（配对差的均值 + 正态近似 95% 置信区间）。
 *
 * `significant` 为 true 当且仅当 CI 不含 0 —— 这是本模块的可证伪输出：
 * CI 跨 0 即「无因果效应」，不得解读为「有趋势」。
 */
export interface IteEstimate {
  n: number
  mean: number
  sd: number
  se: number
  ci95: [number, number]
  significant: boolean
  perPair: ItePair[]
}

/** 配对结果：成功配对的差，以及未能配对的 bundleId（用于度量配对率，而非静默丢弃）。 */
export interface PairingResult {
  pairs: ItePair[]
  unmatched: string[]
  pairingRate: number
}

/** 正态近似 95% 双侧临界值。 */
const Z_95 = 1.96

function mean(a: number[]): number {
  return a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0
}

/** 样本标准差（n−1）。 */
function sampleSd(a: number[]): number {
  if (a.length < 2)
    return 0
  const m = mean(a)
  return Math.sqrt(a.reduce((s, x) => s + (x - m) ** 2, 0) / (a.length - 1))
}

function keysOf(o: Record<string, number>): string[] {
  return Object.keys(o).sort()
}

/**
 * 校验回放束（§12 可回放性的硬不变量）。纯函数，永不抛错。
 *
 * 关键约束：`state_before` 与 `state_after` 键集合必须一致 —— 前后状态不同名就意味着
 * 状态变化无法归因，ITE 会被结构性差异污染。
 */
export function validateReplayBundle(b: ReplayBundle): { ok: true } | { ok: false, reason: string } {
  if (b.schema !== REPLAY_BUNDLE_SCHEMA)
    return { ok: false, reason: `ReplayBundle schema must be "${REPLAY_BUNDLE_SCHEMA}"` }
  if (!b.bundleId)
    return { ok: false, reason: 'ReplayBundle requires a bundleId' }
  if (b.event_ids.length === 0)
    return { ok: false, reason: 'ReplayBundle requires ≥1 event_id (a replay must replay events)' }
  if (!b.prompt_digest)
    return { ok: false, reason: 'ReplayBundle requires a prompt_digest (replay must be content-addressed)' }
  if (!b.model_manifest?.model)
    return { ok: false, reason: 'ReplayBundle requires model_manifest.model (replay must name the model)' }
  const before = keysOf(b.state_before).join(',')
  const after = keysOf(b.state_after).join(',')
  if (before !== after)
    return { ok: false, reason: 'state_before and state_after must share the same key set (comparability)' }
  if (!Number.isFinite(b.user_feedback?.valence) || b.user_feedback.valence < -1 || b.user_feedback.valence > 1)
    return { ok: false, reason: 'user_feedback.valence must be a finite number in [-1,1]' }
  return { ok: true }
}

/**
 * §12 干预回放：替换状态 / 记忆 / 模型，产出**新的** bundle。
 * 纯函数 —— 绝不改动入参。`bundleId` 与 `event_ids` 保持不变，使干预前后仍可配对。
 */
export function intervene(b: ReplayBundle, patch: ReplayIntervention): ReplayBundle {
  return {
    ...b,
    state_before: patch.state_before ?? { ...b.state_before },
    memory_ids_retrieved: patch.memory_ids_retrieved ?? [...b.memory_ids_retrieved],
    model_manifest: patch.model_manifest ?? { ...b.model_manifest, sampling: { ...b.model_manifest.sampling } },
  }
}

function motionSet(b: ReplayBundle): Set<string> {
  return new Set(b.semantic_motion.map(m => m.motion))
}

/**
 * §12 具身回放一致性：重新生成后语音与姿态的吻合度。
 * 语音用 token-F1（复用 `./sim`），姿态用动作集合的 Jaccard 指数。确定性、对称。
 */
export function replayConsistency(a: ReplayBundle, b: ReplayBundle): ReplayConsistency {
  const speechA = a.speech_timeline.map(s => s.text).join(' ')
  const speechB = b.speech_timeline.map(s => s.text).join(' ')
  const speech = tokenF1(speechA, speechB)

  const ma = motionSet(a)
  const mb = motionSet(b)
  let inter = 0
  for (const m of ma) {
    if (mb.has(m))
      inter++
  }
  const union = ma.size + mb.size - inter
  const motion = union === 0 ? 1 : inter / union

  return { speech, motion, overall: (speech + motion) / 2 }
}

/**
 * 把 treated(gate=1) 与 control(gate=0) 两组回放**按同一事件束**配对。
 *
 * 只有 `bundleId` 相同**且** `event_ids` 完全一致才算同一事件束 —— 这正是 §12
 * 「同一事件束在门控开启与关闭下运行，避免只做跨样本相关分析」的可执行版本。
 * 配不上的进 `unmatched`，绝不静默丢弃（配不上本身是要被度量的信号）。
 */
export function pairReplays(treated: ReplayRun[], control: ReplayRun[]): PairingResult {
  const ctrl = new Map<string, ReplayRun>()
  for (const c of control) ctrl.set(c.bundle.bundleId, c)

  const pairs: ItePair[] = []
  const unmatched: string[] = []
  for (const t of treated) {
    const c = ctrl.get(t.bundle.bundleId)
    const sameEvents = c && c.bundle.event_ids.join(' ') === t.bundle.event_ids.join(' ')
    if (!c || !sameEvents) {
      unmatched.push(t.bundle.bundleId)
      continue
    }
    pairs.push({ bundleId: t.bundle.bundleId, treated: t.outcome, control: c.outcome })
  }
  return { pairs, unmatched, pairingRate: treated.length ? pairs.length / treated.length : 0 }
}

/**
 * ITE 因果估计：配对差的均值、样本标准差、标准误与正态近似 95% CI。
 *
 *     ITE_i = Y_i(do(gate=1)) − Y_i(do(gate=0))
 *
 * `significant` = CI 不含 0。空输入返回全零且不显著（不抛错，便于调用方统计）。
 */
export function estimateITE(pairs: ItePair[]): IteEstimate {
  const diffs = pairs.map(p => p.treated - p.control)
  const m = mean(diffs)
  const sd = sampleSd(diffs)
  const se = pairs.length ? sd / Math.sqrt(pairs.length) : 0
  const half = Z_95 * se
  const lo = m - half
  const hi = m + half
  return {
    n: pairs.length,
    mean: m,
    sd,
    se,
    ci95: [lo, hi],
    significant: lo > 0 || hi < 0,
    perPair: pairs,
  }
}

/**
 * 不可变回放日志：bundle 一旦入库不可覆盖（重复 `bundleId` 被拒），
 * 与研究完整性一致 —— 回放束是证据，不是缓存。
 */
export class ReplayLog {
  private bundles = new Map<string, ReplayBundle>()

  /** 写入一条回放束；拒绝非法束与重复 bundleId（返回原因，不抛错）。 */
  add(b: ReplayBundle): { ok: true } | { ok: false, reason: string } {
    const v = validateReplayBundle(b)
    if (!v.ok)
      return v
    if (this.bundles.has(b.bundleId))
      return { ok: false, reason: `ReplayBundle "${b.bundleId}" already logged (replay log is append-only)` }
    this.bundles.set(b.bundleId, b)
    return { ok: true }
  }

  get(bundleId: string): ReplayBundle | undefined {
    return this.bundles.get(bundleId)
  }

  all(): ReplayBundle[] {
    return [...this.bundles.values()]
  }

  get size(): number {
    return this.bundles.size
  }
}
