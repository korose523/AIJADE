import { PGlite } from '@electric-sql/pglite'
import { eq, sql } from 'drizzle-orm'
import { drizzle } from 'drizzle-orm/pglite'
import { Hono } from 'hono'
import { beforeEach, describe, expect, it } from 'vitest'

import { createV9EventsRoutes } from '../../routes/v9/events'
import { buildMemoryV9Ddl } from '../../schemas/pglite-ddl'
import { createV9EventService } from './v9-events'

import * as schema from '../../schemas/memory-v9'

async function createDb() {
  const client = new PGlite()
  await client.exec(buildMemoryV9Ddl())
  return drizzle(client, { schema })
}

describe('v9 render projection', () => {
  let db: ReturnType<typeof drizzle>

  beforeEach(async () => {
    db = await createDb()
  })

  it('backfills render_traces from request and ready events atomically', async () => {
    const service = createV9EventService(db as never)
    const request = {
      event_id: 'req-1',
      trace_id: 'trace-10',
      correlation_id: 'corr-10',
      timestamp: Date.now(),
      producer: 'stage-ui',
      origin_device: 'browser',
      privacy_level: 1 as const,
      evidence_refs: [],
      causal_context_refs: ['trace-10'],
      risk_score: 0,
      idempotency_key: 's1#request-1',
      replay_mode: 'live' as const,
      risk_level: 'low' as const,
      topic: 'aijade.persona.render_requested',
      payload: {
        session_id: 's1',
        persona_snapshot_ref: 'persona-1',
        intent_ref: 'intent-1',
      },
    }

    const ready = {
      event_id: 'ready-1',
      trace_id: 'trace-10',
      correlation_id: 'corr-10',
      timestamp: Date.now(),
      producer: 'stage-ui',
      origin_device: 'browser',
      privacy_level: 1 as const,
      evidence_refs: [],
      causal_context_refs: ['trace-10', 'intent-1'],
      risk_score: 0,
      idempotency_key: 's1#render-1',
      replay_mode: 'live' as const,
      risk_level: 'low' as const,
      topic: 'aijade.lpm.render_ready',
      payload: {
        session_id: 's1',
        render_ref: 'render-1',
        applied_params_hash: 'hash-42',
        asset_version_hash: 'asset-1',
      },
    }

    const reqRes = await service.appendEvent(request)
    expect(reqRes.deduped).toBe(false)

    const traceRows = await db.select().from(schema.v9RenderTraces).where(eq(schema.v9RenderTraces.traceId, 'trace-10'))
    expect(traceRows).toHaveLength(1)
    expect(traceRows[0].intentRef).toBe('intent-1')
    expect(traceRows[0].personaSnapshotRef).toBe('persona-1')
    // v10 §6.2 / P1-2：只收到请求端时，投影为 partial（缺回执，未配对）。
    expect(traceRows[0].projectionStatus).toBe('partial')
    expect(traceRows[0].personaRenderRequestedEventId).toBe('req-1')
    expect(traceRows[0].renderReadyEventId).toBeNull()

    const readyRes = await service.appendEvent(ready)
    expect(readyRes.deduped).toBe(false)
    expect(readyRes.pairingMissing).toBe(false)

    const afterRows = await db.select().from(schema.v9RenderTraces).where(eq(schema.v9RenderTraces.traceId, 'trace-10'))
    expect(afterRows).toHaveLength(1)
    expect(afterRows[0].renderRef).toBe('render-1')
    expect(afterRows[0].appliedParamsHash).toBe('hash-42')
    expect(afterRows[0].intentRef).toBe('intent-1')
    // 两端齐备后升级为 paired。
    expect(afterRows[0].projectionStatus).toBe('paired')
    expect(afterRows[0].renderReadyEventId).toBe('ready-1')
    expect(afterRows[0].personaRenderRequestedEventId).toBe('req-1')
    expect(await service.isRenderTraceConsistent({
      renderRef: 'render-1',
      intentRef: 'intent-1',
      appliedParamsHash: 'hash-42',
      assetVersionHash: 'asset-1',
    })).toBe(true)
    expect(await service.isRenderTraceConsistent({
      renderRef: 'render-1',
      intentRef: 'intent-1',
      appliedParamsHash: 'wrong-hash',
      assetVersionHash: 'asset-1',
    })).toBe(false)
  })

  it('rolls back the event when a trace identity would be overwritten', async () => {
    const service = createV9EventService(db as never)
    const base = {
      trace_id: 'trace-12',
      correlation_id: 'corr-12',
      timestamp: Date.now(),
      producer: 'stage-ui',
      origin_device: 'browser',
      privacy_level: 1 as const,
      evidence_refs: [],
      causal_context_refs: ['trace-12'],
      risk_score: 0,
      replay_mode: 'live' as const,
      risk_level: 'low' as const,
      topic: 'aijade.lpm.render_ready',
      payload: {
        session_id: 's1',
        render_ref: 'render-12',
        applied_params_hash: 'hash-12',
        asset_version_hash: 'asset-12',
      },
    }

    await service.appendEvent({ ...base, event_id: 'ready-12', idempotency_key: 's1#ready-12' })
    await expect(service.appendEvent({
      ...base,
      event_id: 'ready-13',
      idempotency_key: 's1#ready-13',
      payload: { ...base.payload, render_ref: 'render-13' },
    })).rejects.toThrow('projection_render_ref_mismatch')

    const events = await db.execute(sql`SELECT "id" FROM "events" WHERE "trace_id" = 'trace-12'`)
    const traces = await db.select().from(schema.v9RenderTraces).where(eq(schema.v9RenderTraces.traceId, 'trace-12'))
    expect(events.rows).toHaveLength(1)
    expect(traces).toHaveLength(1)
    expect(traces[0].renderRef).toBe('render-12')
  })

  it('rejects invalid strict payloads before any render projection write', async () => {
    const app = new Hono()
      .use('*', async (c, next) => {
        c.set('user' as never, { id: 'u-1' } as any)
        await next()
      })
      .onError((err, c) => {
        if ((err as any)?.statusCode) {
          return c.json({ error: (err as any).errorCode, message: (err as any).message, details: (err as any).details }, (err as any).statusCode)
        }
        return c.json({ error: 'INTERNAL_SERVER_ERROR', message: 'Internal Server Error' }, 500)
      })
      .route('/api/v1/v9/events', createV9EventsRoutes({
        appendEvent: async () => {
          throw new Error('should not reach service for invalid payloads')
        },
      } as never))

    const res = await app.request('/api/v1/v9/events', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        event_id: 'bad-1',
        trace_id: 'trace-11',
        correlation_id: 'corr-11',
        timestamp: Date.now(),
        producer: 'stage-ui',
        origin_device: 'browser',
        privacy_level: 1 as const,
        evidence_refs: [],
        causal_context_refs: ['trace-11'],
        risk_score: 0,
        idempotency_key: 's1#bad-request',
        replay_mode: 'live',
        risk_level: 'low',
        topic: 'aijade.persona.render_requested',
        payload: {
          session_id: 's1',
          persona_snapshot_ref: 'persona-1',
        },
      }),
    })

    expect(res.status).toBe(400)
    const rows = await db.select().from(schema.v9RenderTraces)
    expect(rows).toHaveLength(0)
  })
})
