/**
 * motion-fusion — KIMODO × HY-Motion persona-driven body-motion fusion.
 *
 * Both offline pipelines (NVIDIA KIMODO procedural gestures, Tencent HY-Motion
 * learned expressive full-body motion) emit the same neutral VRM gesture-clip
 * JSON contract (see `kimodo-gestures.ts` / `libs/kimodo/README.md`). This
 * module turns that flat clip bag into a **persona-aware motion library** so the
 * avatar's *autonomous* body language becomes a "super-personified" expression
 * of its internal state — not a random gesture pool.
 *
 * The fusion has three layers, all driven by `PersonaSignal`:
 *  1. intent weighting   — persona → which semantic motions fit right now
 *  2. source selection   — expressive persona → HY-Motion (learned, natural);
 *                           crisp/cautious persona → KIMODO (controllable)
 *  3. clip blending      — `blend()` literally slerps KIMODO + HY-Motion bone
 *                           tracks into one hybrid clip (true synthesis fusion)
 *
 * Everything here is pure / framework-free (only `three` for the clip type) so
 * it can be unit-tested and reused by any VRM runtime.
 */

import type { AnimationClip } from 'three'

import type { PersonaSignal } from './emotion/avatar-expression'

import { Quaternion, QuaternionKeyframeTrack, AnimationClip as ThreeAnimationClip } from 'three'

/** Where a fused motion clip originated. */
export type MotionSource = 'kimodo' | 'hy-motion'

/**
 * Semantic motion intents. These are the vocabulary the persona engine speaks;
 * each generated clip is tagged with one or more intents so the selector can
 * match them against the live persona.
 */
export type MotionIntent
  = | 'open' // welcoming, arms open, leaning in
    | 'playful' // bouncy, wavy, light
    | 'restless' // fidgety, shifting weight
    | 'wistful' // slow, looking away, gentle
    | 'confident' // upright, assertive
    | 'tender' // soft, gentle reach
    | 'thoughtful' // pondering, chin-touch
    | 'alert' // quick, pointed
    | 'bashful' // shy, averted, smaller
    | 'agreeable' // nodding, affirmative

export interface MotionEntry {
  name: string
  source: MotionSource
  intents: MotionIntent[]
  clip: AnimationClip
  /** Relative weight when its intents are active (default 1). */
  baseWeight?: number
}

export interface MotionIntentWeights {
  /** intent → activation 0..1. Missing intents are treated as 0. */
  weights: Partial<Record<MotionIntent, number>>
  /** Overall activation energy 0..1 (drives frequency / amplitude). */
  energy: number
  /** Source preference 0 = prefer KIMODO (crisp), 1 = prefer HY-Motion (expressive). */
  sourcePreference: number
}

/**
 * Map a persona snapshot onto motion-intent activation. Pure + unit-tested.
 *
 * This is the body-language counterpart of `personaToIdleBias` (which drives
 * face/gaze/blink): both read the same `PersonaSignal`, so the avatar's whole
 * autonomous self reads coherent — warm+trusting+oxytocin → open/agreeable/
 * tender body language; cortisol/adrenaline → restless/alert; longing → wistful.
 */
export function personaToMotionIntent(p: PersonaSignal): MotionIntentWeights {
  const { warmth, trust, familiarity, longing } = p.intimacy
  const { dopamine, serotonin, cortisol, oxytocin, adrenaline } = p.endocrine
  const { playfulness, spontaneity } = p.vector

  const set = (w: Partial<Record<MotionIntent, number>>, k: MotionIntent, v: number) => {
    w[k] = Math.max(0, Math.min(1, v))
  }

  const friendly = (warmth + trust + familiarity + oxytocin) / 4
  const expressive = (dopamine + oxytocin + playfulness) / 3
  const fidgety = (cortisol + adrenaline) / 2
  const calm = serotonin

  const weights: Partial<Record<MotionIntent, number>> = {}
  set(weights, 'open', friendly)
  set(weights, 'tender', oxytocin * 0.7 + warmth * 0.3)
  set(weights, 'playful', Math.max(playfulness, spontaneity, dopamine * 0.6))
  set(weights, 'confident', Math.max(0, (familiarity + trust) / 2 - cortisol * 0.5))
  set(weights, 'agreeable', (trust + familiarity) / 2)
  set(weights, 'thoughtful', calm * 0.5 + (1 - fidgety) * 0.3)
  set(weights, 'wistful', longing)
  set(weights, 'bashful', (1 - familiarity) * 0.6 + (1 - trust) * 0.4)
  set(weights, 'restless', fidgety)
  set(weights, 'alert', adrenaline)

  const energy = Math.max(0, Math.min(1, dopamine * 0.4 + adrenaline * 0.3 + playfulness * 0.3))
  // Expressive / longing persona → prefer HY-Motion's learned natural motion;
  // cautious / stressed persona → prefer KIMODO's crisp controllable gestures.
  const sourcePreference = Math.max(0, Math.min(1, expressive * 0.7 + longing * 0.2 - cortisol * 0.3))

  return { weights, energy, sourcePreference }
}

