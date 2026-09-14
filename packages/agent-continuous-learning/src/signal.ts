/**
 * Deriving an {@link InteractionSignal} (valence / arousal) from raw turn text.
 *
 * WHY THIS EXISTS
 * ---------------
 * `ContinuousLearning.ingestTurn(role, text, signal?)` treats `signal` as
 * optional, and `agent-capabilities` never passed one. The consequence was
 * severe and invisible: `applyInteraction` — the *only* path by which an actual
 * conversation shapes the persona — never executed. The persona drifted with
 * wall-clock time and nothing else, so "continuous learning" was a no-op.
 *
 * DESIGN CHOICE: deterministic lexicon by default
 * -----------------------------------------------
 * An LLM-based extractor is tempting, but for this project it is the wrong
 * default:
 *  - it costs an extra inference per turn (and the project already has a
 *    latency budget problem);
 *  - it is non-deterministic, so two runs of the same transcript produce
 *    different trajectories — fatal for a controlled study;
 *  - it makes the affect pipeline untestable offline.
 *
 * So the default is a transparent lexicon + punctuation heuristic that is
 * reproducible and inspectable. `createLlmSignalExtractor` remains available
 * for researchers who want a learned/contextual rater, and both implement the
 * same {@link SignalExtractor} interface so they are interchangeable.
 */

import type { InteractionSignal } from './persona'
import type { LearningLLM } from './types'

import { createLogger } from '@proj-aijade/agent-llm-client'

const logger = createLogger('agent-continuous-learning:signal')

/**
 * Anything that can turn (text, role) into an interaction signal.
 *
 * May be sync or async — `ingestTurn` awaits the result when needed.
 */
export interface SignalExtractor {
  (text: string, role: 'user' | 'assistant'): InteractionSignal | Promise<InteractionSignal>
}

export interface SignalExtractorOptions {
  /** Arousal assigned to a text with no affect cues at all. Default 0.25. */
  baselineArousal?: number
  /** Multiplier applied to the lexicon-derived valence. Default 1. */
  valenceScale?: number
  /** Maximum absolute valence. Default 1. */
  valenceCap?: number
  /** Extra languages / overrides merged into the lexicon. */
  positive?: readonly string[]
  negative?: readonly string[]
  intensifiers?: readonly string[]
}

// ---------------------------------------------------------------------------
// Lexicon
// ---------------------------------------------------------------------------
// Deliberately multi-lingual: the project ships zh-CN / zh-TW / en / ko locales,
// and a monolingual lexicon would silently score every non-English turn as
// neutral — which is exactly the failure mode that made the persona inert.

const DEFAULT_POSITIVE: readonly string[] = [
  // English
  'love',
  'great',
  'good',
  'nice',
  'happy',
  'glad',
  'thanks',
  'thank',
  'awesome',
  'amazing',
  'wonderful',
  'excellent',
  'perfect',
  'cool',
  'fun',
  'enjoy',
  'like',
  'helpful',
  'brilliant',
  'pleased',
  'delighted',
  'yay',
  'yes',
  'please',
  // 简体 / 繁体
  '喜欢',
  '爱',
  '开心',
  '高兴',
  '快乐',
  '谢谢',
  '感谢',
  '太好了',
  '棒',
  '厉害',
  '不错',
  '很好',
  '真好',
  '有意思',
  '有趣',
  '舒服',
  '安心',
  '温暖',
  '感动',
  '赞',
  '喜欢你',
  '陪我',
  '想你',
  // 한국어
  '좋아',
  '사랑',
  '고마워',
  '감사',
  '행복',
  '기뻐',
  '최고',
  '재미있',
]

