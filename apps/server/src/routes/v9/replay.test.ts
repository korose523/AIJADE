import type { HonoEnv } from '../../types/hono'

import { PGlite } from '@electric-sql/pglite'
import { computeV6WMaxBounds, PGC_V6_PARAMS_CASE4 } from '@proj-aijade/memory-biomimetic'
import { sql } from 'drizzle-orm'
import { drizzle } from 'drizzle-orm/pglite'
import { Hono } from 'hono'
import { beforeEach, describe, expect, it } from 'vitest'

import { ApiError } from '../../utils/error'
import { createV9ReplayRoutes } from './replay'

import * as schema from '../../schemas/memory-v9'

const DDL = `
  CREATE TABLE "events" (
    "id" text PRIMARY KEY,
    "event_id" text NOT NULL,
    "trace_id" text NOT NULL,
    "correlation_id" text NOT NULL,
    "timestamp" timestamp NOT NULL,
    "producer" text NOT NULL,
    "origin_device" text NOT NULL,
    "privacy_level" integer NOT NULL,
    "evidence_refs" text[] NOT NULL DEFAULT '{}',
    "causal_context_refs" text[] NOT NULL DEFAULT '{}',
    "risk_score" real NOT NULL DEFAULT 0,
    "topic" text NOT NULL,
    "payload" jsonb,
    "idempotency_key" text NOT NULL UNIQUE,
    "replay_mode" text NOT NULL CHECK ("replay_mode" IN ('live','replay')),
    "risk_level" text NOT NULL CHECK ("risk_level" IN ('low','medium','high')),
    "tick" integer,
    "causality" jsonb,
    "core_state_node" text
  );
  CREATE TABLE "pgc_states" (
    "id" text PRIMARY KEY,
    "session_id" text NOT NULL,
    "trace_id" text NOT NULL,
    "policy_version" text NOT NULL,
    "components" jsonb NOT NULL,
    "v6_state" jsonb NOT NULL,
    "created_at" timestamp DEFAULT NOW() NOT NULL
  );
  CREATE TABLE "memory_txs" (
    "id" text PRIMARY KEY,
    "session_id" text NOT NULL,
    "trace_id" text NOT NULL,
    "atomicity" text NOT NULL,
    "max_writes" text NOT NULL,
    "status" text NOT NULL,
    "created_at" timestamp DEFAULT NOW() NOT NULL
  );
  CREATE TABLE "memory_versions" (
    "id" text PRIMARY KEY,
    "memory_tx_id" text NOT NULL
  );
`

const TICK = 42
const INPUT_HASH = 'input-hash-abc'
const TRACE_ID = 'trace-1'

/** 用**当前**实现的 `computeV6WMaxBounds` 生成 v6 快照，再按需篡改。 */
function v6Snapshot(overrides: Record<string, unknown> = {}) {
  const tau = 'episodic' as const
  const f = 0.1
  const bounds = computeV6WMaxBounds(tau, PGC_V6_PARAMS_CASE4, f)
  return {
    tau,
    s: { a: 0.1, c: 0.1, d: 0.1, f },
    w_max_global: bounds.w_max_global,
    w_max_at_f: bounds.w_max_at_f,
    commit_reason: 'committed',
    ...overrides,
  }
}

async function createDb() {
  const client = new PGlite()
  await client.exec(DDL)
  return drizzle(client, { schema })
}

function makeApp(db: ReturnType<typeof drizzle>) {
  return new Hono<HonoEnv>()
    .use('*', async (c, next) => {
      c.set('user', { id: 'user-replay' } as never)
      await next()
    })
    .onError((err, c) => {
      if (err instanceof ApiError)
        return c.json({ error: err.errorCode, message: err.message, details: err.details }, err.statusCode)
      return c.json({ error: 'INTERNAL_SERVER_ERROR', message: 'Internal Server Error' }, 500)
    })
    .route('/api/v1/v9/replay', createV9ReplayRoutes(db as never))
}

