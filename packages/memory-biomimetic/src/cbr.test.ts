import type { ItePair, ReplayBundle, ReplayRun } from './cbr'

import { describe, expect, it } from 'vitest'

import {
  estimateITE,
  intervene,

  pairReplays,
  REPLAY_BUNDLE_SCHEMA,

  replayConsistency,
  ReplayLog,

  validateReplayBundle,
} from './cbr'

const STATE_KEYS = ['a', 'v', 'd', 'n', 's', 'c', 'b']

function state(fill: number): Record<string, number> {
  return Object.fromEntries(STATE_KEYS.map(k => [k, fill]))
}

function bundle(over: Partial<ReplayBundle> = {}): ReplayBundle {
  return {
    schema: REPLAY_BUNDLE_SCHEMA,
    bundleId: 'b1',
    event_ids: ['e1', 'e2'],
    state_before: state(0.2),
    memory_ids_retrieved: ['m1'],
    prompt_digest: 'sha256:abc',
    model_manifest: { model: 'qwythos:latest', sampling: { temperature: 0 } },
    action_plan: ['retrieve', 'answer'],
    tool_results: [{ ok: true }],
    speech_timeline: [{ t: 0, text: 'the answer is four' }],
    semantic_motion: [{ t: 0, motion: 'nod' }],
    user_feedback: { valence: 0.5, signal: 'F' },
    state_after: state(0.6),
    ...over,
  }
}

