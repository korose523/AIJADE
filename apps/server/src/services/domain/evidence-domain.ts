import type { Database } from '../../libs/db'

import { eq, inArray } from 'drizzle-orm'

import * as schema from '../../schemas/memory-v9'

/**
 * 证据织层 —— 独立的「证据态引用域」查询与一致性校验。
 *
 * 对应架构文档 §10.3「提供可查询的证据态引用域（供 Research Core 校验）」与复核报告
 * R3 / 核对项 3.2。此前引用域一致性仅由 `evidence_weaves.graph_hash` **隐式**保证；
 * 本模块把它显式化为可独立调用的两个能力：
 *
 * 1. {@link EvidenceDomainService.getEvidenceDomain}：把一个会话的证据态投影成
 *    **可查询的引用域快照**——证据包 / 证据块 / Belief（即文档 `BeliefClaim` 的实名
 *    实现，见架构文档 §9.1 实名映射注）/ 记忆版本 / 织图哈希的 id 全集。
 * 2. {@link EvidenceDomainService.verifyEvidenceRefs}：**纯函数**校验一组引用是否
 *    全部落在引用域内（引用域一致性）。Research Core / 审计侧据此可在不重算
 *    `graph_hash` 的情况下独立回答"这批引用是否都真实存在、属于本会话的证据态"。
 *
 * 设计约束：
 * - 查询按 `session_id` 限定（证据包、tx→版本/织图链都挂在会话上）；`beliefs` 表无
 *   会话列（以 `scope`/`owner` 承载作用域），故 belief id 取全量现行集——自托管单用户
 *   companion 语义下即"该 companion 的信念域"。
 * - `verifyEvidenceRefs` 是纯函数（无 IO、确定性），单测不需要数据库。
 * - 宁缺勿伪造：`missing` 非空即 `ok: false`，调用方不得把悬空引用当作已锚定证据。
 */

/** 一个会话证据态的可查询引用域快照。 */
export interface EvidenceDomainSnapshot {
  sessionId: string
  /** 证据包 id 全集（引用域的根锚）。 */
  evidencePackIds: string[]
  /** 证据块 id 全集（`evidence_refs` 最常指向的粒度）。 */
  evidenceChunkIds: string[]
  /** Belief（实名实现 `beliefs` 表）id 全集。 */
  beliefIds: string[]
  /** 记忆版本 id 全集（会话内，经 memory_txs 归属）。 */
  memoryVersionIds: string[]
  /** 织图哈希全集（`evidence_weaves.graph_hash`，会话内）。 */
  graphHashes: string[]
}

/** 纯校验结果：`missing` 非空 ⇒ `ok: false`（宁缺勿伪造）。 */
export interface EvidenceRefVerification {
  ok: boolean
  missing: string[]
}

export interface EvidenceDomainService {
  getEvidenceDomain: (sessionId: string) => Promise<EvidenceDomainSnapshot>
  verifyEvidenceRefs: (refs: readonly string[], domain: EvidenceDomainSnapshot) => EvidenceRefVerification
}

/** 纯函数：判定一组引用是否全部落在引用域快照内（导出以便无库单测）。 */
export function verifyEvidenceRefsPure(
  refs: readonly string[],
  domain: EvidenceDomainSnapshot,
): EvidenceRefVerification {
  const known = new Set<string>([
    ...domain.evidencePackIds,
    ...domain.evidenceChunkIds,
    ...domain.beliefIds,
    ...domain.memoryVersionIds,
    ...domain.graphHashes,
  ])
  const missing = [...new Set(refs)].filter(ref => !known.has(ref))
  return { ok: missing.length === 0, missing }
}

export function createEvidenceDomainService(db: Database): EvidenceDomainService {
  return {
    async getEvidenceDomain(sessionId: string): Promise<EvidenceDomainSnapshot> {
      const packs = await db.select({ id: schema.v9EvidencePacks.id })
        .from(schema.v9EvidencePacks)
        .where(eq(schema.v9EvidencePacks.sessionId, sessionId))
      const packIds = packs.map(p => p.id)

      // 证据块按包归属会话；空会话时避免 `inArray([])` 的空集语义问题。
      const chunkRows = packIds.length === 0
        ? []
        : await db.select({ id: schema.v9EvidenceChunks.id })
            .from(schema.v9EvidenceChunks)
            .where(inArray(schema.v9EvidenceChunks.packId, packIds))

      const beliefRows = await db.select({ id: schema.v9Beliefs.id })
        .from(schema.v9Beliefs)

      // 会话内的 tx → 版本 / 织图（引用域的因果侧）。
      const versionRows = await db.select({ id: schema.v9MemoryVersions.id })
        .from(schema.v9MemoryVersions)
        .innerJoin(schema.v9MemoryTxs, eq(schema.v9MemoryVersions.memoryTxId, schema.v9MemoryTxs.id))
        .where(eq(schema.v9MemoryTxs.sessionId, sessionId))

      const weaveRows = await db.select({ graphHash: schema.v9EvidenceWeaves.graphHash })
        .from(schema.v9EvidenceWeaves)
        .innerJoin(schema.v9MemoryTxs, eq(schema.v9EvidenceWeaves.txId, schema.v9MemoryTxs.id))
        .where(eq(schema.v9MemoryTxs.sessionId, sessionId))

      return {
        sessionId,
        evidencePackIds: packIds,
        evidenceChunkIds: chunkRows.map(c => c.id),
        beliefIds: beliefRows.map(b => b.id),
        memoryVersionIds: versionRows.map(v => v.id),
        graphHashes: weaveRows.map(w => w.graphHash),
      }
    },
    verifyEvidenceRefs: (refs, domain) => verifyEvidenceRefsPure(refs, domain),
  }
}
