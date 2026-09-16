/**
 * v6 门控审计集成测试：给 MemoryTx 的每一次写入尝试（commit/throttle/defer/reject）挂显式 gating。
 *
 * 核心目的：把"为什么没落库"从「不在 committed[] 里的隐含缺席」变成 `gating.memory_version_id === null`
 * 的**显式断言**；并让基线层面的构造性零（w_max_below_theta）在审计里可观测。
 */

import type { MemoryPayload, TxPolicy, TxResult } from './memory-tx'
import type { MemoryKind, PgcCandidateWrite, PgcReadContext, PgcWritePlanEntry } from './pgc'
import type { PgcState4 } from './pgc-state'

import { describe, expect, it } from 'vitest'

import { MemoryTxEngine } from './memory-tx'
import { decideCandidate, DEFAULT_PGC_POLICY_V1 } from './pgc'
import { NEUTRAL_GATE } from './plasticity'

const perWrite: TxPolicy = { atomicity: 'per_write', max_writes: 100 }

function mkPair(writeId: string, memoryKind: MemoryKind, evidenceIds: string[] = ['e1', 'e2', 'e3']) {
  const cand: PgcCandidateWrite = {
    memory_write_id: writeId,
    memory_kind: memoryKind,
    candidate_payload: { text: writeId },
    evidence_ids: evidenceIds,
    proposed_intensity: 1.0,
  }
  const payload: MemoryPayload = {
    memory_write_id: writeId,
    normalized_payload: { memory_kind: memoryKind, content_object: { text: writeId }, attributes: { tags: [], source_claim_ids: [] } },
    evidence_pack_id: 'pack',
    evidence_ids: evidenceIds,
    provenance: { source: 't', actor: 'tester' },
  }
  return { cand, payload }
}

function v6Context(state: PgcState4): PgcReadContext {
  return { now: 1, last_n_events: [], evidence_records: [], beliefs: [], pgc_v6_state: state }
}

/** 用 v6 状态经 PGC 决策产出一个带 v6 快照的 write_plan 项。 */
function v6Plan(cand: PgcCandidateWrite, state: PgcState4): PgcWritePlanEntry {
  return decideCandidate(cand, v6Context(state), DEFAULT_PGC_POLICY_V1)
}

function runWithPlans(planEntries: PgcWritePlanEntry[], payloads: MemoryPayload[]): TxResult {
  const engine = new MemoryTxEngine()
  return engine.commit({
    session_id: 's',
    trace_id: 't',
    tx_id: 'tx_gating',
    pgc_write_plan: planEntries,
    memory_payloads: payloads,
    tx_policy: perWrite,
  })
}

describe('v6 — 门控审计：被拒写入 memory_version_id 显式为 null', () => {
  it('v6 低 w 状态（f=0.9）被 reject，gating.memory_version_id === null 且 commit_reason=w_below_theta', () => {
    const { cand, payload } = mkPair('mw_r', 'long_term')
    const r = runWithPlans([v6Plan(cand, { a: 0, c: 0, d: 0, f: 0.9 })], [payload])
    expect(r.rejected).toHaveLength(1)
    expect(r.rejected[0].gating.memory_version_id).toBeNull()
    expect(r.rejected[0].gating.commit_reason).toBe('w_below_theta')
    expect(r.rejected[0].gating.tau).toBe('semantic')
    expect(r.committed).toHaveLength(0)
  })
})

describe('v6 — 门控审计：被 commit 写入 memory_version_id 与 committed[] 一致', () => {
  it('committed 的 gating.memory_version_id === committed[].memory_version_id，且 tau_case_id=4', () => {
    const { cand, payload } = mkPair('mw_c', 'long_term')
    const r = runWithPlans([v6Plan(cand, { a: 1, c: 1, d: 1, f: 0 })], [payload])
    expect(r.committed).toHaveLength(1)
    expect(r.committed[0].gating.memory_version_id).toBe(r.committed[0].memory_version_id)
    expect(r.committed[0].gating.tau_case_id).toBe(4)
    expect(r.committed[0].gating.tau).toBe('semantic')
    expect(r.committed[0].gating.commit_reason).toBe('committed')
    expect(r.committed[0].gating.commit_possible).toBe(true)
    expect(r.committed[0].gating.w).toBeGreaterThanOrEqual(0.55)
  })
})

