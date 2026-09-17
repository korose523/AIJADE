import type { CoreStateNode } from './core-state-node'

import { describe, expect, it } from 'vitest'

import {
  CORE_STATE_NODES,

  deriveCoreStateNode,
} from './core-state-node'

describe('core-state-node', () => {
  it('exposes the full S0..S8 node set', () => {
    expect(CORE_STATE_NODES).toEqual(['S0', 'S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8'])
  })

  it('maps video observation reduction to S2', () => {
    expect(deriveCoreStateNode('aijade.video.observation.video_transcript')).toBe('S2')
    expect(deriveCoreStateNode('aijade.video.observation.webpage_text')).toBe('S2')
  })

  it('maps learning proposal reduction (shadow params) to S3', () => {
    expect(deriveCoreStateNode('aijade.learning.proposed.shadow_params')).toBe('S3')
    expect(deriveCoreStateNode('aijade.learning.proposed.evidence')).toBe('S3')
  })

  it('maps evidence gate evaluation to S4 (non weave_candidate_ready)', () => {
    expect(deriveCoreStateNode('aijade.evidence.some_gate')).toBe('S4')
  })

  it('maps PGC write gating to S5 regardless of commit conclusion', () => {
    expect(deriveCoreStateNode('aijade.pgc.write_plan_ready')).toBe('S5')
    // commitPossible 不影响 S5 选择（门已被求值即归 S5）。
    expect(deriveCoreStateNode('aijade.pgc.write_plan_ready', { commitPossible: true })).toBe('S5')
    expect(deriveCoreStateNode('aijade.pgc.write_plan_ready', { commitPossible: false })).toBe('S5')
  })

  it('maps MemoryTx execution to S6 when nothing was actually persisted', () => {
    expect(deriveCoreStateNode('aijade.memory_tx.committed')).toBe('S6')
    expect(deriveCoreStateNode('aijade.memory_tx.committed', { hasMemoryVersion: false })).toBe('S6')
  })

  it('maps EvidenceWeave ready to S7', () => {
    expect(deriveCoreStateNode('aijade.evidence.weave_candidate_ready')).toBe('S7')
  })

  it('maps MemoryTx committed to S8 only when a memory version was actually persisted', () => {
    expect(deriveCoreStateNode('aijade.memory_tx.committed', { hasMemoryVersion: true })).toBe('S8')
    // 反例：声称 S8 但无落库证据 ⇒ 必须不是 S8（回放据此检出漂移）。
    expect(deriveCoreStateNode('aijade.memory_tx.committed', { hasMemoryVersion: false })).not.toBe('S8')
  })

  it('falls back to S0 / S1 for unlisted and active_learning topics', () => {
    expect(deriveCoreStateNode('aijade.persona.render_requested')).toBe('S0')
    expect(deriveCoreStateNode('aijade.unknown.topic')).toBe('S0')
    expect(deriveCoreStateNode('aijade.active_learning.requested')).toBe('S1')
    expect(deriveCoreStateNode('aijade.active_learning.completed')).toBe('S1')
  })

  it('always returns a member of CORE_STATE_NODES', () => {
    const topics = [
      'aijade.video.observation.video_transcript',
      'aijade.learning.proposed.shadow_params',
      'aijade.pgc.write_plan_ready',
      'aijade.memory_tx.committed',
      'aijade.evidence.weave_candidate_ready',
      'aijade.evidence.other',
      'aijade.active_learning.requested',
      'aijade.persona.render_requested',
    ]
    for (const topic of topics) {
      const node = deriveCoreStateNode(topic, { hasMemoryVersion: true })
      expect(CORE_STATE_NODES).toContain(node as CoreStateNode)
    }
  })
})
