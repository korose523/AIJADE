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

import type { AijadeEvent, PrivacyLevel, RiskLevel } from './events'
import type { CommitReason, MemoryKind, PgcWritePlanEntry } from './pgc'
import type { Tau } from './pgc-state'
import type { GatingCoefficients } from './types'
import type {
  AuditLogEntryRow,
  MemoryTxRow,
  MemoryVersionRow,
} from './v9-schema'

import { memoryTxCommittedEvent } from './events'
import { durability } from './gating'
import { DEFAULT_PGC_V6_POLICY, PGC_V6_TAU_CASE_ID } from './pgc'
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

/**
 * 信封的**观察/传输上下文**：这条事件是在哪台设备、什么隐私级别、多大风险下被观察到的。
 *
 * 为什么单独抽出来而不是并进 `MemoryTxInput` 的语义字段：这 5 项描述的是**事件如何被观察**，
 * 不是**事务写了什么**。它们只能由运行时（真正持有观察上下文的那一层）提供，引擎自己
 * 无从得知 —— 引擎内部凭空造一个设备名，就是 v10 §14.1 禁止的「伪造因果关键字段」。
 *
 * `evidence_refs` / `causal_context_refs` 留空时由引擎按**自己输入里的真实值**派生
 * （证据链来自 `memory_payloads`，因果上下文取 `trace_id`），不需要调用方重复填写。
 */
export interface MemoryTxEnvelopeContext {
  /** 产出事件的设备/进程标识。**不要**填"占位符"，填不出真实值就别传这个对象。 */
  origin_device: string
  privacy_level: PrivacyLevel
  /** 连续风险分 [0,1]，不是 3 级带宽。 */
  risk_score: number
  /** 因果上下文引用；缺省取 `[input.trace_id]`。 */
  causal_context_refs?: string[]
  /** 证据引用；缺省由本 tx 的 payload 证据链派生。 */
  evidence_refs?: string[]
  /**
   * v10 确定性排序序号与输入溯源哈希（由调用方从**输入事件**传播而来，本层不发明）。
   *
   * 不传则 `memory_tx.committed` 事件不带这两个字段，于是该事件不属于任何回放单元：
   * 回放按 `tick` + `causality.inputHash` 找事件，会**看不到**这次提交 —— 而它正是
   * `S6`/`S8`（是否真实落库）的唯一记录点。反过来，若本层自己编一个，就破坏了
   * 「tick 表示输入快照」的语义。故只能由知情的一层传入。
   */
  tick?: number
  causality?: { inputHash: string }
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
  /**
   * 观察/传输上下文。运行时路径**必须**传真实值（见 `V9CausalRuntime`）。
   *
   * 缺省时的语义是**「本层没有观察上下文」**，而不是"风险为 0 / 设备未知"：此时
   * `origin_device` 会被填成 `'kernel:memory-tx'`（**字面标明是引擎层**，不冒充设备），
   * `privacy_level=0` / `risk_score=0` 表示这层不掌握该信息。这条路径只应出现在**引擎的
   * 隔离单测**里；一旦事件要上总线，就必须由运行时补上真实值 ——
   * `v9-runtime.test.ts` 有一条断言专门证明运行时产出的 `origin_device` / `risk_score`
   * 是输入的真实值、不是这里的占位值。
   */
  envelope_context?: MemoryTxEnvelopeContext
}

/** 无观察上下文时的层内署名（**不是**设备名，故意长得不像设备名）。 */
const UNCONTEXTED_ORIGIN = 'kernel:memory-tx'

// ============================================================================
// 输出类型
// ============================================================================

/**
 * 每一次写入尝试的门控审计（commit/throttle/defer/reject 全覆盖，不另开并行数组）。
 *
 * 核心语义：`memory_version_id` 在此**显式为 null**（而非「不在 committed[] 里」的隐含缺席），
 * 让「没落库」成为可断言的事实。无 v6 状态时 `tau === null`（沿用旧证据阈值策略，v6 诊断项置 null）。
 */