describe('validateReplayBundle', () => {
  it('accepts a well-formed 13-field bundle', () => {
    expect(validateReplayBundle(bundle())).toEqual({ ok: true })
  })

  it('rejects a wrong schema', () => {
    const r = validateReplayBundle(bundle({ schema: 'aijade.replay_bundle@9' as ReplayBundle['schema'] }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/schema/)
  })

  it('rejects a bundle with no events (a replay must replay events)', () => {
    const r = validateReplayBundle(bundle({ event_ids: [] }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/event_id/)
  })

  it('rejects a missing prompt_digest (replay must be content-addressed)', () => {
    const r = validateReplayBundle(bundle({ prompt_digest: '' }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/prompt_digest/)
  })

  it('rejects a bundle that does not name its model', () => {
    const r = validateReplayBundle(bundle({ model_manifest: { model: '', sampling: {} } }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/model/)
  })

  it('rejects state_before/state_after with different key sets (comparability)', () => {
    const r = validateReplayBundle(bundle({ state_after: { a: 1 } }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/key set/)
  })

  it('rejects an out-of-range valence', () => {
    expect(validateReplayBundle(bundle({ user_feedback: { valence: 2, signal: 'F' } })).ok).toBe(false)
    expect(validateReplayBundle(bundle({ user_feedback: { valence: Number.NaN, signal: 'F' } })).ok).toBe(false)
  })
})

describe('intervene (§12 干预回放)', () => {
  it('replaces state, keeps bundleId and event_ids so the pair stays matchable', () => {
    const b = bundle()
    const out = intervene(b, { state_before: state(0.9) })
    expect(out.state_before).toEqual(state(0.9))
    expect(out.bundleId).toBe(b.bundleId)
    expect(out.event_ids).toEqual(b.event_ids)
  })

  it('is pure — never mutates the input bundle', () => {
    const b = bundle()
    const snapshot = JSON.stringify(b)
    intervene(b, { memory_ids_retrieved: ['m9'], model_manifest: { model: 'other', sampling: {} } })
    expect(JSON.stringify(b)).toBe(snapshot)
  })

  it('replaces memory ids and model manifest', () => {
    const out = intervene(bundle(), {
      memory_ids_retrieved: ['m7'],
      model_manifest: { model: 'other:latest', sampling: { temperature: 0 } },
    })
    expect(out.memory_ids_retrieved).toEqual(['m7'])
    expect(out.model_manifest.model).toBe('other:latest')
  })
})

describe('replayConsistency (§12 具身回放)', () => {
  it('is 1.0 for identical bundles', () => {
    const c = replayConsistency(bundle(), bundle())
    expect(c.speech).toBe(1)
    expect(c.motion).toBe(1)
    expect(c.overall).toBe(1)
  })

  it('is 0 for completely disjoint speech and motion', () => {
    const a = bundle({ speech_timeline: [{ t: 0, text: 'alpha beta' }], semantic_motion: [{ t: 0, motion: 'nod' }] })
    const b = bundle({ speech_timeline: [{ t: 0, text: 'gamma delta' }], semantic_motion: [{ t: 0, motion: 'wave' }] })
    const c = replayConsistency(a, b)
    expect(c.speech).toBe(0)
    expect(c.motion).toBe(0)
    expect(c.overall).toBe(0)
  })

  it('is symmetric and bounded for partial overlap', () => {
    const a = bundle({ speech_timeline: [{ t: 0, text: 'alpha beta gamma' }], semantic_motion: [{ t: 0, motion: 'nod' }, { t: 1, motion: 'smile' }] })
    const b = bundle({ speech_timeline: [{ t: 0, text: 'alpha beta delta' }], semantic_motion: [{ t: 0, motion: 'nod' }, { t: 1, motion: 'wave' }] })
    const ab = replayConsistency(a, b)
    const ba = replayConsistency(b, a)
    expect(ab.overall).toBeCloseTo(ba.overall, 10)
    expect(ab.overall).toBeGreaterThan(0)
    expect(ab.overall).toBeLessThan(1)
    // motion: |{nod,smile} ∩ {nod,wave}| / |{nod,smile,wave}| = 1/3
    expect(ab.motion).toBeCloseTo(1 / 3, 10)
  })
})

describe('pairReplays (§12 同一事件束配对)', () => {
  const run = (b: ReplayBundle, outcome: number): ReplayRun => ({ bundle: b, outcome })

  it('pairs treated and control sharing the same bundleId and event_ids', () => {
    const t = run(bundle(), 0.9)
    const c = run(bundle(), 0.7)
    const r = pairReplays([t], [c])
    expect(r.pairs).toHaveLength(1)
    expect(r.pairs[0]).toEqual({ bundleId: 'b1', treated: 0.9, control: 0.7 })
    expect(r.pairingRate).toBe(1)
  })

  it('refuses to pair the same bundleId with different events (not the same event bundle)', () => {
    const t = run(bundle({ event_ids: ['e1', 'e2'] }), 0.9)
    const c = run(bundle({ event_ids: ['e1', 'e9'] }), 0.7)
    const r = pairReplays([t], [c])
    expect(r.pairs).toHaveLength(0)
    expect(r.unmatched).toEqual(['b1'])
    expect(r.pairingRate).toBe(0)
  })

  it('reports unmatched treated bundles instead of dropping them silently', () => {
    const t1 = run(bundle({ bundleId: 'b1' }), 1)
    const t2 = run(bundle({ bundleId: 'b2' }), 1)
    const c1 = run(bundle({ bundleId: 'b1' }), 0)
    const r = pairReplays([t1, t2], [c1])
    expect(r.pairs).toHaveLength(1)
    expect(r.unmatched).toEqual(['b2'])
    expect(r.pairingRate).toBeCloseTo(0.5, 10)
  })

  it('returns an empty (rate 0) result for no treated runs', () => {
    expect(pairReplays([], []).pairingRate).toBe(0)
  })
})

describe('estimateITE (§12 可证伪因果估计)', () => {
  const pair = (treated: number, control: number): ItePair => ({ bundleId: 'b', treated, control })

  it('detects a consistent positive effect as significant', () => {
    const e = estimateITE([pair(0.9, 0.7), pair(0.8, 0.6), pair(0.7, 0.5)])
    expect(e.n).toBe(3)
    expect(e.mean).toBeCloseTo(0.2, 10)
    expect(e.sd).toBeCloseTo(0, 10)
    expect(e.significant).toBe(true)
    expect(e.ci95[0]).toBeCloseTo(0.2, 10)
    expect(e.ci95[1]).toBeCloseTo(0.2, 10)
  })

  it('reports a null effect — CI straddles 0, claim is falsified', () => {
    const e = estimateITE([pair(1, 0), pair(-1, 0), pair(0.2, 0), pair(-0.2, 0)])
    expect(e.mean).toBeCloseTo(0, 10)
    expect(e.significant).toBe(false)
    expect(e.ci95[0]).toBeLessThan(0)
    expect(e.ci95[1]).toBeGreaterThan(0)
  })

  it('marks a small noisy effect as not significant (wide CI)', () => {
    const e = estimateITE([pair(1, 0), pair(-0.9, 0), pair(0.95, 0), pair(-0.85, 0)])
    expect(e.significant).toBe(false)
  })

  it('handles an empty input without throwing', () => {
    const e = estimateITE([])
    expect(e.n).toBe(0)
    expect(e.mean).toBe(0)
    expect(e.significant).toBe(false)
  })

  it('keeps per-pair detail for auditing', () => {
    const e = estimateITE([pair(1, 0.5), pair(0.4, 0.2)])
    expect(e.perPair).toHaveLength(2)
    expect(e.perPair[0].treated - e.perPair[0].control).toBeCloseTo(0.5, 10)
  })
})

describe('replayLog (append-only replay evidence)', () => {
  it('stores a valid bundle and reads it back', () => {
    const log = new ReplayLog()
    expect(log.add(bundle()).ok).toBe(true)
    expect(log.size).toBe(1)
    expect(log.get('b1')?.prompt_digest).toBe('sha256:abc')
    expect(log.all()).toHaveLength(1)
  })

  it('rejects an invalid bundle', () => {
    const log = new ReplayLog()
    const r = log.add(bundle({ event_ids: [] }))
    expect(r.ok).toBe(false)
    expect(log.size).toBe(0)
  })

  it('refuses to overwrite an existing bundleId (replay is evidence, not cache)', () => {
    const log = new ReplayLog()
    log.add(bundle())
    const r = log.add(bundle({ prompt_digest: 'sha256:changed' }))
    expect(r.ok).toBe(false)
    if (!r.ok)
      expect(r.reason).toMatch(/append-only/)
    expect(log.get('b1')?.prompt_digest).toBe('sha256:abc')
  })
})

describe('end-to-end: gated ON vs OFF on the same event bundle', () => {
  it('turns a paired replay experiment into a falsifiable ITE claim', () => {
    // 同一事件束（event_ids 相同），门控开/关各跑一遍
    const mk = (i: number, gateOn: boolean): ReplayRun => {
      const b = bundle({
        bundleId: `b${i}`,
        state_before: state(gateOn ? 0.3 : 0.3),
        memory_ids_retrieved: gateOn ? [`m${i}`] : [`m${i}`, `noise${i}`],
        model_manifest: { model: 'qwythos:latest', sampling: { temperature: 0 } },
      })
      // 门控开启时上下文纯净，得分稳定更高
      return { bundle: b, outcome: gateOn ? 0.8 : 0.6 }
    }
    const treated = [mk(1, true), mk(2, true), mk(3, true), mk(4, true)]
    const control = [mk(1, false), mk(2, false), mk(3, false), mk(4, false)]

    const { pairs, pairingRate } = pairReplays(treated, control)
    expect(pairingRate).toBe(1)

    const e = estimateITE(pairs)
    expect(e.n).toBe(4)
    expect(e.mean).toBeCloseTo(0.2, 10)
    expect(e.significant).toBe(true)
    expect(e.ci95[0]).toBeGreaterThan(0)
  })

  it('falsifies the claim when gating makes no paired difference', () => {
    const mk = (i: number, gateOn: boolean): ReplayRun => ({
      bundle: bundle({ bundleId: `b${i}`, memory_ids_retrieved: gateOn ? [`m${i}`] : [`m${i}`, `noise${i}`] }),
      outcome: 0.7, // 完全无差异
    })
    const treated = [mk(1, true), mk(2, true)]
    const control = [mk(1, false), mk(2, false)]
    const e = estimateITE(pairReplays(treated, control).pairs)
    expect(e.mean).toBe(0)
    expect(e.significant).toBe(false)
  })
})
