import type { PerformanceIntent } from '@proj-aijade/memory-biomimetic'

import type { Database } from '../../libs/db'
import type { HonoEnv } from '../../types/hono'

import { PGlite } from '@electric-sql/pglite'
import { drizzle } from 'drizzle-orm/pglite'
import { Hono } from 'hono'
import { beforeEach, describe, expect, it } from 'vitest'

import { buildMemoryAndLongTermDdl } from '../../schemas/pglite-ddl'
import { ApiError } from '../../utils/error'
import { createV9PersonaRoutes } from './persona'

import * as ltmSchema from '../../schemas/long-term-memory'
import * as v9Schema from '../../schemas/memory-v9'

const DDL = buildMemoryAndLongTermDdl()

const SESSION_ID = 'session-route'
const DEVICE_ID = 'device-route'
const AGENT_ID = 'agent-route'
const USER_SCOPE = 'scope-route'
const USER_ID = 'user-route'

async function createDb(): Promise<Database> {
  const client = new PGlite()
  await client.exec(DDL)
  return drizzle(client, { schema: { ...ltmSchema, ...v9Schema } }) as unknown as Database
}

/** Authed app: injects a user so authGuard passes. */
function makeApp(db: Database): Hono<HonoEnv> {
  return new Hono<HonoEnv>()
    .use('*', async (c, next) => {
      c.set('user', { id: USER_ID } as never)
      await next()
    })
    .onError((err, c) => {
      if (err instanceof ApiError)
        return c.json({ error: err.errorCode, message: err.message, details: err.details }, err.statusCode)
      return c.json({ error: 'INTERNAL_SERVER_ERROR', message: 'Internal Server Error' }, 500)
    })
    .route('/api/v1/v9/persona/derive', createV9PersonaRoutes({ db }))
}

/** Unauthed app: authGuard-equivalent that rejects with 401. */
function makeUnauthApp(db: Database): Hono<HonoEnv> {
  return new Hono<HonoEnv>()
    .use('*', async () => {
      throw new ApiError(401, 'UNAUTHORIZED', 'Unauthorized')
    })
    .onError((err, c) => {
      if (err instanceof ApiError)
        return c.json({ error: err.errorCode, message: err.message }, err.statusCode)
      return c.json({ error: 'INTERNAL_SERVER_ERROR' }, 500)
    })
    .route('/api/v1/v9/persona/derive', createV9PersonaRoutes({ db }))
}

describe('pOST /api/v1/v9/persona/derive', () => {
  let db: Database

  beforeEach(async () => {
    db = await createDb()
  })

  async function seedEvidence(db: Database, chunks: { source: string, content: string }[]) {
    const packId = `pack_${SESSION_ID}`
    await db.insert(v9Schema.v9EvidencePacks).values({ id: packId, sessionId: SESSION_ID, source: chunks[0]?.source ?? 'seed' })
    for (let i = 0; i < chunks.length; i++)
      await db.insert(v9Schema.v9EvidenceChunks).values({ id: `chunk_${SESSION_ID}_${i}`, packId, idx: String(i), content: chunks[i].content })
  }

  it('returns 200 with a real PerformanceIntent for a valid request', async () => {
    await seedEvidence(db, [{ source: 'chat', content: 'What do you think about this?' }])

    const res = await makeApp(db).request('/api/v1/v9/persona/derive', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: SESSION_ID,
        device_id: DEVICE_ID,
        agent_id: AGENT_ID,
        user_scope: USER_SCOPE,
        privacy_level: 1,
      }),
    })
    expect(res.status).toBe(200)
    const body = await res.json() as Record<string, unknown>
    expect(body.persona_snapshot_ref).toBeTruthy()
    expect(body.intent_ref).toBeTruthy()
    const intent = body.intent as unknown as PerformanceIntent
    expect(intent.schema).toBe('aijade.performance_intent@1')
    expect(intent.personaSnapshotRef).toBe(body.persona_snapshot_ref)
  })

  it('returns 400 for an unknown extra field (strict schema) and writes nothing', async () => {
    await seedEvidence(db, [{ source: 'chat', content: 'hello' }])
    const before = (await db.select().from(ltmSchema.performanceIntents)).length

    const res = await makeApp(db).request('/api/v1/v9/persona/derive', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: SESSION_ID,
        device_id: DEVICE_ID,
        agent_id: AGENT_ID,
        user_scope: USER_SCOPE,
        privacy_level: 1,
        surprise: 'nope',
      }),
    })
    expect(res.status).toBe(400)
    const after = (await db.select().from(ltmSchema.performanceIntents)).length
    expect(after).toBe(before)
  })

  it('returns 400 for an empty session_id', async () => {
    const res = await makeApp(db).request('/api/v1/v9/persona/derive', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: '',
        device_id: DEVICE_ID,
        agent_id: AGENT_ID,
        user_scope: USER_SCOPE,
        privacy_level: 1,
      }),
    })
    expect(res.status).toBe(400)
  })

  it('returns 422 when the session has no committed evidence', async () => {
    const res = await makeApp(db).request('/api/v1/v9/persona/derive', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: SESSION_ID,
        device_id: DEVICE_ID,
        agent_id: AGENT_ID,
        user_scope: USER_SCOPE,
        privacy_level: 1,
      }),
    })
    expect(res.status).toBe(422)
    const body = await res.json() as Record<string, unknown>
    expect(body.error).toBe('NO_EVIDENCE')
  })

  it('returns 401 when unauthenticated', async () => {
    const res = await makeUnauthApp(db).request('/api/v1/v9/persona/derive', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        session_id: SESSION_ID,
        device_id: DEVICE_ID,
        agent_id: AGENT_ID,
        user_scope: USER_SCOPE,
        privacy_level: 1,
      }),
    })
    expect(res.status).toBe(401)
  })
})
