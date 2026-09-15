/**
 * MemoryTx — 受控写入事务（v9 写入流水线的第二道闸）。
 *
 * ## 硬约束（v9 规范明确要求，本文件用类型 + 运行时双重钉死）
 *
 * 1. `memory_versions` **只**由已 committed 的 `memory_txs` 产生——本引擎里，版本对象
 *    只能在 `commit()` 的「已通过证据校验的提交集」分支被创建；其余任何路径都不产生版本。
 * 2. 每条 `memory_version` **必须带 `evidence_pack_id` 与 `evidence_ids` 证据链**。
 *    `commit()` 在落库前逐一校验：「无 evidence_pack_id **或** 证据链为空」的候选直接被
 *    `reject`（reason=`no_evidence`），**绝不**产生版本。运行时 `assertEvidenceChain()`
 *    作为双保险：即便有人绕过分类逻辑也抛错。
 * 3. 幂等：`tx_id` 即幂等键。同一 `tx_id` 重复提交返回首次结果，不产生重复版本。
 *
 * ## 复用既有代码（不得重复实现）
 * - `gating.ts` 的 `durability`：提交时按内容显著性计算记忆耐久系数（写入门控的数学原语）。
 * - `events.ts` 的 zod schema：提交成功包成 `aijade.memory_tx.committed` 事件并校验。
 * - `pgc.ts` 的 `PgcWritePlanEntry`：输入直接消费 PGC 的 write_plan，不重定义决策类型。
 */

import type { AijadeEvent, RiskLevel } from './events'
import type { MemoryKind, PgcWritePlanEntry } from './pgc'
import type { GatingCoefficients } from './types'
import type {
  AuditLogEntryRow,
  MemoryTxRow,
  MemoryVersionRow,
} from './v9-schema'

import { memoryTxCommittedEvent } from './events'
import { durability } from './gating'
import { NO_GATING } from './types'
import { contentHash } from './v9-hash'

// ============================================================================
// 输入类型
// ============================================================================

export interface MemoryPayloadAttributes {
  tags: string[]
  source_claim_ids: string[]
  risk_level?: RiskLevel
  /** 可选内容显著性，供 `gating.durability` 计算耐久系数。 */
  salience?: { salience: number, socialSalience: number, novelty: number }
}

export interface MemoryPayload {
  memory_write_id: string
  normalized_payload: {
    memory_kind: MemoryKind
    content_object: unknown
    embedding_input_text?: string
    attributes: MemoryPayloadAttributes
  }
  /** 证据包 id（硬约束：每条版本必须携带）。 */
  evidence_pack_id: string
  /** 证据链（硬约束：非空）。 */
  evidence_ids: string[]
  provenance: { source: string, actor: string, [k: string]: unknown }
}

export interface TxPolicy {
  atomicity: 'per_write' | 'bundle'
  max_writes: number
}

export interface MemoryTxInput {
  session_id: string
  trace_id: string
  /** PGC 产出的 write_plan（每项对应一个 memory_write_id）。 */
  pgc_write_plan: PgcWritePlanEntry[]
  memory_payloads: MemoryPayload[]
  tx_policy: TxPolicy
  /** 幂等键；缺省用 trace_id+session_id 推导（同一 tx 重复提交幂等）。 */
  tx_id?: string
}

// ============================================================================
// 输出类型
// ============================================================================

export interface CommittedMemory {
  memory_item_id: string
  memory_version_id: string
  memory_write_id: string
}

export interface ThrottledMemory {
  memory_write_id: string
  decision: 'throttle' | 'defer'
}

export interface RejectedMemory {
  memory_write_id: string
  decision: 'reject'
  reason: string
}

export interface TxResult {
  tx_id: string
  status: 'committed' | 'rejected' | 'partial'
  committed: CommittedMemory[]
  throttled: ThrottledMemory[]
  rejected: RejectedMemory[]
  audit_log: { events: AuditLogEntryRow[] }
  /** 由本次提交产生的事件（已通过 zod 校验）——支撑流水线串联与审计。 */
  events: AijadeEvent[]
}

// ============================================================================
// 引擎
// ============================================================================