const DEFAULT_NEGATIVE: readonly string[] = [
  // English
  'hate',
  'bad',
  'awful',
  'terrible',
  'horrible',
  'angry',
  'mad',
  'sad',
  'upset',
  'annoying',
  'annoyed',
  'stupid',
  'dumb',
  'useless',
  'wrong',
  'broken',
  'failed',
  'fail',
  'error',
  'problem',
  'hurt',
  'pain',
  'tired',
  'boring',
  'disappointed',
  'frustrated',
  'no',
  'stop',
  'shut',
  // 简体 / 繁体
  '讨厌',
  '恨',
  '生气',
  '难过',
  '伤心',
  '烦',
  '无聊',
  '糟糕',
  '差',
  '烂',
  '失败',
  '错误',
  '问题',
  '不行',
  '不要',
  '住口',
  '闭嘴',
  '滚',
  '笨',
  '蠢',
  '失望',
  '沮丧',
  '累',
  '痛',
  '害怕',
  '担心',
  // 한국어
  '싫어',
  '미워',
  '화나',
  '슬퍼',
  '짜증',
  '최악',
  '실패',
  '문제',
  '그만',
]

const DEFAULT_INTENSIFIERS: readonly string[] = [
  'very',
  'really',
  'so',
  'extremely',
  'absolutely',
  'super',
  'totally',
  '非常',
  '特别',
  '超级',
  '真的',
  '太',
  '十分',
  '极其',
  '好',
  '너무',
  '정말',
  '아주',
]

/** Emoji / kaomoji affect cues (substring match, not codepoint-perfect). */
const POSITIVE_EMOJI: readonly string[] = [
  '😊',
  '😄',
  '😍',
  '🥰',
  '😘',
  '❤',
  '💕',
  '💖',
  '👍',
  '🎉',
  '✨',
  '🙏',
  '🤩',
  '😌',
]
const NEGATIVE_EMOJI: readonly string[] = [
  '😠',
  '😡',
  '😢',
  '😭',
  '😞',
  '💔',
  '👎',
  '😣',
  '😤',
  '🙄',
  '😨',
  '😰',
]

// ---------------------------------------------------------------------------
// Lexicon matching
// ---------------------------------------------------------------------------

/**
 * Count lexicon hits.
 *
 * ASCII entries match on word boundaries (so "no" does not fire inside
 * "notebook"); CJK/Hangul entries match as substrings because those scripts
 * have no whitespace word separation.
 */
function countHits(lower: string, words: readonly string[]): number {
  let n = 0
  for (const w of words) {
    if (!w)
      continue
    if (/^[a-z]+$/.test(w)) {
      const m = lower.match(new RegExp(`\\b${w}\\b`, 'g'))
      if (m)
        n += m.length
    }
    else {
      let idx = lower.indexOf(w)
      while (idx !== -1) {
        n++
        idx = lower.indexOf(w, idx + w.length)
      }
    }
  }
  return n
}

function countEmoji(text: string, emoji: readonly string[]): number {
  let n = 0
  for (const e of emoji) {
    let idx = text.indexOf(e)
    while (idx !== -1) {
      n++
      idx = text.indexOf(e, idx + e.length)
    }
  }
  return n
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}

// ---------------------------------------------------------------------------
// Deterministic extractor
// ---------------------------------------------------------------------------

/**
 * Score a turn with a transparent lexicon + punctuation heuristic.
 *
 * Fully deterministic: the same text always yields the same signal, so
 * recorded trajectories are reproducible and the function is unit-testable
 * without a model.
 */
