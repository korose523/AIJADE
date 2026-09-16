import { describe, expect, it } from 'vitest'

import type { RenderAuditEntry } from './types'

import { buildRenderAuditEntry, fingerprintAppliedParams } from './render-audit'

describe('fingerprintAppliedParams', () => {
  it('is independent of key insertion order (a)', () => {
    const a = fingerprintAppliedParams({ gain: 0.5, relaxation: 1000, noise: 0.02 })
    const b = fingerprintAppliedParams({ noise: 0.02, gain: 0.5, relaxation: 1000 })
    expect(a).toBe(b)
  })

  it('is precision-deterministic, absorbing float noise (b)', () => {
    const a = fingerprintAppliedParams({ a: 0.1 + 0.2 })
    const b = fingerprintAppliedParams({ a: 0.3 })
    expect(a).toBe(b)
  })

  it('returns a stable string (never undefined/NaN) for an empty map (d)', () => {
    const empty = fingerprintAppliedParams({})
    expect(empty).toBe('')
    expect(empty).toBe(fingerprintAppliedParams({}))
  })
})

describe('buildRenderAuditEntry', () => {
  it('fills appliedParamsHash consistently with fingerprintAppliedParams (c)', () => {
    const input: Omit<RenderAuditEntry, 'appliedParamsHash'> = {
      sessionId: 's1',
      turnIndex: 0,
      timestamp: 1_700_000_000_000,
      wallClock: '2026-01-01T00:00:00.000Z',
      renderer: 'live2d',
      displayModelId: 'm1',
      assetVersionHash: 'deadbeef',
      appliedParams: { gain: 0.5, noise: 0.02 },
    }
    const entry = buildRenderAuditEntry(input)
    expect(entry.appliedParamsHash).toBe(fingerprintAppliedParams(input.appliedParams))
  })

  it('preserves all passthrough fields and is key-order independent', () => {
    const input: Omit<RenderAuditEntry, 'appliedParamsHash'> = {
      sessionId: 's2',
      turnIndex: 3,
      timestamp: 1,
      wallClock: 'w',
      renderer: 'vrm',
      displayModelId: 'm2',
      assetVersionHash: 'cafe',
      appliedParams: { x: 0.1 + 0.2, y: 1 },
    }
    const entry = buildRenderAuditEntry(input)
    expect(entry.sessionId).toBe('s2')
    expect(entry.turnIndex).toBe(3)
    expect(entry.renderer).toBe('vrm')
    expect(entry.appliedParamsHash).toBe(fingerprintAppliedParams({ y: 1, x: 0.3 }))
  })
})
