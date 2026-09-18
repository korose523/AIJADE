import type { V9CausalRuntime } from '@proj-aijade/memory-biomimetic'

/**
 * A 路（video 观察）派发链路测试：
 *  - 路由落库后按 topic 派生 `V9VideoObservationInput` 并接入 `processVideoObservation`；
 *  - `proposalId` 必须是**确定性派生**的（`sp_prop_<eventId>`），同一事件两次派发得到同一值；
 *  - 字段来源正确（sessionId ← payload.session_id，tick/inputHash ← 信封，其余 ← 信封）；
 *  - 派发失败不得让已落库事件回滚（响应仍 201、appendEvent 只调用一次）。
 *  - `dequeueV9VideoObservation` 对非法载荷抛错、空队列返回 undefined。
 */
import { Hono } from 'hono'
import { describe, expect, it, vi } from 'vitest'

import { createV9EventsRoutes } from '../../routes/v9/events'
import { dequeueV9VideoObservation } from './v9-jobs'

function makeApp(service: any, runtime?: any, redis?: any) {
  return new Hono()
    .use('*', async (c, next) => {
      c.set('user' as never, { id: 'u-1' } as any)
      await next()
    })
    .onError((err, c) => {
      if ((err as any)?.statusCode) {
        return c.json({ error: (err as any).errorCode, message: (err as any).message }, (err as any).statusCode)
      }
      return c.json({ error: 'INTERNAL_SERVER_ERROR', message: 'Internal Server Error' }, 500)
    })
    .route('/api/v1/v9/events', createV9EventsRoutes(service, runtime, redis))
}

const ENVELOPE = {
  event_id: 'evt-vo-1',
  trace_id: 'tr-vo-1',
  correlation_id: 'corr-vo-1',
  timestamp: 1_700_000_000_000,
  producer: 'stage-ui',
  origin_device: 'browser',
  privacy_level: 1 as const,
  evidence_refs: [] as string[],
  causal_context_refs: ['tr-vo-1'],
  risk_score: 0,
  idempotency_key: 'vo-1#idem',
  replay_mode: 'live' as const,
  risk_level: 'low' as const,
  tick: 7,
  causality: { inputHash: 'ih-vo-1' },
}

function webpageEvent(sessionId: string, overEnvelope: Record<string, unknown> = {}) {
  return {
    ...ENVELOPE,
    ...overEnvelope,
    topic: 'aijade.video.observation.webpage_text',
    payload: {
      session_id: sessionId,
      source_url: 'https://example.com',
      content_hash: 'ch-1',
      spans: [{ start_offset: 0, end_offset: 5, label: 'p' }],
      observation_text: 'text',
    },
  }
}

