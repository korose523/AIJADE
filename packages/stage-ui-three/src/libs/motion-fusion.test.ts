import type { PersonaSignal } from './emotion/avatar-expression'
import type { MotionEntry, MotionIntent } from './motion-fusion'

import { AnimationClip, Quaternion, QuaternionKeyframeTrack } from 'three'
import { describe, expect, it } from 'vitest'

import {

  MotionFusionLibrary,

  personaToMotionIntent,
} from './motion-fusion'

function persona(over: Partial<PersonaSignal> = {}): PersonaSignal {
  return {
    intimacy: { warmth: 0.5, trust: 0.5, familiarity: 0.5, longing: 0.2, ...over.intimacy },
    endocrine: { dopamine: 0.5, serotonin: 0.5, cortisol: 0.1, oxytocin: 0.5, adrenaline: 0.1, ...over.endocrine },
    vector: { playfulness: 0.5, spontaneity: 0.5, ...over.vector },
  }
}

function entry(name: string, source: 'kimodo' | 'hy-motion', intents: MotionIntent[], clip?: AnimationClip): MotionEntry {
  return {
    name,
    source,
    intents,
    clip: clip ?? new AnimationClip(name, 1, []),
    baseWeight: 1,
  }
}

function qTrack(name: string, a: number[], b: number[]): QuaternionKeyframeTrack {
  return new QuaternionKeyframeTrack(name, [0, 0.5], [...a, ...b])
}

describe('personaToMotionIntent', () => {
  it('friendly persona → open / agreeable / tender, expressive source preference', () => {
    const w = personaToMotionIntent(persona({
      intimacy: { warmth: 0.95, trust: 0.95, familiarity: 0.9, longing: 0.2 },
      endocrine: { dopamine: 0.9, serotonin: 0.5, cortisol: 0.05, oxytocin: 0.95, adrenaline: 0.1 },
      vector: { playfulness: 0.9, spontaneity: 0.7 },
    }))
    expect(w.weights.open!).toBeGreaterThan(0.5)
    expect(w.weights.agreeable!).toBeGreaterThan(0.5)
    expect(w.weights.tender!).toBeGreaterThan(0.5)
    expect(w.sourcePreference).toBeGreaterThan(0.5) // expressive → prefer HY-Motion
    expect(w.energy).toBeGreaterThan(0.5)
  })

  it('stressed persona → restless / alert, cautious source preference', () => {
    const w = personaToMotionIntent(persona({
      intimacy: { warmth: 0.5, trust: 0.5, familiarity: 0.5, longing: 0.2 },
      endocrine: { dopamine: 0.2, serotonin: 0.2, cortisol: 0.95, oxytocin: 0.3, adrenaline: 0.95 },
      vector: { playfulness: 0.3, spontaneity: 0.3 },
    }))
    expect(w.weights.restless!).toBeGreaterThan(0.5)
    expect(w.weights.alert!).toBeGreaterThan(0.5)
    expect(w.sourcePreference).toBeLessThan(0.5) // cautious → prefer KIMODO
  })

  it('longing persona → strong wistful intent', () => {
    const w = personaToMotionIntent(persona({
      intimacy: { warmth: 0.6, trust: 0.6, familiarity: 0.7, longing: 0.95 },
    }))
    expect(w.weights.wistful!).toBeGreaterThan(0.8)
  })

  it('always returns bounded weights / energy / sourcePreference in [0,1]', () => {
    for (const p of [
      persona({ intimacy: { warmth: 1, trust: 1, familiarity: 1, longing: 1 }, endocrine: { dopamine: 1, serotonin: 1, cortisol: 1, oxytocin: 1, adrenaline: 1 } }),
      persona({ intimacy: { warmth: 0, trust: 0, familiarity: 0, longing: 0 }, endocrine: { dopamine: 0, serotonin: 0, cortisol: 0, oxytocin: 0, adrenaline: 0 } }),
    ]) {
      const w = personaToMotionIntent(p)
      for (const v of Object.values(w.weights)) {
        expect(v!).toBeGreaterThanOrEqual(0)
        expect(v!).toBeLessThanOrEqual(1)
      }
      expect(w.energy).toBeGreaterThanOrEqual(0)
      expect(w.energy).toBeLessThanOrEqual(1)
      expect(w.sourcePreference).toBeGreaterThanOrEqual(0)
      expect(w.sourcePreference).toBeLessThanOrEqual(1)
    }
  })

  it('is pure (same input → same output)', () => {
    const p = persona()
    expect(personaToMotionIntent(p)).toEqual(personaToMotionIntent(p))
  })
})