function makeId(prefix: string, ...parts: string[]): string {
  return [prefix, ...parts].join('_')
}

/** 双保险：任何试图在证据链缺失时造版本都会在这里抛错。 */
function assertEvidenceChain(packId: string, evidenceIds: string[]): void {
  if (!packId || packId.length === 0)
    throw new Error('[memory-tx] evidence_pack_id 缺失：违反「每条 memory_version 必须带证据包」约束')
  if (!Array.isArray(evidenceIds) || evidenceIds.length === 0)
    throw new Error('[memory-tx] evidence_ids 为空：违反「每条 memory_version 必须带证据链」约束')
}

export class MemoryTxEngine {
  private versions = new Map<string, MemoryVersionRow>()
  private items = new Map<string, { memoryKind: MemoryKind, currentVersionId: string }>()
  private txVersions = new Map<string, string[]>()
  private audit: AuditLogEntryRow[] = []
  private txResults = new Map<string, TxResult>()
  private gating: GatingCoefficients

  constructor(opts?: { gating?: GatingCoefficients }) {
    this.gating = opts?.gating ?? NO_GATING
  }

  /** 已提交的版本（供 EvidenceWeave 与测试读取）。 */
  getVersion(id: string): MemoryVersionRow | undefined {
    return this.versions.get(id)
  }

  /** 某 tx 产生的全部版本 id（供 EvidenceWeave 构图）。 */
  getVersionsForTx(txId: string): MemoryVersionRow[] {
    return (this.txVersions.get(txId) ?? []).map(id => this.versions.get(id)!).filter(Boolean)
  }

  get auditLog(): AuditLogEntryRow[] {
    return this.audit
  }

  private recordAudit(e: AuditLogEntryRow): void {
    this.audit.push(e)
  }

