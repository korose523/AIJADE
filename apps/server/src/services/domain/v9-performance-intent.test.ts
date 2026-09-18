import type { PerformanceIntent } from '@proj-aijade/memory-biomimetic'
import type Redis from 'ioredis'

import type { Database } from '../../libs/db'

import { PGlite } from '@electric-sql/pglite'
import { validatePerformanceIntent } from '@proj-aijade/memory-biomimetic'
import { drizzle } from 'drizzle-orm/pglite'
import { beforeEach, describe, expect, it } from 'vitest'

import { buildMemoryAndLongTermDdl } from '../../schemas/pglite-ddl'
import { createLongTermMemoryService } from './long-term-memory'
import { createV9PerformanceIntentService } from './v9-performance-intent'

import * as ltmSchema from '../../schemas/long-term-memory'
import * as v9Schema from '../../schemas/memory-v9'

const DDL = buildMemoryAndLongTermDdl()

const USER_ID = 'user-intent'
const SESSION_ID = 'session-intent'
const DEVICE_ID = 'device-intent'
const AGENT_ID = 'agent-intent'
const USER_SCOPE = 'scope-intent'

async function createDb(): Promise<Database> {
  const client = new PGlite()
  await client.exec(DDL)
  return drizzle(client, { schema: { ...ltmSchema, ...v9Schema } }) as unknown as Database
}

async function seedEvidence(db: Database, sessionId: string, chunks: { source: string, content: string }[]) {
  const packId = `pack_${sessionId}`
  await db.insert(v9Schema.v9EvidencePacks).values({ id: packId, sessionId, source: chunks[0]?.source ?? 'seed' })
  for (let i = 0; i < chunks.length; i++) {
    await db.insert(v9Schema.v9EvidenceChunks).values({ id: `chunk_${sessionId}_${i}`, packId, idx: String(i), content: chunks[i].content })
  }
}

async function countRows(db: Database, table: 'persona_snapshots' | 'performance_intents') {
  const schema = table === 'persona_snapshots' ? ltmSchema.personaSnapshots : ltmSchema.performanceIntents
  const rows = await db.select().from(schema)
  return rows.length
}

describe('v9 real PerformanceIntent derivation', () => {
  let db: Database

  beforeEach(async () => {
    db = await createDb()
  })

  it('persists a genuine, validated kernel PerformanceIntent (not a look-alike)', async () => {
    await seedEvidence(db, SESSION_ID, [
      { source: 'chat', content: 'Tell me about your research?' },
      { source: 'memory', content: 'We discussed the PGC gate last week' },
    ])

    const { snapshot, intent } = await createV9PerformanceIntentService({ db }).deriveForSession({
      userId: USER_ID,
      sessionId: SESSION_ID,
      deviceId: DEVICE_ID,
      privacyLevel: 1,
      agentId: AGENT_ID,
      userScope: USER_SCOPE,
    })

    const pi = intent.intent as unknown as PerformanceIntent

    // Core assertions: real kernel intent.
    expect(pi.schema).toBe('aijade.performance_intent@1')
    expect(pi.id).toBeTruthy()
    expect(pi.agentId).toBe(AGENT_ID)
    expect(pi.userScope).toBe(USER_SCOPE)
    expect(typeof pi.timeMarked).toBe('number')
    expect(Number.isFinite(pi.timeMarked)).toBe(true)
    expect(typeof pi.duration).toBe('number')
    expect(pi.duration).toBeGreaterThanOrEqual(0)
    expect(validatePerformanceIntent(pi).ok).toBe(true)

    // Non-tautology: it is NOT the old hand-rolled shape.
    // Old shape had no `schema` and had a `channels` field.
    expect('schema' in pi).toBe(true)
    expect((pi as unknown as Record<string, unknown>).channels).toBeUndefined()

    // personaSnapshotRef is the real snapshot id, not a fabricated string.
    expect(intent.personaSnapshotRef).toBe(snapshot.id)
    expect(pi.personaSnapshotRef).toBe(snapshot.id)
  })

  it('refuses when there is no committed evidence, and writes nothing', async () => {
    const beforeSnapshots = await countRows(db, 'persona_snapshots')
    const beforeIntents = await countRows(db, 'performance_intents')

    await expect(
      createV9PerformanceIntentService({ db }).deriveForSession({
        userId: USER_ID,
        sessionId: SESSION_ID,
        deviceId: DEVICE_ID,
        privacyLevel: 1,
        agentId: AGENT_ID,
        userScope: USER_SCOPE,
      }),
    ).rejects.toThrow()

    const afterSnapshots = await countRows(db, 'persona_snapshots')
    const afterIntents = await countRows(db, 'performance_intents')
    expect(afterSnapshots).toBe(beforeSnapshots)
    expect(afterIntents).toBe(beforeIntents)
  })

  it('produces a deterministic intent for a known dialogue act (question)', async () => {
    await seedEvidence(db, SESSION_ID, [{ source: 'chat', content: 'Why does the sky look blue?' }])
    const { intent } = await createV9PerformanceIntentService({ db }).deriveForSession({
      userId: USER_ID,
      sessionId: SESSION_ID,
      deviceId: DEVICE_ID,
      privacyLevel: 2,
      agentId: AGENT_ID,
      userScope: USER_SCOPE,
    })
    const pi = intent.intent as unknown as PerformanceIntent
    expect(validatePerformanceIntent(pi).ok).toBe(true)
    expect(pi.schema).toBe('aijade.performance_intent@1')
  })

  it('generatePersonaFromMemory now yields a real PerformanceIntent', async () => {
    await seedEvidence(db, SESSION_ID, [{ source: 'memory', content: 'Remember we celebrated the release!' }])

    const redisStub = { lpush: async () => 0, brpop: async () => undefined } as unknown as Redis
    const svc = createLongTermMemoryService(db, redisStub)

    const { snapshot, intent } = await svc.generatePersonaFromMemory(USER_ID, {
      sessionId: SESSION_ID,
      deviceId: DEVICE_ID,
      privacyLevel: 1,
      agentId: AGENT_ID,
      userScope: USER_SCOPE,
    })

    const pi = intent.intent as unknown as PerformanceIntent
    expect(pi.schema).toBe('aijade.performance_intent@1')
    expect(validatePerformanceIntent(pi).ok).toBe(true)
    expect(intent.personaSnapshotRef).toBe(snapshot.id)
  })
})
