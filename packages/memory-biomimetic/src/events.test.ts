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
      { topic: 'aijade.active_learning.requested', payload: { session_id: 's', trace_id: 't', requested_at: 1, quest_ref: 'q1', resource_budget: { allocated: 10, spent: 0, unit: 'queries' }, stop_conditions: ['信息增益低于阈值'] } },
      { topic: 'aijade.active_learning.completed', payload: { session_id: 's', trace_id: 't', completed_at: 2, quest_ref: 'q1' } },
      { topic: 'aijade.evidence.weave_candidate_ready', payload: { tx_id: 'x', weave_id: 'w', graph_hash: 'h', candidate_memory_write_ids: [] } },
      { topic: 'aijade.pgc.write_plan_ready', payload: { pgc_state_id: 'p', write_plan_size: 1, policy_version: 'v1' } },
      { topic: 'aijade.memory_tx.committed', payload: { tx_id: 'x', trace_id: 't', committed_count: 1, rejected_count: 0, throttled_count: 0 } },
      { topic: 'aijade.persona.render_requested', payload: { session_id: 's', persona_snapshot_ref: 'ps1', intent_ref: 'pi1' } },
      { topic: 'aijade.lpm.render_ready', payload: { session_id: 's' } },
    ]
    for (const t of topics) {
      const r = aijadeEventSchema.safeParse({ ...baseEnvelope(), topic: t.topic, payload: t.payload })
      expect(r.success, `topic ${t.topic} 应被接受`).toBe(true)
    }
  })
})

describe('有界性 — v8 §48.2 由 schema 保证（不是靠调用方自觉）', () => {
  const validRequested = {
    session_id: 's',
    trace_id: 't',
    requested_at: 1,
    quest_ref: 'q1',
    resource_budget: { allocated: 10, spent: 0, unit: 'queries' },
    stop_conditions: ['信息增益低于阈值'],
  }

  function parseRequested(payload: Record<string, unknown>) {
    return safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.active_learning.requested', payload })
  }

  it('基线：合法请求被接受', () => {
    expect(parseRequested(validRequested).success).toBe(true)
  })

  it('缺 stop_conditions ⇒ 拒绝（禁止无终点浏览）', () => {
    const { stop_conditions: _drop, ...rest } = validRequested
    expect(parseRequested(rest).success).toBe(false)
  })

  it('stop_conditions 为空数组 ⇒ 拒绝', () => {
    expect(parseRequested({ ...validRequested, stop_conditions: [] }).success).toBe(false)
  })

  it('缺 resource_budget ⇒ 拒绝（任务必须在开始前被界定）', () => {
    const { resource_budget: _drop, ...rest } = validRequested
    expect(parseRequested(rest).success).toBe(false)
  })

  it('spent > allocated ⇒ 拒绝（预算必须可界定）', () => {
    const r = parseRequested({ ...validRequested, resource_budget: { allocated: 5, spent: 6, unit: 'queries' } })
    expect(r.success).toBe(false)
  })

  it('缺 quest_ref ⇒ 拒绝（无法回指活真源）', () => {
    const { quest_ref: _drop, ...rest } = validRequested
    expect(parseRequested(rest).success).toBe(false)
  })
})

describe('渲染请求 — §52.5 引用必填', () => {
  function parseRenderRequested(payload: Record<string, unknown>) {
    return safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.persona.render_requested', payload })
  }

  it('缺 persona_snapshot_ref ⇒ 拒绝（先渲染再补身份被排除）', () => {
    expect(parseRenderRequested({ session_id: 's', intent_ref: 'pi1' }).success).toBe(false)
  })

  it('persona_snapshot_ref 为空串 ⇒ 拒绝', () => {
    expect(parseRenderRequested({ session_id: 's', persona_snapshot_ref: '', intent_ref: 'pi1' }).success).toBe(false)
  })

  it('缺 intent_ref ⇒ 拒绝（否则 lpm.render_ready 无法回指）', () => {
    expect(parseRenderRequested({ session_id: 's', persona_snapshot_ref: 'ps1' }).success).toBe(false)
  })

  it('已废弃的旧字段名 persona_ref 不再被接受', () => {
    expect(parseRenderRequested({ session_id: 's', persona_ref: 'ps1' }).success).toBe(false)
  })
})
