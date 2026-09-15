/**
 * EvidenceWeave / CausalGraph — 证据织层（v9 写入流水线的第三道、也是回放校验的落点）。
 *
 * 输入一条已提交的 `tx_id`，把其中**已落库**的 `memory_versions`（每条都自带 evidence_pack_id
 * 与证据链）织成一张因果图：
 *
 *     memory_version ──(evidence_ids)──▶ evidence
 *                    ──(pgc_state_id)──▶ PGC 状态
 *                    ──(hypothesis_id)─▶ 信念/claim
 *
 * 关键不变量：**`graph_hash` 必须确定性**——相同输入必得相同哈希，不同输入必得不同哈希。
 * 否则回放一致性校验（用 graph_hash 比对两次运行）毫无意义。哈希用 `v9-hash.graphHash`
 * （规范化 JSON → sha256），与 `memory_versions.content_hash_sha256` 同源。
 *
 * 关于「复用 evidence.ts / belief.ts 既有类型」：本织层消费的是**已落库的版本**，其
 * evidence_ids / pgc_state_id / source_claim_ids 已经是具体 id；信念实体类型（`Belief`）
 * 由证据链回指，不在此重定义。图谱的节点/边关系从 memory-tx 的提交结果派生，而不是平行
 * 再造一套 Evidence/Claim 真源。
 */

import type { RiskLevel } from './events'
import type { MemoryTxEngine } from './memory-tx'
import type { EvidenceWeaveRow } from './v9-schema'

import { evidenceWeaveCandidateReadyEvent } from './events'
import { graphHash, sha256Hex } from './v9-hash'

export interface WeaveSpec {
  /** 是否在 link 上携带 pgc_state_id（已默认携带；此处用于语义开关/审计）。 */
  include_pgc_snapshot: boolean
  /** 是否把 source_claim_ids 推成 hypothesis_id（影响图谱结构与哈希）。 */
  include_claim_ids: boolean
  include_evolution_spec_id?: string
}

export interface WeaveLink {
  linkId: string
  memoryVersionId: string
  evidenceIds: string[]
  pgcStateId: string
  hypothesisId?: string
}

export interface WeaveResult {
  weave_id: string
  tx_id: string
  links: WeaveLink[]
  graph_hash: string
  spec: WeaveSpec
}

/**
 * 构建证据织层。纯函数（除读取引擎状态外无副作用），确定性。
 */
export function buildWeave(engine: MemoryTxEngine, txId: string, spec: WeaveSpec): WeaveResult {
  const versions = engine.getVersionsForTx(txId)

  const links: WeaveLink[] = versions.map((v) => {
    const linkId = sha256Hex(`${txId}:${v.id}`).slice(0, 16)
    return {
      linkId,
      memoryVersionId: v.id,
      evidenceIds: [...v.evidenceIds],
      pgcStateId: v.pgcStateId,
      hypothesisId: spec.include_claim_ids ? v.sourceClaimIds?.[0] : undefined,
    }
  })

  // 确定性哈希：links（按 memory_version_id 排序归一） + spec 一起进图哈希。
  const graph_hash = graphHash(links, {
    include_pgc_snapshot: spec.include_pgc_snapshot,
    include_claim_ids: spec.include_claim_ids,
    include_evolution_spec_id: spec.include_evolution_spec_id,
  })
  const weaveId = sha256Hex(`${txId}:${graph_hash}`).slice(0, 16)

  return { weave_id: weaveId, tx_id: txId, links, graph_hash, spec }
}

/** 落库行形态（DB 映射）。 */
export function toWeaveRow(result: WeaveResult, createdAt = Date.now()): EvidenceWeaveRow {
  return {
    id: result.weave_id,
    txId: result.tx_id,
    graphHash: result.graph_hash,
    spec: {
      includePgcSnapshot: result.spec.include_pgc_snapshot,
      includeClaimIds: result.spec.include_claim_ids,
      includeEvolutionSpecId: result.spec.include_evolution_spec_id,
    },
    links: result.links,
    createdAt,
  }
}

/** 把织层包成 aijade.evidence.weave_candidate_ready 事件（已 zod 校验）。 */
export function buildEvidenceWeaveCandidateReadyEvent(
  result: WeaveResult,
  envelope: { event_id: string, trace_id: string, correlation_id: string, timestamp: number, producer: string, idempotency_key: string, replay_mode: 'live' | 'replay', risk_level: RiskLevel },
) {
  return evidenceWeaveCandidateReadyEvent.parse({
    ...envelope,
    topic: 'aijade.evidence.weave_candidate_ready' as const,
    payload: {
      tx_id: result.tx_id,
      weave_id: result.weave_id,
      graph_hash: result.graph_hash,
      candidate_memory_write_ids: result.links.map(l => l.memoryVersionId),
    },
  })
}