export function extractSignal(text: string, options: SignalExtractorOptions = {}): InteractionSignal {
  const opts = {
    baselineArousal: options.baselineArousal ?? 0.25,
    valenceScale: options.valenceScale ?? 1,
    valenceCap: options.valenceCap ?? 1,
    positive: options.positive?.length ? options.positive : DEFAULT_POSITIVE,
    negative: options.negative?.length ? options.negative : DEFAULT_NEGATIVE,
    intensifiers: options.intensifiers?.length ? options.intensifiers : DEFAULT_INTENSIFIERS,
  }

  const raw = (text ?? '').trim()
  if (!raw)
    return { valence: 0, arousal: 0.05, event: 'empty' }

  const lower = raw.toLowerCase()

  const pos = countHits(lower, opts.positive) + countEmoji(raw, POSITIVE_EMOJI)
  const neg = countHits(lower, opts.negative) + countEmoji(raw, NEGATIVE_EMOJI)

  // Intensifiers amplify whatever polarity is present rather than adding one.
  const intense = countHits(lower, opts.intensifiers)
  const intensity = 1 + Math.min(0.6, intense * 0.2)

  // Polarity: normalised difference, softened by a prior of 2 so that a single
  // stray word does not slam valence to the rail.
  const total = pos + neg
  const valence = total === 0
    ? 0
    : clamp(((pos - neg) / Math.max(2, total)) * 1.5 * intensity * opts.valenceScale, -opts.valenceCap, opts.valenceCap)

  // Arousal: punctuation and typographic energy, not sentiment.
  const exclamations = (raw.match(/[!！]/g) ?? []).length
  const questions = (raw.match(/[?？]/g) ?? []).length
  const letters = raw.replace(/[^a-z]/gi, '')
  const capsRatio = letters.length >= 4
    ? (raw.match(/\b[A-Z]{2,}\b/g) ?? []).length / Math.max(1, raw.split(/\s+/).length)
    : 0
  const ellipsis = (raw.match(/\.\.\.|…/g) ?? []).length > 0 ? -0.05 : 0

  let arousal = opts.baselineArousal
  arousal += Math.min(0.3, exclamations * 0.1)
  arousal += Math.min(0.1, questions * 0.05)
  arousal += Math.min(0.25, capsRatio * 0.5)
  arousal += Math.min(0.2, (pos + neg) * 0.05)
  arousal += ellipsis
  // Very long, dense turns read as more invested than one-word replies.
  arousal += Math.min(0.1, raw.length / 2000)
  arousal = clamp(arousal, 0, 1)

  const event = total === 0 ? 'neutral' : pos >= neg ? 'positive' : 'negative'
  return { valence, arousal, event }
}

/** Create a configurable lexicon extractor bound to fixed options. */
export function createLexiconSignalExtractor(options: SignalExtractorOptions = {}): SignalExtractor {
  return (text: string) => extractSignal(text, options)
}

// ---------------------------------------------------------------------------
// LLM extractor (opt-in)
// ---------------------------------------------------------------------------

const EXTRACT_SYSTEM = `You rate a single chat turn's affect.
Reply with JSON only: {"valence": <number -1..1>, "arousal": <number 0..1>}
valence: -1 very negative, 0 neutral, +1 very positive.
arousal: 0 calm/flat, 1 excited/intense.
No explanation.`

/**
 * Rate a turn with the LLM.
 *
 * Opt-in only: adds latency and is non-deterministic. Use it when the research
 * question needs contextual understanding (sarcasm, implicit affect) and the
 * run does not need to be bit-reproducible.
 *
 * Falls back to the lexicon score when the model is unreachable or returns
 * malformed output, so a flaky endpoint degrades gracefully instead of
 * silently zeroing the signal (which is what broke the pipeline before).
 */
export function createLlmSignalExtractor(llm: LearningLLM, options: SignalExtractorOptions = {}): SignalExtractor {
  const fallback = createLexiconSignalExtractor(options)
  return async (text: string, role: 'user' | 'assistant') => {
    if (!text?.trim())
      return { valence: 0, arousal: 0.05, event: 'empty' }
    try {
      const result = await llm.jsonComplete<{ valence?: number, arousal?: number }>(
        [
          { role: 'system', content: EXTRACT_SYSTEM },
          { role: 'user', content: `[${role}] ${text.slice(0, 2000)}` },
        ],
        { temperature: 0 },
      )
      const valence = Number(result?.valence)
      const arousal = Number(result?.arousal)
      if (!Number.isFinite(valence) || !Number.isFinite(arousal))
        throw new TypeError('non-numeric affect scores')
      return {
        valence: clamp(valence, -1, 1),
        arousal: clamp(arousal, 0, 1),
        event: valence >= 0 ? 'positive' : 'negative',
      }
    }
    catch (err) {
      logger.warn(`LLM affect extraction failed, falling back to lexicon: ${(err as Error).message}`)
      return fallback(text, role)
    }
  }
}
