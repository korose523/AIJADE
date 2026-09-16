import { describe, expect, it } from 'vitest'

import {
  emotionIntensity,
  gazeDirectionToOffset,
  IdleSpontaneousController,
  normalizeEmotionLabel,
  padToPreset,
  personaToIdleBias,
  smoothTowards,
} from './avatar-expression'

describe('normalizeEmotionLabel', () => {
  it('maps known presets and aliases case/space-insensitively', () => {
    expect(normalizeEmotionLabel('happy')).toBe('happy')
    expect(normalizeEmotionLabel('Joy')).toBe('happy')
    expect(normalizeEmotionLabel('  ANGRY ')).toBe('angry')
    expect(normalizeEmotionLabel('cry')).toBe('sad')
  })
  it('falls back to neutral for unknown / empty labels', () => {
    expect(normalizeEmotionLabel('')).toBe('neutral')
    expect(normalizeEmotionLabel('rocket_science')).toBe('neutral')
    expect(normalizeEmotionLabel(null)).toBe('neutral')
  })
})

describe('emotionIntensity', () => {
  it('returns a bounded value in (0,1] for every emotion', () => {
    for (const e of ['neutral', 'happy', 'sad', 'angry', 'surprised', 'thinking', 'loving', 'calm', 'worried'] as const) {
      const v = emotionIntensity(e)
      expect(v).toBeGreaterThan(0)
      expect(v).toBeLessThanOrEqual(1)
    }
  })
  it('keeps expression headroom (never maxed) so the face is not "too raw"', () => {
    expect(emotionIntensity('happy')).toBeLessThan(1)
    expect(emotionIntensity('surprised')).toBeLessThan(1)
    expect(emotionIntensity('angry')).toBeLessThan(1)
  })
})

describe('smoothTowards (anti-jitter core)', () => {
  it('converges toward the target without overshooting', () => {
    let v = 0
    for (let i = 0; i < 200; i++)
      v = smoothTowards(v, 1, 1 / 60, 0.13)
    expect(v).toBeGreaterThan(0.99)
    expect(v).toBeLessThanOrEqual(1)
  })
  it('snaps immediately when tau <= 0', () => {
    expect(smoothTowards(0, 0.7, 1 / 60, 0)).toBe(0.7)
  })
  it('redirects smoothly mid-flight (no snap) — kills streaming-token jitter', () => {
    let v = smoothTowards(0, 1, 1 / 60, 0.13) // partway toward 1
    const mid = v
    v = smoothTowards(v, 0, 1 / 60, 0.13) // retarget to 0 mid-flight
    // first step after retarget must stay continuous (near mid), not jump to 0
    expect(v).toBeGreaterThan(0)
    expect(v).toBeLessThan(mid + 1e-6)
  })
})

describe('gazeDirectionToOffset (LPM-style gaze marker)', () => {
  it('maps cardinal directions to offsets and unknown to center', () => {
    expect(gazeDirectionToOffset('left')).toEqual({ x: -0.35, y: 0, z: 0 })
    expect(gazeDirectionToOffset('right')).toEqual({ x: 0.35, y: 0, z: 0 })
    expect(gazeDirectionToOffset('up')).toEqual({ x: 0, y: 0.35, z: 0 })
    expect(gazeDirectionToOffset('down')).toEqual({ x: 0, y: -0.35, z: 0 })
    expect(gazeDirectionToOffset('center')).toEqual({ x: 0, y: 0, z: 0 })
    expect(gazeDirectionToOffset('nonsense')).toEqual({ x: 0, y: 0, z: 0 })
    expect(gazeDirectionToOffset(null)).toEqual({ x: 0, y: 0, z: 0 })
  })
  it('respects a custom amount', () => {
    expect(gazeDirectionToOffset('left', 1)).toEqual({ x: -1, y: 0, z: 0 })
  })
})

describe('padToPreset', () => {
  it('maps a positive PAD onto happy with bounded intensity', () => {
    const r = padToPreset({ pleasure: 0.8, arousal: 0.1, dominance: 0 })
    expect(r.preset).toBe('happy')
    expect(r.intensity).toBeGreaterThan(0)
    expect(r.intensity).toBeLessThanOrEqual(1)
  })
})

describe('idleSpontaneousController (leuke silence clock)', () => {
  it('fires only after the idle threshold and respects cooldown', () => {
    const c = new IdleSpontaneousController({ pool: ['think'], idleThresholdMs: 100, cooldownMs: 1000 })
    let fired = 0
    c.tick(0, true, () => fired++)
    c.tick(50, true, () => fired++) // before threshold
    expect(fired).toBe(0)
    c.tick(150, true, () => fired++) // past threshold -> fire
    expect(fired).toBe(1)
    c.tick(200, true, () => fired++) // within cooldown -> no fire
    expect(fired).toBe(1)
    c.tick(1200, true, () => fired++) // past cooldown -> fire again
    expect(fired).toBe(2)
  })
  it('resets the silence clock when the user becomes active', () => {
    const c = new IdleSpontaneousController({ idleThresholdMs: 100, cooldownMs: 0 })
    let fired = 0
    c.tick(0, true, () => fired++)
    c.tick(150, true, () => fired++)
    expect(fired).toBe(1)
    c.tick(160, false, () => fired++) // user active -> reset
    c.tick(170, true, () => fired++)
    c.tick(220, true, () => fired++) // under threshold from restart
    expect(fired).toBe(1)
  })
  it('setPool swaps the candidate gestures', () => {
    const c = new IdleSpontaneousController({ pool: ['think'], idleThresholdMs: 0, cooldownMs: 0 })
    const seen = new Set<string>()
    for (let t = 0; t < 50; t++)
      c.tick(t, true, g => seen.add(g))
    expect(seen.has('think')).toBe(true)
    c.setPool(['wave', 'nod'])
    const seen2 = new Set<string>()
    for (let t = 50; t < 100; t++)
      c.tick(t, true, g => seen2.add(g))
    // only the new pool's gestures should ever fire now
    for (const g of seen2)
      expect(['wave', 'nod'].includes(g)).toBe(true)
  })
})

