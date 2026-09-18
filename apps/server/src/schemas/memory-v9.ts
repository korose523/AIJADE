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

import { sql } from 'drizzle-orm'
import { check, integer, jsonb, pgTable, real, text, timestamp } from 'drizzle-orm/pg-core'

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
    originDevice: text('origin_device').notNull(),
    privacyLevel: integer('privacy_level').notNull(),
    evidenceRefs: text('evidence_refs').array().notNull().default([]),
    causalContextRefs: text('causal_context_refs').array().notNull().default([]),
    riskScore: real('risk_score').notNull().default(0),
    topic: text('topic').notNull(),
    payload: jsonb('payload'),
    /**
     * 唯一约束：同一幂等键只接受一次写入。MemoryTx 以 `tx_id` 作为本键，
     * 保证「同一 tx 重复提交幂等」。
     */
    idempotencyKey: text('idempotency_key').notNull().unique(),
    replayMode: text('replay_mode', { enum: ['live', 'replay'] }).notNull(),
    riskLevel: text('risk_level', { enum: ['low', 'medium', 'high'] }).notNull(),
    /** v10 protocol fields; nullable while v9 producers migrate. */
    tick: integer('tick'),
    causality: jsonb('causality').$type<{ inputHash: string }>(),
    /** v10 内生状态节点（S0..S8）；nullable 兼容未打标的旧行。 */
    coreStateNode: text('core_state_node'),
  },
)

// render traces projection --------------------------------------------------
export const v9RenderTraces = pgTable(
  'render_traces',
  {
    id: text('id').primaryKey().$defaultFn(() => nanoid()),
    sessionId: text('session_id').notNull(),
    traceId: text('trace_id').notNull(),
    correlationId: text('correlation_id').notNull(),
    eventId: text('event_id').notNull(),
    personaSnapshotRef: text('persona_snapshot_ref'),
    intentRef: text('intent_ref'),
    renderRef: text('render_ref'),
    appliedParamsHash: text('applied_params_hash'),
    assetVersionHash: text('asset_version_hash'),
    /**
     * v10 §6.2 / 报告 P1-2：来自 `lpm.render_ready` 的事件 id（审计/回放定位）。
     * 可为空 —— 投影行可能先由 `persona.render_requested` 建立（那时还没有回执事件）。
     */
    renderReadyEventId: text('render_ready_event_id'),
    /**
     * v10 §6.2 / 报告 P1-2：来自 `persona.render_requested` 的事件 id。
     * 可为空 —— 投影行可能先由 `lpm.render_ready` 建立（那时还没有请求事件）。
     */
    personaRenderRequestedEventId: text('persona_render_requested_event_id'),
    /**
     * v10 §6.2 / 报告 P1-2：投影完成标记 —— 这是"缺配检测"的关键状态位。
     * - `paired`：请求 (`intent_ref`) 与回执 (`render_ref`) 齐备，身份链完整。
     * - `partial`：只收到一端，存在配对缺口（论文可见，而非埋成正常数据）。
     * 该列由投影写入逻辑**显式计算**，故可 NOT NULL；旧行的 NOT NULL 约束由迁移
     * 0024 以 `DEFAULT 'partial'` 落地（见 `drizzle/0024_*.sql`）。
     */
    projectionStatus: text('projection_status').notNull(),
    createdAt: timestamp('created_at').defaultNow().notNull(),
    updatedAt: timestamp('updated_at').defaultNow().notNull(),
  },
  // v10 §6.2 / 报告 R4（两步走 · 第一步）：两阶段身份不变量。
  //
  // 投影行由两端事件「任意一端先到」即建立（persona.render_requested 只带 intent_ref；
  // lpm.render_ready 只带回执三件套且 asset_version_hash 契约上可选），因此
  // intent_ref / applied_params_hash / asset_version_hash **不能**简单收紧为 NOT NULL ——
  // 那会同时破坏内核 payload 契约（render_ready 的 asset_version_hash 可省略）
  // 与「partial 配对缺口论文可见」的设计。真正可数据库化强制的不变量是：
  //   ① 每行至少携带一端身份（不允许两端皆空的无主行）；
  //   ② 有回执端（render_ref）必有内容指纹（applied_params_hash）——
  //      契约上 render_ready 的 applied_params_hash 为 `.min(1)` 必填，两者不可分割。
  // 迁移侧（drizzle/0025）以 NOT VALID 落地：不扫存量行（回填完成前服务器照常启动），
  // 但对**新写入**自约束生效起即强制；存量行合规性由回填后的 VALIDATE CONSTRAINT 确认。
  () => [
    check(
      'render_traces_identity_phase_check',
      sql`("intent_ref" IS NOT NULL OR "render_ref" IS NOT NULL) AND ("render_ref" IS NULL OR "applied_params_hash" IS NOT NULL)`,
    ),
  ],
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
    sessionId: text('session_id').notNull(),
    traceId: text('trace_id').notNull(),
    policyVersion: text('policy_version').notNull(),
    components: jsonb('components').notNull(),
    v6State: jsonb('v6_state').notNull(),
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
    evidencePackId: text('evidence_pack_id').notNull().references(() => v9EvidencePacks.id, { onDelete: 'restrict' }),
    evidenceIds: text('evidence_ids').array().notNull(),
    pgcStateId: text('pgc_state_id').notNull().references(() => v9PgcStates.id, { onDelete: 'restrict' }),
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
    txId: text('tx_id').notNull().references(() => v9MemoryTxs.id, { onDelete: 'cascade' }),
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