describe('v10 replay consistency', () => {
  let db: ReturnType<typeof drizzle>

  beforeEach(async () => {
    db = await createDb()
  })

  /** 写入一条带 v10 字段的事件。 */
  async function seedEvent(opts: {
    eventId: string
    topic: string
    coreStateNode: string | null
    idempotencyKey: string
    tick?: number
    inputHash?: string
  }) {
    await db.insert(schema.v9Events).values({
      id: opts.eventId,
      eventId: opts.eventId,
      traceId: TRACE_ID,
      correlationId: TRACE_ID,
      timestamp: new Date(),
      producer: 'test',
      originDevice: 'test',
      privacyLevel: 1,
      evidenceRefs: [],
      causalContextRefs: [TRACE_ID],
      riskScore: 0,
      topic: opts.topic,
      payload: {},
      idempotencyKey: opts.idempotencyKey,
      replayMode: 'live',
      riskLevel: 'low',
      tick: opts.tick ?? TICK,
      causality: { inputHash: opts.inputHash ?? INPUT_HASH },
      ...(opts.coreStateNode === null ? {} : { coreStateNode: opts.coreStateNode }),
    })
  }

  async function seedPgcState(v6: Record<string, unknown>) {
    await db.insert(schema.v9PgcStates).values({
      id: 'pgc-1',
      sessionId: 'session-1',
      traceId: TRACE_ID,
      policyVersion: 'pgc_policy_v1',
      components: {},
      v6State: v6,
    })
  }

  async function seedMemoryVersion() {
    await db.insert(schema.v9MemoryTxs).values({
      id: 'tx-1',
      sessionId: 'session-1',
      traceId: TRACE_ID,
      atomicity: 'per_write',
      maxWrites: '1',
      status: 'committed',
    })
    // 该测试的 DDL 只建了本模块真正读取的两列（route 只 join `memory_tx_id`），
    // 故用原始 SQL 写入，避免 drizzle 按完整 schema 展开未建的列。
    await db.execute(sql`INSERT INTO "memory_versions" ("id", "memory_tx_id") VALUES ('mv-1', 'tx-1')`)
  }

  async function replay(tick = TICK, inputHash = INPUT_HASH) {
    const res = await makeApp(db).request('/api/v1/v9/replay', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tick, inputHash }),
    })
    return { status: res.status, body: await res.json() as Record<string, unknown> }
  }

  it('reports ok when the recorded node, the memory-version fact and the v6 bounds agree', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: 'S5', idempotencyKey: 'k1' })
    await seedEvent({ eventId: 'e2', topic: 'aijade.memory_tx.committed', coreStateNode: 'S8', idempotencyKey: 'k2' })
    await seedPgcState(v6Snapshot())
    await seedMemoryVersion()

    const { status, body } = await replay()
    expect(status).toBe(200)
    expect(body.ok).toBe(true)
    expect(body.checked).toBe(2)
    expect(body.coreStateNodes).toEqual(['S5', 'S8'])
    expect(body.commitReasons).toEqual(['committed'])
  })

  // ---- 非恒真证明：篡改记录点必须被检出 ----------------------------------
  it('detects a tampered core_state_node (proves the check is not a tautology)', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.memory_tx.committed', coreStateNode: 'S5', idempotencyKey: 'k1' })
    await seedPgcState(v6Snapshot())
    await seedMemoryVersion()

    const { body } = await replay()
    expect(body.ok).toBe(false)
    expect(body.reason).toBe('mismatch')
    const mismatches = body.mismatches as Array<Record<string, unknown>>
    expect(mismatches.some(m => m.kind === 'core_state_node_mismatch')).toBe(true)
  })

  it('flags S8 recorded without a real memory_version', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.memory_tx.committed', coreStateNode: 'S8', idempotencyKey: 'k1' })
    await seedPgcState(v6Snapshot())

    const { body } = await replay()
    expect(body.ok).toBe(false)
    const mismatches = body.mismatches as Array<Record<string, unknown>>
    expect(mismatches.some(m => m.kind === 's8_without_memory_version')).toBe(true)
  })

  it('detects a tampered v6 w_max bound (design §4.3 f must come from the same snapshot)', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: 'S5', idempotencyKey: 'k1' })
    await seedPgcState(v6Snapshot({ w_max_global: 0.123456789 }))

    const { body } = await replay()
    expect(body.ok).toBe(false)
    const mismatches = body.mismatches as Array<Record<string, unknown>>
    expect(mismatches.some(m => m.kind === 'w_max_global_drift')).toBe(true)
  })

  it('reports a commit_reason outside the fixed chain as drift', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: 'S5', idempotencyKey: 'k1' })
    await seedPgcState(v6Snapshot({ commit_reason: 'totally_made_up' }))

    const { body } = await replay()
    expect(body.ok).toBe(false)
    const mismatches = body.mismatches as Array<Record<string, unknown>>
    expect(mismatches.some(m => m.kind === 'commit_reason_outside_fixed_chain')).toBe(true)
  })

  it('degrades to insufficient_input_snapshot for legacy rows with no core_state_node', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: null, idempotencyKey: 'k1' })
    await seedPgcState(v6Snapshot())

    const { body } = await replay()
    expect(body.ok).toBe(false)
    expect(body.reason).toBe('insufficient_input_snapshot')
    const insufficient = body.insufficient as Array<Record<string, unknown>>
    expect(insufficient.some(i => i.kind === 'missing_core_state_node')).toBe(true)
  })

  it('returns an explicit failure when no event matches the snapshot', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: 'S5', idempotencyKey: 'k1' })

    const { status, body } = await replay(TICK, 'unknown-hash')
    expect(status).toBe(404)
    expect(body.ok).toBe(false)
    expect(body.reason).toBe('no_events_for_snapshot')
  })

  it('rejects a malformed replay request at the boundary', async () => {
    const res = await makeApp(db).request('/api/v1/v9/replay', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tick: -1, inputHash: '' }),
    })
    expect(res.status).toBe(400)
  })
})