function clamp01(x: number): number {
  return Math.max(0, Math.min(1, x))
}

/**
 * Unified, persona-aware motion library over the merged KIMODO + HY-Motion clip
 * set. Replaces the old "random gesture name → emote pulse" idle behavior with a
 * selection that is biased by intent weights and source preference, plus a true
 * two-source clip blender.
 */
export class MotionFusionLibrary {
  private byNameMap = new Map<string, MotionEntry[]>()
  private readonly all: MotionEntry[] = []

  add(entry: MotionEntry): this {
    if (!entry || !entry.clip)
      return this
    this.all.push(entry)
    const arr = this.byNameMap.get(entry.name) ?? []
    arr.push(entry)
    this.byNameMap.set(entry.name, arr)
    return this
  }

  /** Bulk-add plain AnimationClips (e.g. from `loadOfflineGestureClips`). */
  addClips(
    clips: AnimationClip[],
    source: MotionSource,
    defaultIntents: MotionIntent[],
    nameToIntents?: Record<string, MotionIntent[]>,
  ): this {
    for (const clip of clips) {
      const intents = (clip.name && nameToIntents?.[clip.name]) || defaultIntents
      this.add({ name: clip.name, source, intents, clip, baseWeight: 1 })
    }
    return this
  }

  get entries(): readonly MotionEntry[] {
    return this.all
  }

  get size(): number {
    return this.all.length
  }

  byName(name: string): MotionEntry[] {
    return this.byNameMap.get(name) ?? []
  }

  /**
   * Pick a specific gesture name, choosing the source (KIMODO vs HY-Motion) that
   * best fits `sourcePreference`. Returns null if no clip carries that name.
   */
  pickForName(name: string, sourcePreference = 0.5, rng: () => number = Math.random): MotionEntry | null {
    const candidates = this.byName(name)
    if (!candidates.length)
      return null
    if (candidates.length === 1)
      return candidates[0]
    return this.weightedPick(candidates, sourcePreference, rng)
  }

  /** Pick a clip matching a single intent, weighted by source preference. */
  selectForIntent(intent: MotionIntent, sourcePreference = 0.5, rng: () => number = Math.random): MotionEntry | null {
    const candidates = this.all.filter(e => e.intents.includes(intent))
    if (!candidates.length)
      return null
    return this.weightedPick(candidates, sourcePreference, rng)
  }

  /**
   * Pick a clip whose combined intent weights best match the live persona.
   * Falls back to a source-preference-weighted pick when nothing matches.
   */
  select(weights: MotionIntentWeights, rng: () => number = Math.random): MotionEntry | null {
    if (!this.all.length)
      return null

    let best: MotionEntry | null = null
    let bestScore = -Infinity
    for (const e of this.all) {
      let score = 0
      for (const it of e.intents) {
        const w = weights.weights[it] ?? 0
        if (w > 0)
          score += w
      }
      if (score <= 0)
        continue
      score *= (e.baseWeight ?? 1)
      const entryExpr = e.source === 'hy-motion' ? 1 : 0
      const fit = 1 - Math.abs(weights.sourcePreference - entryExpr)
      score *= (0.4 + 0.6 * fit)
      score *= (0.6 + 0.4 * weights.energy)
      if (score > bestScore) {
        bestScore = score
        best = e
      }
    }
    if (best)
      return best
    // Nothing matched → any clip, weighted by source preference.
    return this.weightedPick(this.all, weights.sourcePreference, rng)
  }

