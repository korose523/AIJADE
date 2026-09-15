import type { MemoryPayload, TxPolicy } from './memory-tx'
import type { PgcWritePlanEntry } from './pgc'

import { describe, expect, it } from 'vitest'

import { MemoryTxEngine } from './memory-tx'
import { NEUTRAL_GATE } from './plasticity'

function plan(writeId: string, decision: PgcWritePlanEntry['decision'], finalIntensity = 1): PgcWritePlanEntry {
  return {
    memory_write_id: writeId,
    decision,
    final_intensity: finalIntensity,
    reason_codes: [],
    expected_tests: [],
    pgc_state_snapshot: {
      pgc_state_id: `pgc_${writeId}`,
      components: {
        plasticity: { ...NEUTRAL_GATE },
        evidence_strength: 1,
        contradiction_severity: 0,
        evidence_uncertainty: 0,
        persona_shift_risk: 0,
      },
    },
  }
}

function payload(writeId: string, evidencePackId: string, evidenceIds: string[]): MemoryPayload {
  return {
    memory_write_id: writeId,
    normalized_payload: {
      memory_kind: 'long_term',
      content_object: { text: writeId },
      attributes: { tags: [], source_claim_ids: [] },
    },
    evidence_pack_id: evidencePackId,
    evidence_ids: evidenceIds,
    provenance: { source: 'test', actor: 'tester' },
  }
}

const perWrite: TxPolicy = { atomicity: 'per_write', max_writes: 100 }