  /**
   * 提交一笔受控写入事务。幂等：同一 `tx_id` 第二次提交直接返回首次结果。
   */
  commit(input: MemoryTxInput): TxResult {
    const txId = input.tx_id
      ?? makeId('tx', input.session_id, input.trace_id)

    // 幂等：直接返回首跑结果（不产生任何新版本/事件）。
    const cached = this.txResults.get(txId)
    if (cached)
      return cached

    const plan = new Map(input.pgc_write_plan.map(p => [p.memory_write_id, p]))
    const now = Date.now()
    const committed: CommittedMemory[] = []
    const throttled: ThrottledMemory[] = []
    const rejected: RejectedMemory[] = []

    // 1) 按 PGC write_plan 分类候选。
    for (const p of input.memory_payloads) {
      const decision = plan.get(p.memory_write_id)?.decision
      if (decision === 'commit') {
        // 进入提交候选集，稍后做证据校验
      }
      else if (decision === 'throttle' || decision === 'defer') {
        throttled.push({ memory_write_id: p.memory_write_id, decision })
      }
      else {
        rejected.push({ memory_write_id: p.memory_write_id, decision: 'reject', reason: decision ? 'pgc_rejected' : 'no_write_plan' })
      }
    }

    const commitCandidates = input.memory_payloads.filter(p => plan.get(p.memory_write_id)?.decision === 'commit')

    // 2) 证据校验（硬约束）：无 evidence_pack_id 或证据链为空 ⇒ reject，不落库。
    const validCommits: MemoryPayload[] = []
    for (const p of commitCandidates) {
      if (!p.evidence_pack_id || p.evidence_ids.length === 0) {
        rejected.push({ memory_write_id: p.memory_write_id, decision: 'reject', reason: 'no_evidence' })
      }
      else {
        validCommits.push(p)
      }
    }

    // 3) max_writes 上限：超额部分 reject（不落库）。
    let commitFinal = validCommits
    if (validCommits.length > input.tx_policy.max_writes) {
      const excess = validCommits.slice(input.tx_policy.max_writes)
      for (const e of excess)
        rejected.push({ memory_write_id: e.memory_write_id, decision: 'reject', reason: 'tx_max_writes_exceeded' })
      commitFinal = validCommits.slice(0, input.tx_policy.max_writes)
    }

    // 4) bundle 原子性：任一提交候选因证据/上限失败 ⇒ 全部回滚（none committed）。
    if (input.tx_policy.atomicity === 'bundle' && rejected.length > 0) {
      for (const p of commitFinal)
        rejected.push({ memory_write_id: p.memory_write_id, decision: 'reject', reason: 'bundle_rolled_back' })
      commitFinal = []
    }

    // 5) 真正落库：只有 commitFinal 会产出 memory_versions（约束 1 的落点）。
    for (const p of commitFinal) {
      const planEntry = plan.get(p.memory_write_id)!
      assertEvidenceChain(p.evidence_pack_id, p.evidence_ids) // 双保险
      const itemId = makeId('mi', p.memory_write_id)
      const versionId = makeId('mv', txId, p.memory_write_id)
      const contentHashSha256 = contentHash(p.normalized_payload)
      const sal = p.normalized_payload.attributes.salience
      const dur = sal ? durability(sal, this.gating) : 1

      const version: MemoryVersionRow = {
        id: versionId,
        memoryTxId: txId,
        memoryItemId: itemId,
        memoryWriteId: p.memory_write_id,
        memoryKind: p.normalized_payload.memory_kind,
        contentHashSha256,
        evidencePackId: p.evidence_pack_id,
        evidenceIds: [...p.evidence_ids],
        pgcStateId: planEntry.pgc_state_snapshot.pgc_state_id,
        intensity: planEntry.final_intensity,
        durability: dur,
        sourceClaimIds: p.normalized_payload.attributes.source_claim_ids,
        riskLevel: p.normalized_payload.attributes.risk_level,
        createdAt: now,
      }
      this.versions.set(versionId, version)
      this.items.set(itemId, { memoryKind: version.memoryKind, currentVersionId: versionId })
      const arr = this.txVersions.get(txId) ?? []
      arr.push(versionId)
      this.txVersions.set(txId, arr)

      this.recordAudit({
        id: makeId('aud', txId, p.memory_write_id),
        txId,
        actor: p.provenance.actor,
        action: 'memory_version.commit',
        beforeHash: undefined,
        afterHash: contentHashSha256,
        at: now,
      })
      committed.push({ memory_item_id: itemId, memory_version_id: versionId, memory_write_id: p.memory_write_id })
    }

    const status: TxResult['status']
      = committed.length > 0 && rejected.length === 0
        ? 'committed'
        : committed.length === 0 && rejected.length > 0
          ? 'rejected'
          : 'partial'

    // 6) 发出已校验事件（aijade.memory_tx.committed），idempotency_key = txId。
    const committedEvent = memoryTxCommittedEvent.parse({
      event_id: makeId('evt', txId, 'committed'),
      trace_id: input.trace_id,
      correlation_id: input.trace_id,
      timestamp: now,
      producer: 'memory-tx',
      idempotency_key: txId,
      replay_mode: 'live',
      risk_level: committed.some(c => this.versions.get(c.memory_version_id)?.riskLevel === 'high') ? 'high' : 'low',
      topic: 'aijade.memory_tx.committed',
      payload: {
        tx_id: txId,
        trace_id: input.trace_id,
        committed_count: committed.length,
        rejected_count: rejected.length,
        throttled_count: throttled.length,
      },
    })

    const result: TxResult = {
      tx_id: txId,
      status,
      committed,
      throttled,
      rejected,
      audit_log: { events: this.audit.filter(a => a.txId === txId) },
      events: [committedEvent],
    }

    // 幂等登记：之后同 tx_id 提交直接返回本结果。
    this.txResults.set(txId, result)
    return result
  }

  /** 把已提交结果落为 memory_txs 行（DB 映射用，纯读取当前状态）。 */
  toMemoryTxRow(input: MemoryTxInput, result: TxResult): MemoryTxRow {
    const txId = result.tx_id
    return {
      id: txId,
      sessionId: input.session_id,
      traceId: input.trace_id,
      atomicity: input.tx_policy.atomicity,
      maxWrites: input.tx_policy.max_writes,
      status: result.status,
      createdAt: this.versions.get(result.committed[0]?.memory_version_id ?? '')?.createdAt ?? Date.now(),
    }
  }
}
