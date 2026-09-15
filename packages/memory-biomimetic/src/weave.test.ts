import type { MemoryPayload } from './memory-tx'
import type { PgcWritePlanEntry } from './pgc'

import { describe, expect, it } from 'vitest'

import { MemoryTxEngine } from './memory-tx'
import { NEUTRAL_GATE } from './plasticity'
import { buildWeave } from './weave'

function plan(writeId: string, decision: PgcWritePlanEntry['decision']): PgcWritePlanEntry {
  return {
    memory_write_id: writeId,
    decision,
    final_intensity: 1,
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

function payload(writeId: string, packId: string, evidenceIds: string[], claimIds: string[] = []): MemoryPayload {
  return {
    memory_write_id: writeId,
    normalized_payload: {
      memory_kind: 'long_term',
      content_object: { text: writeId },
      attributes: { tags: [], source_claim_ids: claimIds },
    },
    evidence_pack_id: packId,
    evidence_ids: evidenceIds,
    provenance: { source: 'test', actor: 'tester' },
  }
}

const specA = { include_pgc_snapshot: true, include_claim_ids: true }

describe('evidenceWeave — graph_hash 确定性', () => {
  it('相同 tx + 相同 spec ⇒ 两次构建得到完全相同的 graph_hash', () => {
    const engine = new MemoryTxEngine()
    engine.commit({
      session_id: 's',
      trace_id: 't',
      tx_id: 'tx_w1',
      pgc_write_plan: [plan('mw_1', 'commit'), plan('mw_2', 'commit')],
      memory_payloads: [payload('mw_1', 'p', ['e1', 'e2']), payload('mw_2', 'p', ['e3'])],
      tx_policy: { atomicity: 'per_write', max_writes: 100 },
    })
    const a = buildWeave(engine, 'tx_w1', specA)
    const b = buildWeave(engine, 'tx_w1', specA)
    expect(b.graph_hash).toBe(a.graph_hash)
    expect(b.links).toEqual(a.links)
    expect(b.weave_id).toBe(a.weave_id)
  })

  it('不同证据链 ⇒ 不同 graph_hash', () => {
    const e1 = new MemoryTxEngine()
    e1.commit({
      session_id: 's',
      trace_id: 't',
      tx_id: 'tx_x',
      pgc_write_plan: [plan('mw_1', 'commit')],
      memory_payloads: [payload('mw_1', 'p', ['e1', 'e2'])],
      tx_policy: { atomicity: 'per_write', max_writes: 100 },
    })
    const e2 = new MemoryTxEngine()
    e2.commit({
      session_id: 's',
      trace_id: 't',
      tx_id: 'tx_y',
      pgc_write_plan: [plan('mw_1', 'commit')],
      memory_payloads: [payload('mw_1', 'p', ['e1', 'e9'])], // 不同证据
      tx_policy: { atomicity: 'per_write', max_writes: 100 },
    })
    const h1 = buildWeave(e1, 'tx_x', specA).graph_hash
    const h2 = buildWeave(e2, 'tx_y', specA).graph_hash
    expect(h1).not.toBe(h2)
  })

  it('切换 include_claim_ids ⇒ 不同 graph_hash（spec 进入哈希）', () => {
    const engine = new MemoryTxEngine()
    engine.commit({
      session_id: 's',
      trace_id: 't',
      tx_id: 'tx_spec',
      pgc_write_plan: [plan('mw_1', 'commit')],
      memory_payloads: [payload('mw_1', 'p', ['e1'], ['claim_a'])],
      tx_policy: { atomicity: 'per_write', max_writes: 100 },
    })
    const withClaims = buildWeave(engine, 'tx_spec', { include_pgc_snapshot: true, include_claim_ids: true })
    const withoutClaims = buildWeave(engine, 'tx_spec', { include_pgc_snapshot: true, include_claim_ids: false })
    expect(withClaims.graph_hash).not.toBe(withoutClaims.graph_hash)
    // 当携带 claim 时，link 应出现 hypothesisId
    expect(withClaims.links[0].hypothesisId).toBe('claim_a')
    expect(withoutClaims.links[0].hypothesisId).toBeUndefined()
  })

  it('graph_hash 为 64 位 hex（sha256），可回放比对', () => {
    const engine = new MemoryTxEngine()
    engine.commit({
      session_id: 's',
      trace_id: 't',
      tx_id: 'tx_replay',
      pgc_write_plan: [plan('mw_1', 'commit')],
      memory_payloads: [payload('mw_1', 'p', ['e1'])],
      tx_policy: { atomicity: 'per_write', max_writes: 100 },
    })
    const h = buildWeave(engine, 'tx_replay', specA).graph_hash
    expect(h).toMatch(/^[0-9a-f]{64}$/)
  })

  it('空 tx（无提交）⇒ 空链接、确定性空哈希', () => {
    const engine = new MemoryTxEngine()
    const a = buildWeave(engine, 'tx_empty', specA)
    const b = buildWeave(engine, 'tx_empty', specA)
    expect(a.links).toHaveLength(0)
    expect(a.graph_hash).toBe(b.graph_hash)
  })
})