describe('memoryTx — 无证据写入必须被拒绝（硬约束）', () => {
  it('evidence_ids 为空且 PGC 判 commit ⇒ 该写入被 reject(no_evidence)，且**不产生任何 memory_version**', () => {
    const engine = new MemoryTxEngine()
    const r = engine.commit({
      session_id: 's1',
      trace_id: 't1',
      tx_id: 'tx_no_evidence',
      pgc_write_plan: [plan('mw_a', 'commit')],
      memory_payloads: [payload('mw_a', 'pack_1', [])], // 空证据链
      tx_policy: perWrite,
    })
    expect(r.rejected.map(x => x.memory_write_id)).toContain('mw_a')
    expect(r.rejected[0].reason).toBe('no_evidence')
    expect(r.committed).toHaveLength(0)
    // 约束 1+2：没有任何版本被创建（事务根本没落库）
    expect(engine.getVersionsForTx('tx_no_evidence')).toHaveLength(0)
  })

  it('缺少 evidence_pack_id 同样被 reject，且全仓不存在无证据版本（双保险）', () => {
    const engine = new MemoryTxEngine()
    engine.commit({
      session_id: 's2',
      trace_id: 't2',
      tx_id: 'tx_no_pack',
      pgc_write_plan: [plan('mw_b', 'commit')],
      memory_payloads: [payload('mw_b', '', ['e1'])], // 空 pack id
      tx_policy: perWrite,
    })
    // 遍历所有已生成版本，断言每条都带证据包且证据链非空
    for (const v of engine.getVersionsForTx('tx_no_pack'))
      expect(v.evidenceIds.length).toBeGreaterThan(0)
    expect(engine.getVersionsForTx('tx_no_pack')).toHaveLength(0)
  })

  it('已提交的版本确实带 evidence_pack_id 与 evidence 链', () => {
    const engine = new MemoryTxEngine()
    const r = engine.commit({
      session_id: 's3',
      trace_id: 't3',
      tx_id: 'tx_ok',
      pgc_write_plan: [plan('mw_c', 'commit')],
      memory_payloads: [payload('mw_c', 'pack_x', ['e1', 'e2'])],
      tx_policy: perWrite,
    })
    expect(r.committed).toHaveLength(1)
    const v = engine.getVersion(r.committed[0].memory_version_id)!
    expect(v.evidencePackId).toBe('pack_x')
    expect(v.evidenceIds).toEqual(['e1', 'e2'])
    expect(v.contentHashSha256).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe('memoryTx — 幂等（同一 tx 重复提交）', () => {
  it('同一 tx_id 二次提交返回首次结果且不再产生新版本', () => {
    const engine = new MemoryTxEngine()
    const input = {
      session_id: 's4',
      trace_id: 't4',
      tx_id: 'tx_idem',
      pgc_write_plan: [plan('mw_d', 'commit')],
      memory_payloads: [payload('mw_d', 'pack_y', ['e1'])],
      tx_policy: perWrite,
    }
    const r1 = engine.commit(input)
    const versionsAfterFirst = engine.getVersionsForTx('tx_idem').length
    const r2 = engine.commit(input)
    expect(r2).toBe(r1) // 同一结果对象（缓存）
    expect(r2.committed.map(c => c.memory_version_id)).toEqual(r1.committed.map(c => c.memory_version_id))
    // 没有重复落库
    expect(engine.getVersionsForTx('tx_idem').length).toBe(versionsAfterFirst)
    expect(versionsAfterFirst).toBe(1)
  })
})

describe('memoryTx — 原子性', () => {
  it('bundle：任一候选无证据 ⇒ 全部回滚，无一提交', () => {
    const engine = new MemoryTxEngine()
    const r = engine.commit({
      session_id: 's5',
      trace_id: 't5',
      tx_id: 'tx_bundle',
      pgc_write_plan: [plan('mw_good', 'commit'), plan('mw_bad', 'commit')],
      memory_payloads: [
        payload('mw_good', 'pack_g', ['e1']),
        payload('mw_bad', 'pack_b', []), // 无证据
      ],
      tx_policy: { atomicity: 'bundle', max_writes: 100 },
    })
    expect(r.committed).toHaveLength(0)
    expect(r.status).toBe('rejected')
    expect(engine.getVersionsForTx('tx_bundle')).toHaveLength(0)
  })

  it('per_write：坏候选被拒、好候选照常提交', () => {
    const engine = new MemoryTxEngine()
    const r = engine.commit({
      session_id: 's6',
      trace_id: 't6',
      tx_id: 'tx_perwrite',
      pgc_write_plan: [plan('mw_good', 'commit'), plan('mw_bad', 'commit')],
      memory_payloads: [
        payload('mw_good', 'pack_g', ['e1']),
        payload('mw_bad', 'pack_b', []),
      ],
      tx_policy: perWrite,
    })
    expect(r.committed.map(c => c.memory_write_id)).toContain('mw_good')
    expect(r.rejected.map(c => c.memory_write_id)).toContain('mw_bad')
    expect(r.status).toBe('partial')
  })
})

describe('memoryTx — 分类与上限', () => {
  it('throttle/defer 候选不落库（不产生版本）', () => {
    const engine = new MemoryTxEngine()
    const r = engine.commit({
      session_id: 's7',
      trace_id: 't7',
      tx_id: 'tx_throttle',
      pgc_write_plan: [plan('mw_th', 'throttle'), plan('mw_df', 'defer')],
      memory_payloads: [payload('mw_th', 'pack_h', ['e1']), payload('mw_df', 'pack_i', ['e1'])],
      tx_policy: perWrite,
    })
    expect(r.throttled).toHaveLength(2)
    expect(r.committed).toHaveLength(0)
    expect(engine.getVersionsForTx('tx_throttle')).toHaveLength(0)
  })

  it('max_writes 超出部分被拒', () => {
    const engine = new MemoryTxEngine()
    const r = engine.commit({
      session_id: 's8',
      trace_id: 't8',
      tx_id: 'tx_max',
      pgc_write_plan: [plan('mw_1', 'commit'), plan('mw_2', 'commit'), plan('mw_3', 'commit')],
      memory_payloads: [
        payload('mw_1', 'p', ['e1']),
        payload('mw_2', 'p', ['e1']),
        payload('mw_3', 'p', ['e1']),
      ],
      tx_policy: { atomicity: 'per_write', max_writes: 2 },
    })
    expect(r.committed).toHaveLength(2)
    expect(r.rejected.map(x => x.reason)).toContain('tx_max_writes_exceeded')
  })

  it('提交产出 aijade.memory_tx.committed 事件（zod 已校验，流水线可串联）', () => {
    const engine = new MemoryTxEngine()
    const r = engine.commit({
      session_id: 's9',
      trace_id: 't9',
      tx_id: 'tx_evt',
      pgc_write_plan: [plan('mw_e', 'commit')],
      memory_payloads: [payload('mw_e', 'pack_e', ['e1'])],
      tx_policy: perWrite,
    })
    expect(r.events[0].topic).toBe('aijade.memory_tx.committed')
    expect((r.events[0].payload as { committed_count: number }).committed_count).toBe(1)
  })
})