describe('v9 video observation dispatch — 确定性 proposalId', () => {
  // 复核报告 R1：派发前必须能取到真实渲染身份（来自 render_traces 真源投影），
  // 否则跳过派发（宁缺勿伪造）。此 mock 模拟"存在真实回执三元组"的正常路径。
  const realIdentity = { renderRef: 'r-1', appliedParamsHash: 'aph-1', assetVersionHash: 'avh-1' }

  it('inline 路径：同一事件两次派发得到同一 proposalId，且字段来源正确（含真实渲染身份）', async () => {
    const calls: any[] = []
    const runtime = {
      processVideoObservation: vi.fn(async (input: any) => {
        calls.push(input)
        return { artifact: {}, tx: { tx_id: 't', status: 'committed', committed: [], rejected: [], throttled: [] }, proposal: {} }
      }),
    } as unknown as V9CausalRuntime
    const service = {
      appendEvent: vi.fn(async () => ({ row: { eventId: 'evt-vo-1' }, deduped: false, pairingMissing: false })),
      findLatestRenderIdentity: vi.fn(async () => realIdentity),
    }
    const app = makeApp(service, runtime) // 无 redis ⇒ 内联归约

    const res1 = await app.request('/api/v1/v9/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(webpageEvent('s-1')),
    })
    const res2 = await app.request('/api/v1/v9/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(webpageEvent('s-1')),
    })

    expect(res1.status).toBe(201)
    expect(res2.status).toBe(201)
    expect(calls).toHaveLength(2)

    // 关键不变量：proposalId 确定性派生，与回放可复现。
    expect(calls[0].proposalId).toBe('sp_prop_evt-vo-1')
    expect(calls[1].proposalId).toBe(calls[0].proposalId)

    // 字段来源正确。
    expect(calls[0].sessionId).toBe('s-1')
    expect(calls[0].eventId).toBe('evt-vo-1')
    expect(calls[0].traceId).toBe('tr-vo-1')
    expect(calls[0].correlationId).toBe('corr-vo-1')
    expect(calls[0].timestamp).toBe(ENVELOPE.timestamp)
    expect(calls[0].originDevice).toBe('browser')
    expect(calls[0].privacyLevel).toBe(1)
    expect(calls[0].riskScore).toBe(0)
    expect(calls[0].tick).toBe(7)
    expect(calls[0].inputHash).toBe('ih-vo-1')
    expect(calls[0].event.topic).toBe('aijade.video.observation.webpage_text')

    // R1：渲染身份三项必须原样来自真源投影（内核 P0-2 守卫据此放行）。
    expect(calls[0].renderRef).toBe('r-1')
    expect(calls[0].appliedParamsHash).toBe('aph-1')
    expect(calls[0].assetVersionHash).toBe('avh-1')
  })

  it('redis 路径：入队 job 的 proposalId 同样确定性派生，且携带真实渲染身份', async () => {
    const enqueued: any[] = []
    const fakeRedis = {
      lpush: vi.fn(async (_q: string, raw: string) => {
        enqueued.push(JSON.parse(raw))
        return 1
      }),
    }
    // 派发需要 runtime 为非空才会进入；redis 路径下只调用 enqueue，不调用 runtime。
    const runtime = {} as unknown as V9CausalRuntime
    const service = {
      appendEvent: vi.fn(async () => ({ row: { eventId: 'evt-vo-2' }, deduped: false, pairingMissing: false })),
      findLatestRenderIdentity: vi.fn(async () => realIdentity),
    }
    const app = makeApp(service, runtime, fakeRedis)

    const res = await app.request('/api/v1/v9/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(webpageEvent('s-2', {
        event_id: 'evt-vo-2',
        idempotency_key: 'vo-2#idem',
        trace_id: 'tr-vo-2',
        correlation_id: 'corr-vo-2',
        tick: 9,
        causality: { inputHash: 'ih-vo-2' },
      })),
    })
    expect(res.status).toBe(201)
    expect(enqueued).toHaveLength(1)
    expect(enqueued[0].input.proposalId).toBe('sp_prop_evt-vo-2')
    expect(enqueued[0].input.sessionId).toBe('s-2')
    expect(enqueued[0].input.tick).toBe(9)
    expect(enqueued[0].input.inputHash).toBe('ih-vo-2')
    expect(enqueued[0].input.renderRef).toBe('r-1')
    expect(enqueued[0].input.appliedParamsHash).toBe('aph-1')
    expect(enqueued[0].input.assetVersionHash).toBe('avh-1')
  })

  it('派发失败不回滚已落库事件：响应仍是 201，appendEvent 只调用一次', async () => {
    const runtime = {
      processVideoObservation: vi.fn(async () => {
        throw new Error('boom')
      }),
    } as unknown as V9CausalRuntime
    const service = {
      appendEvent: vi.fn(async () => ({ row: { eventId: 'evt-vo-3' }, deduped: false, pairingMissing: false })),
      findLatestRenderIdentity: vi.fn(async () => realIdentity),
    }
    const app = makeApp(service, runtime)
    const res = await app.request('/api/v1/v9/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(webpageEvent('s-3', { event_id: 'evt-vo-3', idempotency_key: 'vo-3#idem' })),
    })
    expect(res.status).toBe(201)
    expect(service.appendEvent).toHaveBeenCalledTimes(1)
  })

  it('r1 宁缺勿伪造：无真实渲染身份 ⇒ 跳过派发（runtime 不被调用），事件仍 201', async () => {
    const runtime = {
      processVideoObservation: vi.fn(async () => ({})),
    } as unknown as V9CausalRuntime
    const service = {
      appendEvent: vi.fn(async () => ({ row: { eventId: 'evt-vo-4' }, deduped: false, pairingMissing: false })),
      findLatestRenderIdentity: vi.fn(async () => null),
    }
    const app = makeApp(service, runtime)
    const res = await app.request('/api/v1/v9/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(webpageEvent('s-4', { event_id: 'evt-vo-4', idempotency_key: 'vo-4#idem' })),
    })
    expect(res.status).toBe(201)
    expect(runtime.processVideoObservation).not.toHaveBeenCalled()
    expect(service.appendEvent).toHaveBeenCalledTimes(1)
  })

  it('r1 宁缺勿伪造：redis 路径无真实渲染身份 ⇒ 不入队，事件仍 201', async () => {
    const enqueued: any[] = []
    const fakeRedis = {
      lpush: vi.fn(async (_q: string, raw: string) => {
        enqueued.push(JSON.parse(raw))
        return 1
      }),
    }
    const runtime = {} as unknown as V9CausalRuntime
    const service = {
      appendEvent: vi.fn(async () => ({ row: { eventId: 'evt-vo-5' }, deduped: false, pairingMissing: false })),
      findLatestRenderIdentity: vi.fn(async () => null),
    }
    const app = makeApp(service, runtime, fakeRedis)
    const res = await app.request('/api/v1/v9/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(webpageEvent('s-5', { event_id: 'evt-vo-5', idempotency_key: 'vo-5#idem' })),
    })
    expect(res.status).toBe(201)
    expect(enqueued).toHaveLength(0)
  })
})

describe('v9-jobs dequeueV9VideoObservation', () => {
  it('非法载荷（非 JSON / 缺 jobId+input）抛错', async () => {
    const notJson = { brpop: async () => ['aijade:v9:video-observation', 'not-json'] as any } as any
    await expect(dequeueV9VideoObservation(notJson)).rejects.toThrow()
    const missingFields = { brpop: async () => ['aijade:v9:video-observation', JSON.stringify({ foo: 1 })] as any } as any
    await expect(dequeueV9VideoObservation(missingFields)).rejects.toThrow()
  })

  it('队列空时返回 undefined', async () => {
    const empty = { brpop: async () => undefined } as any
    expect(await dequeueV9VideoObservation(empty)).toBeUndefined()
  })
})