export interface MemoryWriteGatingAudit {
  memory_write_id: string
  /** 当前在用的基线编号（4 = 第 4 份参数）；无 v6 状态时为 null。 */
  tau_case_id: number | null
  tau: Tau | null
  /** commit 阈值 θ（文档值 0.55）。 */
  theta_commit_threshold: number
  /** 闭式全局上界；无 v6 状态时为 null。 */
  w_max_global: number | null
  /** 给定当前疲劳的上界；无 v6 状态时为 null。 */
  w_max_at_f: number | null
  /** 本次提交权重 w；无 v6 状态时为 null。 */
  w: number | null
  /** 本次写入是否可能 commit（v6 诊断，区分「状态不好」与「参数不可能」）；无 v6 状态时 null。 */
  commit_possible: boolean | null
  commit_reason: CommitReason | null
  /** 确实产生的版本 id；未落库（被拒/节流/推迟）时为 null。 */
  memory_version_id: string | null
  content_hash: string | null
}

export interface CommittedMemory {
  memory_item_id: string
  memory_version_id: string
  memory_write_id: string
  /** 门控审计：committed 时 memory_version_id 等于本条目。 */
  gating: MemoryWriteGatingAudit
}

export interface ThrottledMemory {
  memory_write_id: string
  decision: 'throttle' | 'defer'
  /** 门控审计：throttle/defer 均不落库，gating.memory_version_id === null。 */
  gating: MemoryWriteGatingAudit
}

export interface RejectedMemory {
  memory_write_id: string
  decision: 'reject'
  reason: string
  /** 门控审计：rejected 不落库，gating.memory_version_id === null。 */
  gating: MemoryWriteGatingAudit
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

/**
 * 构造单次写入尝试的门控审计。v6 路径从 `planEntry.pgc_state_snapshot.v6` 取 τ/w/w_max/判定；
 * 无 v6 状态（旧证据阈值策略）时仅填 `tau: null` 与版本/哈希，`commit_possible`/`commit_reason`
 * 等 v6 诊断项置 null。`memory_version_id` / `content_hash` 由调用方按本次实际落库情况填入
 * （未落库即 null——把「缺席」变成显式断言）。
 */
function buildGatingAudit(
  memoryWriteId: string,
  planEntry: PgcWritePlanEntry | undefined,
  memoryVersionId: string | null,
  contentHash: string | null,
): MemoryWriteGatingAudit {
  const v6 = planEntry?.pgc_state_snapshot.v6
  if (!v6) {
    return {
      memory_write_id: memoryWriteId,
      tau_case_id: null,
      tau: null,
      theta_commit_threshold: DEFAULT_PGC_V6_POLICY.thresholds.commit_min_w,
      w_max_global: null,
      w_max_at_f: null,
      w: null,
      commit_possible: null,
      commit_reason: null,
      memory_version_id: memoryVersionId,
      content_hash: contentHash,
    }
  }
  return {
    memory_write_id: memoryWriteId,
    tau_case_id: PGC_V6_TAU_CASE_ID,
    tau: v6.tau,
    theta_commit_threshold: DEFAULT_PGC_V6_POLICY.thresholds.commit_min_w,
    w_max_global: v6.w_max_global,
    w_max_at_f: v6.w_max_at_f,
    w: v6.w,
    commit_possible: v6.commit_possible,
    commit_reason: v6.commit_reason,
    memory_version_id: memoryVersionId,
    content_hash: contentHash,
  }
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
      const entry = plan.get(p.memory_write_id)
      const decision = entry?.decision
      if (decision === 'commit') {
        // 进入提交候选集，稍后做证据校验
      }
      else if (decision === 'throttle' || decision === 'defer') {
        throttled.push({ memory_write_id: p.memory_write_id, decision, gating: buildGatingAudit(p.memory_write_id, entry, null, null) })
      }
      else {
        rejected.push({ memory_write_id: p.memory_write_id, decision: 'reject', reason: decision ? 'pgc_rejected' : 'no_write_plan', gating: buildGatingAudit(p.memory_write_id, entry, null, null) })
      }
    }

