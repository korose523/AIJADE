import type Redis from 'ioredis'

import type { Database } from '../../libs/db'

import { desc, eq } from 'drizzle-orm'

import { nanoid } from '../../utils/id'
import { createV9PerformanceIntentService } from './v9-performance-intent'

import * as schema from '../../schemas/long-term-memory'

export const LONG_TERM_MEMORY_QUEUE = 'aijade:memory:sync'
export type PrivacyLevel = 0 | 1 | 2 | 3
export type MemoryJob
  = | { kind: 'sync', outboxId: string }
    | { kind: 'share', notificationId: string }

export interface PersonaSnapshotInput {
  id?: string
  deviceId: string
  privacyLevel: PrivacyLevel
  persona: Record<string, unknown>
  version: number
}

export interface PerformanceIntentInput {
  id?: string
  deviceId: string
  privacyLevel: PrivacyLevel
  personaSnapshotRef: string
  intent: Record<string, unknown>
  timeMarked: number
}

export function enqueueMemoryJob(redis: Redis, job: MemoryJob) {
  return redis.lpush(LONG_TERM_MEMORY_QUEUE, JSON.stringify(job))
}

export async function dequeueMemoryJob(redis: Redis): Promise<MemoryJob | undefined> {
  const result = await redis.brpop(LONG_TERM_MEMORY_QUEUE, 5)
  if (!result)
    return undefined
  const value: unknown = JSON.parse(result[1])
  if (!value || typeof value !== 'object' || !('kind' in value))
    throw new Error('invalid long-term memory job')
  return value as MemoryJob
}

function assertPrivacy(level: number): asserts level is PrivacyLevel {
  if (!Number.isInteger(level) || level < 0 || level > 3)
    throw new Error('privacyLevel must be an integer from 0 to 3')
}

export function createLongTermMemoryService(db: Database, redis: Redis) {
  const service = {
    async savePersonaSnapshot(userId: string, input: PersonaSnapshotInput) {
      assertPrivacy(input.privacyLevel)
      const id = input.id ?? nanoid()
      const [snapshot] = await db.insert(schema.personaSnapshots).values({
        id,
        userId,
        deviceId: input.deviceId,
        privacyLevel: input.privacyLevel,
        persona: input.persona,
        version: input.version,
      }).returning()
      const [outbox] = await db.insert(schema.memorySyncOutbox).values({
        userId,
        sourceDeviceId: input.deviceId,
        entityType: 'persona_snapshot',
        entityId: id,
        privacyLevel: input.privacyLevel,
        payload: snapshot,
      }).returning()
      await enqueueMemoryJob(redis, { kind: 'sync', outboxId: outbox.id })
      return snapshot
    },
    async savePerformanceIntent(userId: string, input: PerformanceIntentInput) {
      assertPrivacy(input.privacyLevel)
      if (!input.personaSnapshotRef)
        throw new Error('personaSnapshotRef is required')
      const id = input.id ?? nanoid()
      const [intent] = await db.insert(schema.performanceIntents).values({
        id,
        userId,
        deviceId: input.deviceId,
        personaSnapshotRef: input.personaSnapshotRef,
        privacyLevel: input.privacyLevel,
        intent: input.intent,
        timeMarked: new Date(input.timeMarked),
      }).returning()
      const [outbox] = await db.insert(schema.memorySyncOutbox).values({
        userId,
        sourceDeviceId: input.deviceId,
        entityType: 'performance_intent',
        entityId: id,
        privacyLevel: input.privacyLevel,
        payload: intent,
      }).returning()
      await enqueueMemoryJob(redis, { kind: 'sync', outboxId: outbox.id })
      return intent
    },
    async generatePersonaFromMemory(userId: string, input: {
      sessionId: string
      deviceId: string
      privacyLevel: PrivacyLevel
      /** Agent identity for the derived intent (kernel-required; added when the method was rewired to the real director). */
      agentId: string
      /** User scope for the derived intent (kernel-required; added when the method was rewired to the real director). */
      userScope: string
    }) {
      // Rewired to the real kernel path: `deriveForSession` runs the genuine
      // `PerformanceDirector` and persists a validated `PerformanceIntent`
      // (schema 'aijade.performance_intent@1'). The previous hand-rolled,
      // unvalidated look-alike structure has been removed. `agentId`/`userScope`
      // are now required because the kernel mandates them on every intent.
      return createV9PerformanceIntentService({ db }).deriveForSession({
        userId,
        sessionId: input.sessionId,
        deviceId: input.deviceId,
        privacyLevel: input.privacyLevel,
        agentId: input.agentId,
        userScope: input.userScope,
      })
    },
    async pullForDevice(userId: string, deviceId: string) {
      const rows = await db.select().from(schema.memorySyncOutbox).where(eq(schema.memorySyncOutbox.userId, userId)).orderBy(desc(schema.memorySyncOutbox.createdAt))
      return rows.filter(row => row.sourceDeviceId !== deviceId && row.privacyLevel >= 2)
    },
    async processSync(outboxId: string) {
      await db.update(schema.memorySyncOutbox).set({ status: 'processed', processedAt: new Date() }).where(eq(schema.memorySyncOutbox.id, outboxId))
    },
    async queueShareNotification(userId: string, candidate: { id: string, channel: string, contentRef: string, score: number, privacyLevel: PrivacyLevel }) {
      assertPrivacy(candidate.privacyLevel)
      const [notification] = await db.insert(schema.sharingNotifications).values({
        userId,
        candidateId: candidate.id,
        channel: candidate.channel,
        contentRef: candidate.contentRef,
        score: candidate.score,
        privacyLevel: candidate.privacyLevel,
      }).returning()
      await enqueueMemoryJob(redis, { kind: 'share', notificationId: notification.id })
      return notification
    },
    async processShare(notificationId: string) {
      await db.update(schema.sharingNotifications).set({ status: 'delivered', deliveredAt: new Date() }).where(eq(schema.sharingNotifications.id, notificationId))
    },
    async listNotifications(userId: string) {
      return db.select().from(schema.sharingNotifications).where(eq(schema.sharingNotifications.userId, userId)).orderBy(desc(schema.sharingNotifications.createdAt))
    },
  }
  return service
}

export type LongTermMemoryService = ReturnType<typeof createLongTermMemoryService>