describe('personaToIdleBias (Neuro-Sama / z-waif autonomous core)', () => {
  const warm: any = {
    intimacy: { warmth: 0.9, trust: 0.9, familiarity: 0.9, longing: 0.2 },
    endocrine: { dopamine: 0.8, serotonin: 0.5, cortisol: 0.1, oxytocin: 0.9, adrenaline: 0.1 },
    vector: { playfulness: 0.8, spontaneity: 0.7 },
  }
  const cold: any = {
    intimacy: { warmth: 0.1, trust: 0.1, familiarity: 0.1, longing: 0.2 },
    endocrine: { dopamine: 0.2, serotonin: 0.4, cortisol: 0.2, oxytocin: 0.1, adrenaline: 0.1 },
    vector: { playfulness: 0.2, spontaneity: 0.2 },
  }
  const wistful: any = {
    intimacy: { warmth: 0.6, trust: 0.6, familiarity: 0.7, longing: 0.9 },
    endocrine: { dopamine: 0.4, serotonin: 0.5, cortisol: 0.1, oxytocin: 0.5, adrenaline: 0.1 },
    vector: { playfulness: 0.4, spontaneity: 0.4 },
  }
  const stressed: any = {
    intimacy: { warmth: 0.5, trust: 0.5, familiarity: 0.5, longing: 0.2 },
    endocrine: { dopamine: 0.2, serotonin: 0.2, cortisol: 0.9, oxytocin: 0.3, adrenaline: 0.9 },
    vector: { playfulness: 0.3, spontaneity: 0.3 },
  }

  it('friendly persona → friendly pool + happy drift', () => {
    const b = personaToIdleBias(warm)
    expect(b.pool).toEqual(expect.arrayContaining(['wave', 'nod', 'agree']))
    expect(b.emotion).toBe('happy')
  })
  it('cold/low-familiar persona → cautious pool, no happy drift', () => {
    const b = personaToIdleBias(cold)
    expect(b.pool).toEqual(expect.arrayContaining(['shrug', 'think', 'point']))
    expect(b.emotion).not.toBe('happy')
  })
  it('wistful persona → gaze up', () => {
    const b = personaToIdleBias(wistful)
    expect(b.gazeBias).toBe('up')
  })
  it('stressed persona → fidgety pool + worried drift + faster blink', () => {
    const b = personaToIdleBias(stressed)
    expect(b.pool).toEqual(expect.arrayContaining(['think', 'point', 'surprised']))
    expect(b.emotion).toBe('worried')
    expect(b.blinkRateScale).toBeGreaterThan(1)
  })
  it('always returns a non-empty pool and a clamped blink scale', () => {
    for (const p of [warm, cold, wistful, stressed]) {
      const b = personaToIdleBias(p)
      expect(b.pool.length).toBeGreaterThan(0)
      expect(b.blinkRateScale).toBeGreaterThanOrEqual(0.5)
      expect(b.blinkRateScale).toBeLessThanOrEqual(1.6)
    }
  })
  it('is pure (same input → same output)', () => {
    expect(personaToIdleBias(warm)).toEqual(personaToIdleBias(warm))
  })
})

describe('IdleSpontaneousController determinism (replay contract)', () => {
  const POOL = ['wave', 'nod', 'agree', 'think', 'shrug', 'point'] as const

  /** Drive a controller over a fixed silence timeline; collect fired gestures. */
  function run(seed: number, timeline: { now: number, silence: boolean }[]): string[] {
    const c = new IdleSpontaneousController({ pool: [...POOL], idleThresholdMs: 100, cooldownMs: 100, seed })
    const gestures: string[] = []
    for (const { now, silence } of timeline)
      c.tick(now, silence, g => gestures.push(g))
    return gestures
  }

  /** Long, realistic timeline: silent except for a 1s active burst every 5s. */
  function makeTimeline(): { now: number, silence: boolean }[] {
    const tl: { now: number, silence: boolean }[] = []
    for (let t = 0; t < 60000; t += 100)
      tl.push({ now: t, silence: (t % 5000) >= 1000 })
    return tl
  }

  it('same seed + same tick sequence -> identical gesture sequence', () => {
    const tl = makeTimeline()
    expect(run(42, tl)).toEqual(run(42, tl))
  })

  it('different seed -> different gesture sequence, and always in-pool', () => {
    const tl = makeTimeline()
    const a = run(42, tl)
    const b = run(43, tl)
    expect(a).not.toEqual(b)
    for (const g of a)
      expect(POOL).toContain(g)
  })

  it('reset() does not reseed — a timeline that resets replays identically', () => {
    const tl = makeTimeline()
    const c1 = new IdleSpontaneousController({ pool: [...POOL], idleThresholdMs: 100, cooldownMs: 100, seed: 7 })
    const c2 = new IdleSpontaneousController({ pool: [...POOL], idleThresholdMs: 100, cooldownMs: 100, seed: 7 })
    const g1: string[] = []
    const g2: string[] = []
    for (const { now, silence } of tl) {
      if (now === 20000) { c1.reset(); c2.reset() } // identical reset point in both runs
      c1.tick(now, silence, g => g1.push(g))
      c2.tick(now, silence, g => g2.push(g))
    }
    expect(g1).toEqual(g2)
  })
})