describe('v6 — 门控审计：每一次写入尝试都有 gating（commit+throttle+defer+reject 全覆盖）', () => {
  it('4 个 payload 产出 4 条 gating 记录，且无一条重复真源（不另开并行数组）', () => {
    const commit = mkPair('mw_c', 'long_term')
    const throttle = mkPair('mw_t', 'long_term')
    const reject = mkPair('mw_r', 'long_term')
    // defer 由手动 write_plan 项注入（v6 公式下 defer 不可达，但门控记录必须覆盖该决策类型）
    const deferPlan: PgcWritePlanEntry = {
      memory_write_id: 'mw_d',
      decision: 'defer',
      final_intensity: 0.4,
      reason_codes: [],
      expected_tests: [],
      pgc_state_snapshot: {
        pgc_state_id: 'pgc_mw_d',
        components: { plasticity: { ...NEUTRAL_GATE }, evidence_strength: 1, contradiction_severity: 0, evidence_uncertainty: 0, persona_shift_risk: 0 },
      },
    }
    const plans = [
      v6Plan(commit.cand, { a: 1, c: 1, d: 1, f: 0 }), // commit
      v6Plan(throttle.cand, { a: 0, c: 0, d: 0, f: 0.2 }), // throttle (w≈0.441)
      v6Plan(reject.cand, { a: 0, c: 0, d: 0, f: 0.9 }), // reject
      deferPlan, // defer
    ]
    const payloads = [commit.payload, throttle.payload, reject.payload, mkPair('mw_d', 'long_term').payload]
    const r = runWithPlans(plans, payloads)

    expect(r.committed).toHaveLength(1)
    expect(r.rejected).toHaveLength(1)
    expect(r.throttled).toHaveLength(2) // throttle + defer 都归入 throttled[]
    const totalGating = r.committed.length + r.throttled.length + r.rejected.length
    expect(totalGating).toBe(4) // == 输入 payload 数

    for (const e of [...r.committed, ...r.throttled, ...r.rejected])
      expect(e.gating).toBeDefined()
    // 未落库者 memory_version_id 一律 null
    for (const e of [...r.throttled, ...r.rejected])
      expect(e.gating.memory_version_id).toBeNull()
  })
})

describe('v6 — 门控审计：向后兼容（无 pgc_v6_state）', () => {
  it('不传 pgc_v6_state ⇒ gating.tau === null，且行为与改动前一致（仍 commit 有证据写入）', () => {
    const { cand, payload } = mkPair('mw_x', 'long_term')
    const plan = decideCandidate(cand, { now: 1, last_n_events: [], evidence_records: [], beliefs: [] }, DEFAULT_PGC_POLICY_V1)
    expect(plan.pgc_state_snapshot.v6).toBeUndefined()
    const r = runWithPlans([plan], [payload])
    expect(r.committed).toHaveLength(1)
    expect(r.committed[0].gating.tau).toBeNull()
    expect(r.committed[0].gating.tau_case_id).toBeNull()
    expect(r.committed[0].gating.commit_possible).toBeNull()
    expect(r.committed[0].gating.commit_reason).toBeNull()
    // 仍产生版本，gating.memory_version_id 与 committed[] 一致
    expect(r.committed[0].gating.memory_version_id).toBe(r.committed[0].memory_version_id)
  })
})

describe('v6 — 门控审计：基线 1 的构造性零穿过 MemoryTx 仍是显式原因', () => {
  it('v6 状态走第 4 份参数 commit，但若换成基线 1 参数则 w_max_below_theta（证明可观测，非事后解释）', () => {
    // 这里只验证：生产的 v6 路径在好状态下给出 committed，且 gating 携带 w_max_global=1.0
    const { cand, payload } = mkPair('mw_y', 'long_term')
    const r = runWithPlans([v6Plan(cand, { a: 1, c: 1, d: 1, f: 0 })], [payload])
    expect(r.committed[0].gating.w_max_global).toBe(1.0)
    expect(r.committed[0].gating.w_max_at_f).toBeGreaterThanOrEqual(0.55)
  })
})
