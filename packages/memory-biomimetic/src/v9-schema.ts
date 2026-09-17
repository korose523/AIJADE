/**
 * v9 内核的数据库行（领域）类型。
 *
 * 这是记忆写入流水线的**单一数据模型真源（TS 侧）**。物理 DDL 落在
 * `apps/server/src/schemas/memory-v9.ts`（drizzle-orm `pgTable`），二者逐表对应、
 * 字段命名保持一致；DDL 是数据库的真源，此文件是内核代码消费的真源，二者互补而非冲突。
 *
 * 注意：证据/信念的**实体类型**不在此重新定义——直接复用 `belief.ts` 的 `Belief` /
 * `EvidenceEntry`，避免两套平行真源（本项目明确反对）。
 */

import type { Belief } from './belief'
import type { RiskLevel } from './events'
import type { MemoryKind, PgcDecision, PgcReasonCode, PgcStateSnapshot } from './pgc'
import type { PgcState4 } from './pgc-state'

export interface SessionRow {
  id: string
  sessionRef: string
  createdAt: number
  updatedAt: number
  meta?: Record<string, unknown>
}

export interface AssetRow {
  id: string
  kind: string
  ownerSessionId: string
  payload: Record<string, unknown>
  createdAt: number
}

export interface EventRow {
  id: string
  /** 业务事件 id（与事件信封 event_id 对应）。 */
  eventId: string
  traceId: string
  correlationId: string
  timestamp: number
  producer: string
  topic: string
  payload: unknown
  /** 唯一约束：支撑 MemoryTx 幂等去重。 */
  idempotencyKey: string
  replayMode: 'live' | 'replay'
  riskLevel: RiskLevel
}

export interface EvidencePackRow {
  id: string
  sessionId: string
  source: string
  createdAt: number
  note?: string
}

export interface EvidenceChunkRow {
  id: string
  packId: string
  idx: number
  content: string
  createdAt: number
}

/** 直接复用 belief.ts 的 `Belief`，此处仅列出表持有形态以备映射。 */
export type BeliefRow = Belief

export interface PgcStateRow {
  id: string
  /** Session and trace make the four-dimensional state recoverable across turns. */
  sessionId: string
  traceId: string
  policyVersion: string
  /** 快照的 components（含复用的 PlasticityGate）。 */
  components: PgcStateSnapshot['components']
  /** The actual v6 endogenous state s_t; required for the next event's transition. */
  v6State: PgcState4
  createdAt: number
}

export interface PgcWritePlanRow {
  id: string
  pgcStateId: string
  sessionId: string
  traceId: string
  policyVersion: string
  writePlan: PgcWritePlanEntryRow[]
  contradictionReport: { conflictingEvidenceIds?: string[], severity: 'low' | 'high' }
  createdAt: number
}

export interface PgcWritePlanEntryRow {
  memoryWriteId: string
  decision: PgcDecision
  finalIntensity: number
  reasonCodes: PgcReasonCode[]
  expectedTests: string[]
  pgcStateId: string
}

export interface MemoryTxRow {
  id: string
  sessionId: string
  traceId: string
  atomicity: 'per_write' | 'bundle'
  maxWrites: number
  status: 'committed' | 'rejected' | 'partial'
  createdAt: number
}

/**
 * 记忆版本行。**硬约束**（v9 规范）：只由已 committed 的 memory_txs 产生，
 * 且必须带 `evidencePackId` 与 `evidenceIds` 证据链，杜绝无证据写入。
 */
export interface MemoryVersionRow {
  id: string
  memoryTxId: string
  memoryItemId: string
  memoryWriteId: string
  memoryKind: MemoryKind
  /** 内容规范化后的 sha256；回放/去重用。 */
  contentHashSha256: string
  evidencePackId: string
  evidenceIds: string[]
  pgcStateId: string
  intensity: number
  durability: number
  /** 来源 claim id（persona/belief 关联），供 EvidenceWeave 推 hypothesis_id。 */
  sourceClaimIds?: string[]
  riskLevel?: RiskLevel
  createdAt: number
}

export interface EvidenceWeaveRow {
  id: string
  txId: string
  graphHash: string
  spec: { includePgcSnapshot: boolean, includeClaimIds: boolean, includeEvolutionSpecId?: string }
  links: {
    linkId: string
    memoryVersionId: string
    evidenceIds: string[]
    pgcStateId: string
    hypothesisId?: string
  }[]
  createdAt: number
}

export interface EvolutionSpecRow {
  id: string
  name: string
  spec: Record<string, unknown>
  createdAt: number
}

export interface EvalReportRow {
  id: string
  name: string
  metric: Record<string, unknown>
  result: Record<string, unknown>
  createdAt: number
}

export interface AuditLogEntryRow {
  id: string
  txId: string
  actor: string
  action: string
  beforeHash?: string
  afterHash?: string
  at: number
}
