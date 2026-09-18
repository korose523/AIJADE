import { PGlite } from '@electric-sql/pglite'
import { drizzle } from 'drizzle-orm/pglite'
import { beforeEach, describe, expect, it } from 'vitest'

import { buildMemoryV9Ddl } from '../../schemas/pglite-ddl'
import { planRenderTraceBackfill, runRenderTraceBackfill } from './render-trace-backfill'

import * as schema from '../../schemas/memory-v9'

const DDL = buildMemoryV9Ddl()

async function createDb() {
  const client = new PGlite()
  await client.exec(DDL)
  return drizzle(client, { schema })
}

type TestDb = ReturnType<typeof drizzle>

async function seedEvent(
  db: TestDb,
  opts: { eventId: string, traceId: string, topic: string, payload: Record<string, unknown>, at: Date },
) {
  await db.insert(schema.v9Events).values({
    id: opts.eventId,
    eventId: opts.eventId,
    traceId: opts.traceId,
    correlationId: opts.traceId,
    timestamp: opts.at,
    producer: 'test',
    originDevice: 'test',
    privacyLevel: 1,
    evidenceRefs: [],
    causalContextRefs: [opts.traceId],
    riskScore: 0,
    topic: opts.topic,
    payload: opts.payload,
    idempotencyKey: `k-${opts.eventId}`,
    replayMode: 'live',
    riskLevel: 'low',
  })
}

const REQUEST = 'aijade.persona.render_requested'
const READY = 'aijade.lpm.render_ready'

describe('render_traces offline backfill', () => {
  let db: TestDb

  beforeEach(async () => {
    db = await createDb()
  })

  it('rebuilds a projection row from a matched request/ready pair', async () => {
    const base = new Date('2026-01-01T00:00:00Z')
    await seedEvent(db, {
      eventId: 'req-1',
      traceId: 't1',
      topic: REQUEST,
      payload: { session_id: 's1', persona_snapshot_ref: 'snap-1', intent_ref: 'r:1' },
      at: base,
    })
    await seedEvent(db, {
      eventId: 'ready-1',
      traceId: 't1',
      topic: READY,
      payload: { session_id: 's1', render_ref: 'r:1', applied_params_hash: 'h1', asset_version_hash: 'a1' },
      at: new Date('2026-01-01T00:00:01Z'),
    })

    const report = await runRenderTraceBackfill(db as never)
    expect(report.inserted).toBe(1)
    expect(report.incomplete).toEqual([])

    const rows = await db.select().from(schema.v9RenderTraces)
    expect(rows).toHaveLength(1)
    expect(rows[0].traceId).toBe('t1')
    expect(rows[0].intentRef).toBe('r:1')
    expect(rows[0].renderRef).toBe('r:1')
    expect(rows[0].appliedParamsHash).toBe('h1')
    expect(rows[0].assetVersionHash).toBe('a1')
    expect(rows[0].personaSnapshotRef).toBe('snap-1')
    // v10 §6.2 / P1-2：请求+回执齐备 ⇒ paired；两端事件 id 回填。
    expect(rows[0].projectionStatus).toBe('paired')
    expect(rows[0].renderReadyEventId).toBe('ready-1')
    expect(rows[0].personaRenderRequestedEventId).toBe('req-1')
  })

  it('is idempotent: a second run inserts nothing', async () => {
    const base = new Date('2026-01-01T00:00:00Z')
    await seedEvent(db, { eventId: 'req-1', traceId: 't1', topic: REQUEST, payload: { session_id: 's1', intent_ref: 'r:1' }, at: base })
    await seedEvent(db, {
      eventId: 'ready-1',
      traceId: 't1',
      topic: READY,
      payload: { session_id: 's1', render_ref: 'r:1', applied_params_hash: 'h1' },
      at: base,
    })

    await runRenderTraceBackfill(db as never)
    const second = await runRenderTraceBackfill(db as never)
    expect(second.inserted).toBe(0)
    expect(second.skippedExisting).toBe(1)
    expect(await db.select().from(schema.v9RenderTraces)).toHaveLength(1)
  })

  it('does not fabricate a projection when the ready event is missing', async () => {
    await seedEvent(db, {
      eventId: 'req-1',
      traceId: 't1',
      topic: REQUEST,
      payload: { session_id: 's1', intent_ref: 'r:1' },
      at: new Date(),
    })

    const report = await runRenderTraceBackfill(db as never)
    expect(report.inserted).toBe(0)
    expect(report.incomplete).toEqual([{ traceId: 't1', reason: 'missing_lpm_render_ready' }])
    expect(await db.select().from(schema.v9RenderTraces)).toHaveLength(0)
  })

  it('skips a trace whose request and ready disagree on session_id', async () => {
    const base = new Date('2026-01-01T00:00:00Z')
    await seedEvent(db, { eventId: 'req-1', traceId: 't1', topic: REQUEST, payload: { session_id: 's1', intent_ref: 'r:1' }, at: base })
    await seedEvent(db, {
      eventId: 'ready-1',
      traceId: 't1',
      topic: READY,
      payload: { session_id: 's2', render_ref: 'r:1', applied_params_hash: 'h1' },
      at: base,
    })

    const report = await runRenderTraceBackfill(db as never)
    expect(report.inserted).toBe(0)
    expect(report.conflicts).toEqual([{ traceId: 't1', reason: 'session_id_mismatch_between_request_and_ready' }])
  })

  it('dry-run plans without writing', async () => {
    const base = new Date('2026-01-01T00:00:00Z')
    await seedEvent(db, { eventId: 'req-1', traceId: 't1', topic: REQUEST, payload: { session_id: 's1', intent_ref: 'r:1' }, at: base })
    await seedEvent(db, {
      eventId: 'ready-1',
      traceId: 't1',
      topic: READY,
      payload: { session_id: 's1', render_ref: 'r:1', applied_params_hash: 'h1' },
      at: base,
    })

    const report = await runRenderTraceBackfill(db as never, { dryRun: true })
    expect(report.plannedRows).toBe(1)
    expect(report.inserted).toBe(0)
    expect(await db.select().from(schema.v9RenderTraces)).toHaveLength(0)
  })

  it('planner is deterministic and derives a stable id from the trace id', () => {
    const events = [
      { eventId: 'r1', traceId: 't1', correlationId: 't1', topic: REQUEST, payload: { session_id: 's1', intent_ref: 'i:1' }, timestamp: 1 },
      { eventId: 'r2', traceId: 't1', correlationId: 't1', topic: READY, payload: { session_id: 's1', render_ref: 'i:1', applied_params_hash: 'h' }, timestamp: 2 },
    ]
    const a = planRenderTraceBackfill(events)
    const b = planRenderTraceBackfill([...events].reverse())
    expect(a.rows).toEqual(b.rows)
    expect(a.rows[0].id).toBe('rt_t1')
  })
})
