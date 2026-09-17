import { integer, jsonb, pgTable, real, text, timestamp } from 'drizzle-orm/pg-core'

import { nanoid } from '../utils/id'

export const personaSnapshots = pgTable('persona_snapshots', {
  id: text('id').primaryKey().$defaultFn(() => nanoid()),
  userId: text('user_id').notNull(),
  deviceId: text('device_id').notNull(),
  privacyLevel: integer('privacy_level').notNull(),
  persona: jsonb('persona').notNull(),
  version: integer('version').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
})

export const performanceIntents = pgTable('performance_intents', {
  id: text('id').primaryKey().$defaultFn(() => nanoid()),
  userId: text('user_id').notNull(),
  deviceId: text('device_id').notNull(),
  personaSnapshotRef: text('persona_snapshot_ref').notNull(),
  privacyLevel: integer('privacy_level').notNull(),
  intent: jsonb('intent').notNull(),
  timeMarked: timestamp('time_marked').notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
})

export const memorySyncOutbox = pgTable('memory_sync_outbox', {
  id: text('id').primaryKey().$defaultFn(() => nanoid()),
  userId: text('user_id').notNull(),
  sourceDeviceId: text('source_device_id').notNull(),
  entityType: text('entity_type').notNull(),
  entityId: text('entity_id').notNull(),
  privacyLevel: integer('privacy_level').notNull(),
  payload: jsonb('payload').notNull(),
  status: text('status').notNull().default('pending'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  processedAt: timestamp('processed_at'),
})

export const sharingNotifications = pgTable('sharing_notifications', {
  id: text('id').primaryKey().$defaultFn(() => nanoid()),
  userId: text('user_id').notNull(),
  candidateId: text('candidate_id').notNull(),
  channel: text('channel').notNull(),
  contentRef: text('content_ref').notNull(),
  score: real('score').notNull(),
  privacyLevel: integer('privacy_level').notNull(),
  status: text('status').notNull().default('pending'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  deliveredAt: timestamp('delivered_at'),
})
