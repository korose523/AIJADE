import type { RenderAuditEntry } from './types'

import { describe, expect, it } from 'vitest'

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

  it('tags non-numeric channels so the three real channel kinds stay distinguishable', () => {
    expect(fingerprintAppliedParams({ 'emotion.preset': 'happy' })).toBe('emotion.preset=s:happy')
    expect(fingerprintAppliedParams({ 'blink.engaged': true })).toBe('blink.engaged=b:1')
    expect(fingerprintAppliedParams({ 'blink.engaged': false })).toBe('blink.engaged=b:0')
  })

  it('cannot collide across value types (string "0.5" is not the number 0.5)', () => {
    expect(fingerprintAppliedParams({ x: '0.5' })).not.toBe(fingerprintAppliedParams({ x: 0.5 }))
    expect(fingerprintAppliedParams({ x: 'true' })).not.toBe(fingerprintAppliedParams({ x: true }))
  })

  /**
   * 向后兼容锁：数值通道**不带 tag**，所以仅含数值的指纹与本次"支持非数值通道"改动之前
   * 逐位一致。任何给数值加前缀的改动都会让这条变红 —— 那会静默改写已落库指纹的含义。
   */
  it('numeric-only fingerprints are unchanged by the non-numeric widening', () => {
    expect(fingerprintAppliedParams({ b: 1.25, a: 0.4 })).toBe('a=0.4|b=1.25')
  })

  /**
   * 跨边界一致性锁（golden vector）。
   *
   * 表现层（`@proj-aijade/stage-ui` 的 `utils/render-receipt.ts`）**不能** import 本包
   * （会把 `node:fs` 拖进浏览器包），所以它对编码做了有意重复实现。这条字面量在
   * `render-receipt.test.ts` 里被钉了**同一个值**：任一侧改了编码而另一侧不改，
   * 两个测试必有一个变红，`lpm.render_ready.applied_params_hash` 也就不会悄悄对不上。
   * 沿 `stage-ui-three/libs/determinism.ts` 里 mulberry32 跨实现锁的既有房规。
   *
   * 该字面量是用本实现**实跑**出来的，不是手写的。
   */
  it('pins the cross-boundary golden vector (mirrored in stage-ui render-receipt.test.ts)', () => {
    const vector = {
      'emotion.preset': 'happy',
      'emotion.intensity': 0.4,
      'blink.engaged': true,
      'blink.rateScale': 1.25,
      'gaze.dir': 'down',
    }
    expect(fingerprintAppliedParams(vector))
      .toBe('blink.engaged=b:1|blink.rateScale=1.25|emotion.intensity=0.4|emotion.preset=s:happy|gaze.dir=s:down')
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