describe('motionFusionLibrary', () => {
  function build(): MotionFusionLibrary {
    const lib = new MotionFusionLibrary()
    lib.add(entry('wave', 'kimodo', ['playful', 'open']))
    lib.add(entry('reach_out', 'hy-motion', ['open', 'tender']))
    lib.add(entry('fidget', 'hy-motion', ['restless']))
    lib.add(entry('shrug', 'kimodo', ['bashful', 'thoughtful']))
    return lib
  }

  it('registers entries and looks them up by name', () => {
    const lib = build()
    expect(lib.size).toBe(4)
    expect(lib.byName('wave').map(e => e.source)).toEqual(['kimodo'])
    expect(lib.byName('nope')).toEqual([])
  })

  it('select prefers the source matching sourcePreference for a shared intent', () => {
    // For the shared 'open' intent, friendly (expressive) persona should pick the
    // HY-Motion clip over the KIMODO one.
    const lib = new MotionFusionLibrary()
    lib.add(entry('wave', 'kimodo', ['open']))
    lib.add(entry('reach_out', 'hy-motion', ['open']))
    const w = personaToMotionIntent(persona({
      intimacy: { warmth: 0.95, trust: 0.95, familiarity: 0.9, longing: 0.2 },
      endocrine: { dopamine: 0.9, serotonin: 0.5, cortisol: 0.05, oxytocin: 0.95, adrenaline: 0.1 },
      vector: { playfulness: 0.9, spontaneity: 0.7 },
    }))
    const picked = lib.select(w)
    expect(picked?.source).toBe('hy-motion')
  })

  it('selectForIntent returns only clips carrying that intent', () => {
    const lib = build()
    const picked = lib.selectForIntent('restless', 0.5)
    expect(picked?.name).toBe('fidget')
  })

  it('pickForName chooses the source by sourcePreference when a name exists in both', () => {
    const lib = new MotionFusionLibrary()
    lib.add(entry('wave', 'kimodo', ['playful', 'open']))
    lib.add(entry('wave', 'hy-motion', ['playful', 'open']))
    // deterministic rng=0.5 → source preference decides (see weightedPick math)
    expect(lib.pickForName('wave', 0.9, () => 0.5)?.source).toBe('hy-motion')
    expect(lib.pickForName('wave', 0.1, () => 0.5)?.source).toBe('kimodo')
  })

  it('ambient prefers a HY-Motion (expressive) clip', () => {
    const lib = build()
    const w = personaToMotionIntent(persona())
    const a = lib.ambient(w)
    expect(a?.source).toBe('hy-motion')
  })

  it('blend slerps two clips’ bone quaternions at t=0.5 (true KIMODO×HY-Motion fusion)', () => {
    // a: head identity -> 180° about Y ; b: head identity -> 180° about X
    const a = new AnimationClip('a', 0.5, [qTrack('head.quaternion', [0, 0, 0, 1], [0, 1, 0, 0])])
    const b = new AnimationClip('b', 0.5, [qTrack('head.quaternion', [0, 0, 0, 1], [1, 0, 0, 0])])
    const lib = new MotionFusionLibrary()
    const fused = lib.blend(a, b, 0.5, 'fused')

    expect(fused.name).toBe('fused')
    const track = fused.tracks.find(t => t.name === 'head.quaternion') as QuaternionKeyframeTrack
    expect(track).toBeDefined()
    // frame 0: slerp(a=identity, b=identity, .5) = identity
    const fa = new Quaternion().fromArray(track.values, 0)
    expect(fa.angleTo(new Quaternion(0, 0, 0, 1))).toBeLessThan(1e-4)
    // frame 1: slerp(a=180°Y, b=180°X, .5)
    const qbExp = new Quaternion(0, 1, 0, 0).slerp(new Quaternion(1, 0, 0, 0), 0.5)
    const fb = new Quaternion().fromArray(track.values, 4)
    // Threshold 1e-3 (≈0.057°): QuaternionKeyframeTrack quantizes its stored
    // values to Float32, so the round-tripped value carries ~3.7e-4 rad of
    // float-precision noise. The blend itself is exact in float64 — this only
    // guards against gross regressions, not float storage quantization.
    expect(fb.angleTo(qbExp)).toBeLessThan(1e-3)
  })

  it('blend is deterministic and pure (no mutation of inputs)', () => {
    const a = new AnimationClip('a', 0.5, [qTrack('head.quaternion', [0, 0, 0, 1], [0, 1, 0, 0])])
    const before = a.tracks[0].values.slice()
    const lib = new MotionFusionLibrary()
    lib.blend(a, a, 0.3)
    expect(Array.from(a.tracks[0].values)).toEqual(Array.from(before))
  })

  it('select falls back to a source-preference pick when no intent matches', () => {
    const lib = new MotionFusionLibrary()
    lib.add(entry('wave', 'kimodo', ['playful']))
    lib.add(entry('reach_out', 'hy-motion', ['open']))
    // persona with only 'wistful' high → no clip matches → fallback by source pref.
    const w = personaToMotionIntent(persona({
      intimacy: { warmth: 0.6, trust: 0.6, familiarity: 0.7, longing: 0.9 },
      endocrine: { dopamine: 0.2, serotonin: 0.9, cortisol: 0.05, oxytocin: 0.5, adrenaline: 0.1 },
      vector: { playfulness: 0.2, spontaneity: 0.2 },
    }))
    const picked = lib.select(w)
    expect(picked).not.toBeNull()
    // no clip matches 'wistful' → fallback by source preference still returns a valid entry
    expect(['kimodo', 'hy-motion']).toContain(picked?.source)
  })
})
