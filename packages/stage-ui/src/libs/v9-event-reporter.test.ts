import type { V9EventEnvelope } from '../utils/render-receipt'

import { describe, expect, it, vi } from 'vitest'

import { authedFetch } from './auth-fetch'
import { reportV9Event, reportV9Perception, V9_EVENTS_ENDPOINT, V9_PERCEPTION_ENDPOINT } from './v9-event-reporter'

// 隔离 authedFetch：只验证"发出去了什么"，不触发真实网络 / Pinia / localStorage。
vi.mock('./auth-fetch', () => ({
  authedFetch: vi.fn(async () => new Response(null, { status: 201 })),
}))

describe('reportV9Event', () => {
  it('posts a plain-JSON envelope to the events endpoint and never throws on success', async () => {
    const envelope: V9EventEnvelope = {
      event_id: 'e1',
      trace_id: 't1',
      correlation_id: 't1',
      timestamp: 123,
      producer: 'stage-ui',
      idempotency_key: 'k1',
      replay_mode: 'live',
      risk_level: 'low',
      topic: 'aijade.lpm.render_ready',
      payload: { session_id: 's1', render_ref: 's1#render:1', applied_params_hash: 'x=y' },
    }

    expect(() => reportV9Event(envelope)).not.toThrow()
    // fire-and-forget：等微任务 flush 后再断言网络调用。
    await new Promise(r => setTimeout(r, 0))

    expect(authedFetch).toHaveBeenCalledTimes(1)
    const [url, init] = (authedFetch as any).mock.calls[0] as [string, RequestInit]
    expect(url).toBe(V9_EVENTS_ENDPOINT)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toMatchObject({
      topic: 'aijade.lpm.render_ready',
      idempotency_key: 'k1',
      // 信封是 topic + 嵌套 payload（与内核 eventEnvelopeSchema 同构）；
      // applied_params_hash 属于 payload，不是信封顶层字段。
      payload: { session_id: 's1', render_ref: 's1#render:1', applied_params_hash: 'x=y' },
    })
  })

  it('swallows HTTP/network errors — never throws into the render path', async () => {
    vi.mocked(authedFetch).mockImplementationOnce(async () => new Response(null, { status: 500 }))

    expect(() => reportV9Event({
      event_id: 'e2',
      trace_id: 't2',
      correlation_id: 't2',
      timestamp: 1,
      producer: 'stage-ui',
      idempotency_key: 'k2',
      replay_mode: 'live',
      risk_level: 'low',
      topic: 'aijade.lpm.render_ready',
      payload: {},
    })).not.toThrow()

    // 即便 fetch 直接 reject 也不能抛。
    vi.mocked(authedFetch).mockImplementationOnce(async () => {
      throw new Error('network down')
    })
    expect(() => reportV9Event({
      event_id: 'e3',
      trace_id: 't3',
      correlation_id: 't3',
      timestamp: 1,
      producer: 'stage-ui',
      idempotency_key: 'k3',
      replay_mode: 'live',
      risk_level: 'low',
      topic: 'aijade.lpm.render_ready',
      payload: {},
    })).not.toThrow()

    await new Promise(r => setTimeout(r, 0))
  })
})

describe('reportV9Perception', () => {
  it('posts the complete trace/session/privacy envelope without exposing media bytes', async () => {
    reportV9Perception({
      event_id: 'audio:e1',
      session_id: 'session-1',
      trace_id: 'trace-1',
      correlation_id: 'correlation-1',
      timestamp: 123,
      origin_device: 'stage-ui',
      privacy_level: 2,
      risk_score: 0,
      source: 'audio:microphone',
      content: '{"mime_type":"audio/wav","bytes":42}',
      stimulus_features: { bytes: 42 },
      risk_level: 'low',
    })
    await new Promise(r => setTimeout(r, 0))

    const [url, init] = (authedFetch as any).mock.calls.at(-1) as [string, RequestInit]
    expect(url).toBe(V9_PERCEPTION_ENDPOINT)
    expect(JSON.parse(init.body as string)).toMatchObject({
      session_id: 'session-1',
      trace_id: 'trace-1',
      correlation_id: 'correlation-1',
      privacy_level: 2,
      source: 'audio:microphone',
      stimulus_features: { bytes: 42 },
    })
  })
})
