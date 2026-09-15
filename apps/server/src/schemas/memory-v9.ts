/**
 * v9 记忆写入流水线的数据库表（DDL）。
 *
 * 落点：项目既有的 drizzle-orm schema 机制（`apps/server/src/schemas/`，由
 * `server-schema` 的虚拟迁移插件扫描生成 SQL）。**不**另起一套 schema 机制。
 *
 * 与 `packages/memory-biomimetic/src/v9-schema.ts` 的 TS 领域类型逐表对应、命名一致；
 * DDL 是数据库真源，TS 类型是内核消费真源，二者互补。
 *
 * 硬约束体现：
 * - `events.idempotency_key` → 唯一约束（支撑 MemoryTx 幂等去重）。
 * - `memory_versions.content_hash_sha256` → 非空（回放/去重）。
 * - `memory_versions.evidence_pack_id` / `evidence_ids` → 非空（无证据写入禁止落库）。
 * - `memory_versions.memory_tx_id` → 引用 `memory_txs`（版本只由已提交事务产生）。
 */

import { jsonb, pgTable, text, timestamp } from 'drizzle-orm/pg-core'

import { nanoid } from '../utils/id'

// sessions -------------------------------------------------------------------
export const v9Sessions = pgTable(
  'sessions',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    sessionRef: text('session_ref').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
    updatedAt: timestamp('updated_at').defaultNow().notNull(),
    meta: jsonb('meta'),
  },
)

export const v9Assets = pgTable(
  'assets',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    kind: text('kind').notNull(),
    ownerSessionId: text('owner_session_id').references(() => v9Sessions.id, { onDelete: 'cascade' }),
    payload: jsonb('payload').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

// events（统一事件总线；idempotency_key 唯一）--------------------------------
export const v9Events = pgTable(
  'events',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    eventId: text('event_id').notNull(),
    traceId: text('trace_id').notNull(),
    correlationId: text('correlation_id').notNull(),
    timestamp: timestamp('timestamp').notNull(),
    producer: text('producer').notNull(),
    topic: text('topic').notNull(),
    payload: jsonb('payload'),
    /**
     * 唯一约束：同一幂等键只接受一次写入。MemoryTx 以 `tx_id` 作为本键，
     * 保证「同一 tx 重复提交幂等」。
     */
    idempotencyKey: text('idempotency_key').notNull().unique(),
    replayMode: text('replay_mode', { enum: ['live', 'replay'] }).notNull(),
    riskLevel: text('risk_level', { enum: ['low', 'medium', 'high'] }).notNull(),
  },
)

// evidence_packs / evidence_chunks -------------------------------------------
export const v9EvidencePacks = pgTable(
  'evidence_packs',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    sessionId: text('session_id').notNull(),
    source: text('source').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
    note: text('note'),
  },
)

export const v9EvidenceChunks = pgTable(
  'evidence_chunks',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    packId: text('pack_id').notNull().references(() => v9EvidencePacks.id, { onDelete: 'cascade' }),
    idx: text('idx').notNull(),
    content: text('content').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

// beliefs（镜像 belief.ts 的 Belief 实体，直接复用既有类型定义）------------
export const v9Beliefs = pgTable(
  'beliefs',
  {
    id: text('id').primaryKey(),
    proposition: text('proposition').notNull(),
    scope: text('scope').notNull(),
    confidence: text('confidence').notNull(), // 存为字符串以保留精度，读取时解析
    logit: text('logit').notNull(),
    status: text('status', { enum: ['hypothesis', 'accepted', 'contested', 'retracted'] }).notNull(),
    owner: text('owner', { enum: ['user', 'agent', 'world'] }).notNull(),
    evidenceIds: text('evidence_ids').array().notNull().default([]),
    counterEvidenceIds: text('counter_evidence_ids').array().notNull().default([]),
    validFrom: timestamp('valid_from').notNull(),
    validTo: timestamp('valid_to'),
    createdAt: timestamp('created_at').defaultNow().notNull(),
    updatedAt: timestamp('updated_at').defaultNow().notNull(),
  },
)

// pgc_states / pgc_write_plans -----------------------------------------------
export const v9PgcStates = pgTable(
  'pgc_states',
  {
    id: text('id').primaryKey(),
    policyVersion: text('policy_version').notNull(),
    components: jsonb('components').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

export const v9PgcWritePlans = pgTable(
  'pgc_write_plans',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    pgcStateId: text('pgc_state_id').notNull().references(() => v9PgcStates.id, { onDelete: 'cascade' }),
    sessionId: text('session_id').notNull(),
    traceId: text('trace_id').notNull(),
    policyVersion: text('policy_version').notNull(),
    writePlan: jsonb('write_plan').notNull(),
    contradictionReport: jsonb('contradiction_report').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

// memory_txs / memory_versions -----------------------------------------------
export const v9MemoryTxs = pgTable(
  'memory_txs',
  {
    id: text('id').primaryKey(),
    sessionId: text('session_id').notNull(),
    traceId: text('trace_id').notNull(),
    atomicity: text('atomicity', { enum: ['per_write', 'bundle'] }).notNull(),
    maxWrites: text('max_writes').notNull(),
    status: text('status', { enum: ['committed', 'rejected', 'partial'] }).notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

export const v9MemoryVersions = pgTable(
  'memory_versions',
  {
    id: text('id').primaryKey(),
    memoryTxId: text('memory_tx_id').notNull().references(() => v9MemoryTxs.id, { onDelete: 'cascade' }),
    memoryItemId: text('memory_item_id').notNull(),
    memoryWriteId: text('memory_write_id').notNull(),
    memoryKind: text('memory_kind', { enum: ['long_term', 'persona', 'skill', 'episodic', 'knowledge_card'] }).notNull(),
    /** 内容规范化后的 sha256（回放/去重）。非空。 */
    contentHashSha256: text('content_hash_sha256').notNull(),
    evidencePackId: text('evidence_pack_id').notNull(),
    evidenceIds: text('evidence_ids').array().notNull(),
    pgcStateId: text('pgc_state_id').notNull(),
    intensity: text('intensity').notNull(),
    durability: text('durability').notNull(),
    riskLevel: text('risk_level', { enum: ['low', 'medium', 'high'] }),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

// evidence_weaves / evolution_specs / eval_reports / audit_log --------------
export const v9EvidenceWeaves = pgTable(
  'evidence_weaves',
  {
    id: text('id').primaryKey(),
    txId: text('tx_id').notNull(),
    graphHash: text('graph_hash').notNull(),
    spec: jsonb('spec').notNull(),
    links: jsonb('links').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

export const v9EvolutionSpecs = pgTable(
  'evolution_specs',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    name: text('name').notNull(),
    spec: jsonb('spec').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

export const v9EvalReports = pgTable(
  'eval_reports',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    name: text('name').notNull(),
    metric: jsonb('metric').notNull(),
    result: jsonb('result').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
  },
)

export const v9AuditLogEntries = pgTable(
  'audit_log_entries',
  {
    id: text('id').primaryKey(),
    txId: text('tx_id').notNull(),
    actor: text('actor').notNull(),
    action: text('action').notNull(),
    beforeHash: text('before_hash'),
    afterHash: text('after_hash'),
    at: timestamp('at').notNull(),
  },
)