    const commitCandidates = input.memory_payloads.filter(p => plan.get(p.memory_write_id)?.decision === 'commit')

    // 2) 证据校验（硬约束）：无 evidence_pack_id 或证据链为空 ⇒ reject，不落库。
    const validCommits: MemoryPayload[] = []
    for (const p of commitCandidates) {
      if (!p.evidence_pack_id || p.evidence_ids.length === 0) {
        rejected.push({ memory_write_id: p.memory_write_id, decision: 'reject', reason: 'no_evidence', gating: buildGatingAudit(p.memory_write_id, plan.get(p.memory_write_id), null, null) })
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
        rejected.push({ memory_write_id: e.memory_write_id, decision: 'reject', reason: 'tx_max_writes_exceeded', gating: buildGatingAudit(e.memory_write_id, plan.get(e.memory_write_id), null, null) })
      commitFinal = validCommits.slice(0, input.tx_policy.max_writes)
    }

    // 4) bundle 原子性：任一提交候选因证据/上限失败 ⇒ 全部回滚（none committed）。
    if (input.tx_policy.atomicity === 'bundle' && rejected.length > 0) {
      for (const p of commitFinal)
        rejected.push({ memory_write_id: p.memory_write_id, decision: 'reject', reason: 'bundle_rolled_back', gating: buildGatingAudit(p.memory_write_id, plan.get(p.memory_write_id), null, null) })
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
      committed.push({
        memory_item_id: itemId,
        memory_version_id: versionId,
        memory_write_id: p.memory_write_id,
        gating: buildGatingAudit(p.memory_write_id, planEntry, versionId, contentHashSha256),
      })
    }

    const status: TxResult['status']
      = committed.length > 0 && rejected.length === 0
        ? 'committed'
        : committed.length === 0 && rejected.length > 0
          ? 'rejected'
          : 'partial'

    // 6) 发出已校验事件（aijade.memory_tx.committed），idempotency_key = txId。
    //
    // 信封的 5 个观察/传输字段：能由本层真实派生的就派生（证据引用来自本 tx 的 payload
    // 证据链、因果上下文取 trace_id），派生不出的（设备 / 隐私分级 / 风险分）才向调用方
    // 索取；缺上下文时用品名标注本层，**不冒充**真实设备（详见 MemoryTxInput.envelope_context）。
    const envelopeContext = input.envelope_context
    const derivedEvidenceRefs = [...new Set(
      input.memory_payloads.flatMap(p => [p.evidence_pack_id, ...p.evidence_ids]).filter(Boolean),
    )]
    const committedEvent = memoryTxCommittedEvent.parse({
      event_id: makeId('evt', txId, 'committed'),
      trace_id: input.trace_id,
      correlation_id: input.trace_id,
      timestamp: now,
      producer: 'memory-tx',
      origin_device: envelopeContext?.origin_device ?? UNCONTEXTED_ORIGIN,
      privacy_level: envelopeContext?.privacy_level ?? 0,
      evidence_refs: envelopeContext?.evidence_refs ?? derivedEvidenceRefs,
      causal_context_refs: envelopeContext?.causal_context_refs ?? [input.trace_id],
      risk_score: envelopeContext?.risk_score ?? 0,
      idempotency_key: txId,
      replay_mode: 'live',
      risk_level: committed.some(c => this.versions.get(c.memory_version_id)?.riskLevel === 'high') ? 'high' : 'low',
      // v10 溯源：本 tx 属于输入快照 `envelope_context.causality.inputHash` / `tick`。
      // 由调用方传入而不是本层发明；缺上下文时保持缺省（v9 路径不产生这两个字段）。
      ...(envelopeContext?.tick === undefined ? {} : { tick: envelopeContext.tick }),
      ...(envelopeContext?.causality === undefined ? {} : { causality: envelopeContext.causality }),
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
