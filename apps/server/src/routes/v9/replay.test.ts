import type { HonoEnv } from '../../types/hono'

import { PGlite } from '@electric-sql/pglite'
import { computeV6WMaxBounds, PGC_V6_PARAMS_CASE4 } from '@proj-aijade/memory-biomimetic'
import { sql } from 'drizzle-orm'
import { drizzle } from 'drizzle-orm/pglite'
import { Hono } from 'hono'
import { beforeEach, describe, expect, it } from 'vitest'

import { buildMemoryV9Ddl } from '../../schemas/pglite-ddl'
import { ApiError } from '../../utils/error'
import { createV9ReplayRoutes } from './replay'

import * as schema from '../../schemas/memory-v9'

const DDL = buildMemoryV9Ddl()

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

  /**
   * 像**运行期持久化**那样写入决策快照：`v6` 挂在
   * `write_plan[].pgcStateSnapshot` 上（`pgc_states.v6_state` 则只有 `{a,c,d,f}`）。
   * 这是真实数据的形状，也是回放唯一能真正比对到的来源。
   */
  async function seedWritePlan(v6: Record<string, unknown>, traceId = TRACE_ID) {
    await db.execute(sql`
      INSERT INTO "pgc_write_plans" ("id", "pgc_state_id", "session_id", "trace_id", "policy_version", "write_plan", "contradiction_report")
      VALUES (
        ${'pwp-1'}, ${'pgc-1'}, ${'session-1'}, ${traceId}, ${'pgc_policy_v1'},
        ${JSON.stringify([{ memoryWriteId: 'mw-1', decision: 'commit', pgcStateId: 'pgc-1', pgcStateSnapshot: { pgc_state_id: 'pgc-1', components: {}, v6 } }])}::jsonb,
        ${JSON.stringify({ severity: 'low' })}::jsonb
      )
    `)
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
    // DDL 现在由 drizzle 全量生成（不再有"只建两列"的局部 DDL），
    // 故必须按真实 schema 写入 memory_versions 的全部 NOT NULL / 外键列。
    // 回放路由只 inner join 到 memory_tx_id 来判定 trace 是否真的落库了 memory_version，
    // 因此这里只保证一张**合法**的完整行即可，内容不影响断言。
    await db.insert(schema.v9EvidencePacks).values({
      id: 'ep-1',
      sessionId: 'session-1',
      source: 'test',
    })
    await db.insert(schema.v9PgcStates).values({
      id: 'pgc-mv-1',
      sessionId: 'session-1',
      traceId: TRACE_ID,
      policyVersion: 'pgc_policy_v1',
      components: {},
      v6State: {},
    })
    await db.insert(schema.v9MemoryVersions).values({
      id: 'mv-1',
      memoryTxId: 'tx-1',
      memoryItemId: 'mi-1',
      memoryWriteId: 'mw-1',
      memoryKind: 'long_term',
      contentHashSha256: 'deadbeef',
      evidencePackId: 'ep-1',
      evidenceIds: [],
      pgcStateId: 'pgc-mv-1',
      intensity: 'normal',
      durability: 'durable',
    })
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

  // ---------------------------------------------------------------------------
  // 运行期数据形状：v6 决策快照挂在 write_plan[].pgcStateSnapshot 上，
  // 而 pgc_states.v6_state 只有 {a,c,d,f}（供下一次转移复用，**不含**门控诊断）。
  //
  // 这一组断言的存在理由：早先回放只认 pgc_states.v6_state，而运行期从不往那里写
  // tau/w_max_*/commit_reason，于是**真实事件回放永远只能报 insufficient** ——
  // 回放一致性沦为只对手工塞入的测试数据成立的断言（构造性零）。
  // ---------------------------------------------------------------------------

  it('verifies a runtime-shaped trace whose v6 snapshot lives in the write plan', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: 'S5', idempotencyKey: 'k1' })
    // 运行期的真实形状：pgc_states 只有四维状态，没有 v6 诊断。
    await seedPgcState({ a: 0.1, c: 0.1, d: 0.1, f: 0.1 })
    await seedWritePlan(v6Snapshot())

    const { status, body } = await replay()
    expect(status).toBe(200)
    expect(body.ok).toBe(true)
    expect(body.reason).toBeUndefined()
    expect(body.commitReasons).toEqual(['committed'])
    const insufficient = (body.insufficient ?? []) as Array<Record<string, unknown>>
    expect(insufficient).toHaveLength(0)
  })

  it('detects w_max drift inside the write-plan snapshot (proves that path is not vacuous)', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: 'S5', idempotencyKey: 'k1' })
    await seedPgcState({ a: 0.1, c: 0.1, d: 0.1, f: 0.1 })
    await seedWritePlan(v6Snapshot({ w_max_global: 0.999999 }))

    const { body } = await replay()
    expect(body.ok).toBe(false)
    expect(body.reason).toBe('mismatch')
    const mismatches = body.mismatches as Array<Record<string, unknown>>
    expect(mismatches.some(m => m.kind === 'w_max_global_drift')).toBe(true)
  })

  it('does not read a partial v6 snapshot as agreement (missing w_max_* is insufficient, not ok)', async () => {
    await seedEvent({ eventId: 'e1', topic: 'aijade.pgc.write_plan_ready', coreStateNode: 'S5', idempotencyKey: 'k1' })
    await seedPgcState({ a: 0.1, c: 0.1, d: 0.1, f: 0.1 })
    // 有 tau 与 s.f，但缺 w_max_* —— `Math.abs(undefined - n)` 是 NaN，NaN > eps 恒 false，
    // 若不逐字段校验，「缺字段」会静默变成「无漂移」。
    await seedWritePlan({ tau: 'episodic', s: { f: 0.1 }, commit_reason: 'committed' })

    const { body } = await replay()
    expect(body.ok).toBe(false)
    expect(body.reason).toBe('insufficient_input_snapshot')
    const insufficient = body.insufficient as Array<Record<string, unknown>>
    expect(insufficient.some(i => i.kind === 'missing_v6_snapshot')).toBe(true)
  })
})