  /** Pick a looping expressive (HY-Motion) clip for a continuous ambient posture. */
  ambient(weights: MotionIntentWeights, rng: () => number = Math.random): MotionEntry | null {
    const loopers = this.all.filter(e => e.source === 'hy-motion')
    if (!loopers.length)
      return this.select(weights, rng)
    return this.weightedPick(loopers, weights.sourcePreference, rng)
  }

  private weightedPick(pool: MotionEntry[], sourcePreference: number, rng: () => number = Math.random): MotionEntry {
    const scored = pool.map((e) => {
      const entryExpr = e.source === 'hy-motion' ? 1 : 0
      const fit = 1 - Math.abs(clamp01(sourcePreference) - entryExpr)
      return { e, s: (0.3 + 0.7 * fit) * (e.baseWeight ?? 1) }
    })
    const total = scored.reduce((a, x) => a + x.s, 0) || 1
    let r = rng() * total
    for (const x of scored) {
      r -= x.s
      if (r <= 0)
        return x.e
    }
    return scored[scored.length - 1].e
  }

  /**
   * True KIMODO × HY-Motion synthesis fusion: blend two clips' bone-quaternion
   * tracks into a single hybrid clip by slerping each bone's rotation toward the
   * other clip at ratio `t` (0 = fully `a`, 1 = fully `b`). Non-quaternion tracks
   * (e.g. expression Number tracks) are copied from `a`; tracks only present in
   * `b` are resampled onto `a`'s timeline and added. If the two clips differ in
   * length the `b` tracks are resampled onto `a`'s time grid so the output is
   * always well-formed.
   */
  blend(a: AnimationClip, b: AnimationClip, t = 0.5, name = 'fused'): AnimationClip {
    const out = new ThreeAnimationClip(name, a.duration)
    const bByName = new Map(b.tracks.map(tr => [tr.name, tr]))
    const aTimes = a.tracks[0]?.times ?? new Float32Array()

    for (const ta of a.tracks) {
      const tb = bByName.get(ta.name)
      if (tb && ta instanceof QuaternionKeyframeTrack && tb instanceof QuaternionKeyframeTrack) {
        const resampled = resampleQuats(tb, ta.times)
        const vals: number[] = []
        const qa = new Quaternion()
        const qb = new Quaternion()
        const qr = new Quaternion()
        for (let i = 0; i < ta.times.length; i++) {
          qa.fromArray(ta.values, i * 4)
          qb.fromArray(resampled, i * 4)
          qr.copy(qa).slerp(qb, t)
          vals.push(qr.x, qr.y, qr.z, qr.w)
        }
        out.tracks.push(new QuaternionKeyframeTrack(ta.name, Array.from(ta.times), vals))
      }
      else {
        out.tracks.push(ta.clone())
      }
    }

    // Tracks present only in `b` (e.g. an expressive head lean) → resample + add.
    const aNames = new Set(a.tracks.map(tr => tr.name))
    for (const tb of b.tracks) {
      if (aNames.has(tb.name))
        continue
      if (tb instanceof QuaternionKeyframeTrack) {
        const resampled = resampleQuats(tb, aTimes)
        out.tracks.push(new QuaternionKeyframeTrack(tb.name, Array.from(aTimes), resampled))
      }
      else {
        out.tracks.push(tb.clone())
      }
    }

    return out
  }
}

/** Resample a quaternion keyframe track's values onto an arbitrary time grid. */
function resampleQuats(track: QuaternionKeyframeTrack, targetTimes: ArrayLike<number>): number[] {
  const srcTimes = track.times
  const srcVals = track.values
  const n = srcTimes.length
  const out: number[] = []
  const qPrev = new Quaternion()
  const qNext = new Quaternion()
  const q = new Quaternion()
  let j = 0
  for (let k = 0; k < targetTimes.length; k++) {
    const tt = targetTimes[k]
    while (j < n - 2 && srcTimes[j + 1] < tt)
      j++
    const t0 = srcTimes[j]
    const t1 = srcTimes[Math.min(j + 1, n - 1)]
    const f = t1 > t0 ? (tt - t0) / (t1 - t0) : 0
    qPrev.fromArray(srcVals, j * 4)
    qNext.fromArray(srcVals, Math.min(j + 1, n - 1) * 4)
    q.copy(qPrev).slerp(qNext, clamp01(f))
    out.push(q.x, q.y, q.z, q.w)
  }
  return out
}
