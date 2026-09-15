import { describe, expect, it } from 'vitest'

import {
  aijadeEventSchema,
  eventEnvelopeSchema,
  memoryTxCommittedEvent,
  safeParseAijadeEvent,
} from './events'

function baseEnvelope(over: Record<string, unknown> = {}) {
  return {
    event_id: 'evt_1',
    trace_id: 'tr_1',
    correlation_id: 'cor_1',
    timestamp: 1_700_000_000_000,
    producer: 'memory-tx',
    idempotency_key: 'idem_1',
    replay_mode: 'live',
    risk_level: 'low',
    ...over,
  }
}

describe('事件信封 — 统一契约', () => {
  it('合法信封通过校验', () => {
    const ok = eventEnvelopeSchema.parse({ ...baseEnvelope(), topic: 'aijade.memory_tx.committed', payload: { tx_id: 't' } })
    expect(ok.event_id).toBe('evt_1')
  })

  it('缺少 idempotency_key ⇒ 拒绝（支撑 events 表唯一约束/幂等）', () => {
    const r = eventEnvelopeSchema.safeParse({ ...baseEnvelope(), idempotency_key: undefined })
    expect(r.success).toBe(false)
  })

  it('非法 risk_level / replay_mode ⇒ 拒绝', () => {
    expect(eventEnvelopeSchema.safeParse({ ...baseEnvelope(), risk_level: 'critical' }).success).toBe(false)
    expect(eventEnvelopeSchema.safeParse({ ...baseEnvelope(), replay_mode: 'maybe' }).success).toBe(false)
  })
})

describe('topic schema — 判别联合', () => {
  it('已知 topic 的强类型事件通过校验', () => {
    const ev = memoryTxCommittedEvent.parse({
      ...baseEnvelope(),
      topic: 'aijade.memory_tx.committed',
      payload: { tx_id: 'tx_1', trace_id: 'tr_1', committed_count: 2, rejected_count: 0, throttled_count: 1 },
    })
    expect(ev.topic).toBe('aijade.memory_tx.committed')
    expect((ev.payload as { committed_count: number }).committed_count).toBe(2)
  })

  it('未知 topic ⇒ 拒绝（强制登记，防止静默接受非法事件）', () => {
    const r = safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.unknown.topic', payload: {} })
    expect(r.success).toBe(false)
  })

  it('payload 形状错误（缺字段）⇒ 拒绝', () => {
    const r = safeParseAijadeEvent({
      ...baseEnvelope(),
      topic: 'aijade.pgc.write_plan_ready',
      payload: { pgc_state_id: 'x' }, // 缺 write_plan_size / policy_version
    })
    expect(r.success).toBe(false)
  })

  it('全部 7 个规范 topic 都能被判别联合接受', () => {
    const topics: { topic: string, payload: Record<string, unknown> }[] = [
      { topic: 'aijade.active_learning.requested', payload: { session_id: 's', trace_id: 't', requested_at: 1 } },
      { topic: 'aijade.active_learning.completed', payload: { session_id: 's', trace_id: 't', completed_at: 2 } },
      { topic: 'aijade.evidence.weave_candidate_ready', payload: { tx_id: 'x', weave_id: 'w', graph_hash: 'h', candidate_memory_write_ids: [] } },
      { topic: 'aijade.pgc.write_plan_ready', payload: { pgc_state_id: 'p', write_plan_size: 1, policy_version: 'v1' } },
      { topic: 'aijade.memory_tx.committed', payload: { tx_id: 'x', trace_id: 't', committed_count: 1, rejected_count: 0, throttled_count: 0 } },
      { topic: 'aijade.persona.render_requested', payload: { session_id: 's' } },
      { topic: 'aijade.lpm.render_ready', payload: { session_id: 's' } },
    ]
    for (const t of topics) {
      const r = aijadeEventSchema.safeParse({ ...baseEnvelope(), topic: t.topic, payload: t.payload })
      expect(r.success, `topic ${t.topic} 应被接受`).toBe(true)
    }
  })
})
