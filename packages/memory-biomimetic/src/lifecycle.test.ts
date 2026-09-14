import type { SweepInput } from './lifecycle'
import type { PhysiologicalState } from './types'

import { describe, expect, it } from 'vitest'

import { DeletionLedger, sweepForgetting, sweepWithGate, tierOf } from './lifecycle'
import { DEFAULT_FORGETTING, DEFAULT_GATING, NO_GATING } from './types'

const DAY = 86_400_000
const T0 = 1_800_000_000_000

const CALM: PhysiologicalState = {
  dopamine: 0.5,
  serotonin: 0.5,
  cortisol: 0.3,
  oxytocin: 0.5,
  adrenaline: 0.3,
  affect: { valence: 0.5, arousal: 0.5, dominance: 0.5 },
}

function item(over: Partial<SweepInput> = {}): SweepInput {
  return {
    id: 'm1',
    createdAt: T0,
    lastAccessedAt: T0,
    accessCount: 0,
    baseStrength: 1,
    durability: 1,
    ...over,
  }
}

describe('tiers (v3 §5 三级驻留)', () => {
  it('maps strength onto hot / warm / cold at the documented thresholds', () => {
    expect(tierOf(0.9)).toBe('hot')
    expect(tierOf(0.6)).toBe('hot')
    expect(tierOf(0.59)).toBe('warm')
    expect(tierOf(0.25)).toBe('warm')
    expect(tierOf(0.24)).toBe('cold')
    expect(tierOf(0)).toBe('cold')
  })
})

describe('two-stage forgetting (v3 §5): demote first, delete never silently', () => {
  it('stage one decays strength and demotes tier, but queues nothing yet (dwell < T)', () => {
    const now = T0 + 5 * DAY
    const r = sweepForgetting(item(), now, DEFAULT_FORGETTING, DEFAULT_GATING, 0.3, 1)
    expect(r.strength).toBeLessThan(1) // 阶段一：衰减
    expect(r.tier).toBe('cold') // 阶段一：降级（但仍未被删除）
    // 驻留仅 5 天 < coldDwellDays(30) ⇒ 只是降级，尚未成为删除候选
    expect(r.deletionCandidate).toBe(false)
  })

  it('stage two queues a candidate only when cold + never accessed + dwelled long enough', () => {
    const now = T0 + 200 * DAY
    // 未满足驻留时长（刚进冷层）
    const shortDwell = sweepForgetting(
      item({ tier: 'cold' }),
      T0 + 31 * DAY,
      DEFAULT_FORGETTING,
      DEFAULT_GATING,
      0.3,
      1,
    )
    expect(shortDwell.deletionCandidate).toBe(true)

    const accessed = sweepForgetting(
      item({ tier: 'cold', accessCount: 3, lastAccessedAt: now }),
      now,
      DEFAULT_FORGETTING,
      DEFAULT_GATING,
      0.3,
      1,
    )
    expect(accessed.deletionCandidate).toBe(false)

    // 仍在温层（2 天后 strength≈0.497 ∈ [0.25,0.6)）⇒ 不是候选
    const warm = sweepForgetting(
      item({ tier: 'warm' }),
      T0 + 2 * DAY,
      DEFAULT_FORGETTING,
      DEFAULT_GATING,
      0.3,
      1,
    )
    expect(warm.tier).toBe('warm')
    expect(warm.deletionCandidate).toBe(false)
  })

  it('gating accelerates decay: gated memory is weaker than ungated at the same age', () => {
    const now = T0 + 90 * DAY
    const gated = sweepWithGate(item({ id: 'g' }), now, DEFAULT_FORGETTING, DEFAULT_GATING, CALM)
    const ungated = sweepWithGate(item({ id: 'u' }), now, DEFAULT_FORGETTING, NO_GATING, CALM)
    // NO_GATING ⇒ decayMultiplier = 1（恒等 gate）
    expect(ungated.strength).toBeCloseTo(
      sweepForgetting(item({ id: 'u' }), now, DEFAULT_FORGETTING, NO_GATING, 0.3, 1).strength,
      12,
    )
    // 皮质醇 > 0 ⇒ decayMultiplier > 1 ⇒ 门控下衰减更快
    expect(gated.strength).toBeLessThan(ungated.strength)
  })
})

describe('deletion ledger — v3 §5 永不静默删除', () => {
  it('enqueue only queues — nothing is deleted', () => {
    const ledger = new DeletionLedger()
    ledger.enqueue('m1', 'cold, never accessed', T0, { decayMultiplier: 1.27, retrievalNoise: 0.08 })
    expect(ledger.pending()).toHaveLength(1)
    expect(ledger.pending()[0].resolution).toBeUndefined()
  })

  it('retain() cancels a queued candidate by id, and is recorded', () => {
    const ledger = new DeletionLedger()
    ledger.enqueue('m1', 'cold', T0, { decayMultiplier: 1, retrievalNoise: 0 })
    expect(ledger.retain('m1', T0 + DAY)).toBe(true)
    expect(ledger.pending()).toHaveLength(0)
    expect(ledger.all()[0].resolution).toBe('retained')
    // 二次 retain 无效
    expect(ledger.retain('m1', T0 + 2 * DAY)).toBe(false)
  })

  it('commit() is the only deleting path, and always leaves an audit record', () => {
    const ledger = new DeletionLedger()
    ledger.enqueue('m1', 'cold', T0, { decayMultiplier: 1, retrievalNoise: 0 })
    expect(ledger.commit('m1', T0 + DAY)).toBe(true)
    const all = ledger.all()
    expect(all).toHaveLength(1)
    expect(all[0].resolution).toBe('deleted')
    expect(all[0].resolvedAt).toBe(T0 + DAY)
    // 未入队的东西不能被"删除"——没有静默删除通道
    expect(ledger.commit('never-queued', T0)).toBe(false)
  })

  it('the gate snapshot is captured for audit (v4 §5.5 gate_snapshot)', () => {
    const ledger = new DeletionLedger()
    ledger.enqueue('m1', 'cold', T0, { decayMultiplier: 1.27, retrievalNoise: 0.081 })
    expect(ledger.all()[0].gateSnapshot).toEqual({ decayMultiplier: 1.27, retrievalNoise: 0.081 })
  })
})
