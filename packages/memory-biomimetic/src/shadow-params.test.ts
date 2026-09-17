import type { AijadeEvent } from './events'

import { describe, expect, it } from 'vitest'

import { assertV10RequiredFields, buildLearningProposedShadowParamsEvent } from './events'
import { decidePgc } from './pgc'
import {
  computeLearningInputHash,
  learningStimulusFeatures,
  ShadowParamsIntegrityError,
  shadowParamsProposalFromEvent,
  shadowProposalAsPgcCandidate,
  verifyShadowParamsProposalAnchor,
} from './shadow-params'
import { V9CausalRuntime } from './v9-runtime'

/** 构造一个 input_hash 自洽的合法 shadow_params 学习事件（生产方必须用同一口径生成）。 */
function buildValidShadowParamsEvent(): AijadeEvent {
  const sessionId = 's1'
  const proposalId = 'p1'
  const candidateParams = { lr: 0.01, layers: 3 }
  const input_hash = computeLearningInputHash(sessionId, proposalId, candidateParams)
  return buildLearningProposedShadowParamsEvent(
    {
      session_id: sessionId,
      proposal_id: proposalId,
      render_ref: 'r1',
      applied_params_hash: 'aph1',
      asset_version_hash: 'avh1',
      input_hash,
      candidate_params: candidateParams,
      confidence: 0.8,
    },
    {
      event_id: 'e1',
      trace_id: 't1',
      correlation_id: 't1',
      timestamp: 1,
      producer: 'test',
      origin_device: 'test-device',
      privacy_level: 1,
      evidence_refs: [],
      causal_context_refs: ['t1'],
      risk_score: 0,
      idempotency_key: 'ik1',
      replay_mode: 'live',
      risk_level: 'low',
      tick: 5,
      causality: { inputHash: input_hash },
    },
  )
}

describe('shadow-params reduction', () => {
  // D.1 归约确定性：同输入两次归约逐位相同。
  it('reduces deterministically (bit-for-bit identical) for the same input', () => {
    const ev = buildValidShadowParamsEvent()
    const a = shadowParamsProposalFromEvent(ev)
    const b = shadowParamsProposalFromEvent(ev)
    expect(a).toEqual(b)
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
  })

  // D.2 input_hash 与重算不一致 ⇒ 被拒（证明闸门非恒真）。
  it('rejects when input_hash is inconsistent with recomputation (gate is not a tautology)', () => {
    const ev = buildValidShadowParamsEvent()
    const corrupted = {
      ...ev,
      payload: { ...(ev.payload as Record<string, unknown>), input_hash: '0'.repeat(64) },
    } as AijadeEvent
    expect(() => shadowParamsProposalFromEvent(corrupted)).toThrow(ShadowParamsIntegrityError)
  })

  // D.3 归约出的 proposal 经 decidePgc 得到的 commit_reason 落在既有判定链上；
  //      构造低 w / 高疲劳场景使其不 等于 committed（证明门控真会拒）。
  it('runs the reduced proposal through decidePgc and the gate actually rejects under low w / high fatigue', () => {
    const ev = buildValidShadowParamsEvent()
    const proposal = shadowParamsProposalFromEvent(ev)
    const candidate = shadowProposalAsPgcCandidate(proposal)
    const decision = decidePgc({
      session_id: 's1',
      trace_id: 't1',
      pgc_policy_version: 'pgc_policy_v1',
      candidate_memory_writes: [candidate],
      pgc_read_context: {
        now: 1,
        last_n_events: [{ topic: 'aijade.learning.proposed.shadow_params' }],
        evidence_records: [],
        // 高疲劳 (f=1.0) ⇒ w=0（低 w），门控应拒，不应 committed。
        pgc_v6_state: { a: 0.1, c: 0.1, d: 0.1, f: 1.0 },
        pgc_v6_stimulus_features: learningStimulusFeatures(proposal),
      },
    })
    const entry = decision.write_plan[0]!
    expect(entry.pgc_state_snapshot.v6).toBeDefined()
    const reason = entry.pgc_state_snapshot.v6!.commit_reason
    expect(reason).not.toBe('committed')
    // 落在既有判定链上（v10 设计文档 §3 的 commit_reason 枚举）。
    expect([
      'w_max_below_theta',
      'contradiction_high',
      'evidence_insufficient',
      'fatigue_deferred',
      'w_below_theta',
    ]).toContain(reason)
  })

  // D.4 processLearning 产出的事件信封同时含 tick 与 causality.inputHash，且等于传入值。
  it('processLearning emits a v10 learning event carrying tick and causality propagated from input', async () => {
    const ev = buildValidShadowParamsEvent()
    const artifacts: unknown[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (a) => {
        artifacts.push(a)
      },
    })
    const tick = 42
    const inputHash = 'propagated-input-hash-123'
    const result = await runtime.processLearning({
      eventId: 'e1',
      sessionId: 's1',
      traceId: 't1',
      correlationId: 't1',
      timestamp: 1,
      originDevice: 'desktop',
      privacyLevel: 1,
      riskScore: 0.1,
      tick,
      inputHash,
      event: ev,
    })
    expect(artifacts).toHaveLength(1)
    const learningEvents = result.artifact.events.filter(e => e.topic.startsWith('aijade.learning.'))
    expect(learningEvents.length).toBeGreaterThanOrEqual(1)
    const le = learningEvents[0]!
    expect(le.tick).toBe(tick)
    expect(le.causality).toEqual({ inputHash })
  })

  // D.5 assertV10RequiredFields 对 processLearning 产出的事件通过。
  it('assertV10RequiredFields passes on the learning event produced by processLearning', async () => {
    const ev = buildValidShadowParamsEvent()
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async () => undefined,
    })
    const result = await runtime.processLearning({
      eventId: 'e1',
      sessionId: 's1',
      traceId: 't1',
      correlationId: 't1',
      timestamp: 1,
      originDevice: 'desktop',
      privacyLevel: 1,
      riskScore: 0.1,
      tick: 42,
      inputHash: 'propagated-input-hash-123',
      event: ev,
    })
    const learningEvents = result.artifact.events.filter(e => e.topic.startsWith('aijade.learning.'))
    expect(learningEvents.length).toBeGreaterThanOrEqual(1)
    for (const le of learningEvents)
      expect(() => assertV10RequiredFields(le)).not.toThrow()
  })
})

// ============================================================================
// verifyShadowParamsProposalAnchor —— 把闸门变成"任何持有提案的一方都能重放的动作"
// ============================================================================

describe('verifyShadowParamsProposalAnchor', () => {
  /** 归约出的 shadow_params 提案（有生产方声明的 input_hash，归约时已比对通过）。 */
  function shadowProposal() {
    return shadowParamsProposalFromEvent(buildValidShadowParamsEvent())
  }

  it('accepts an honest shadow_params proposal', () => {
    expect(verifyShadowParamsProposalAnchor(shadowProposal())).toEqual({ ok: true })
  })

  it('rejects a shadow_params proposal whose body was changed after reduction', () => {
    // 模拟"序列化后被人改过"：body 变了、hash 没跟着变。
    const tampered = { ...shadowProposal(), candidateParams: { lr: 0.99, layers: 3 } }
    const res = verifyShadowParamsProposalAnchor(tampered)
    expect(res.ok).toBe(false)
    expect(res.ok === false && res.reason).toContain('input_hash mismatch')
  })

  it('rejects a shadow_params proposal whose session/proposal id was changed', () => {
    // 锚点把 session_id / proposal_id 纳入哈希，故改 id 也必须被检出（防跨提案碰撞）。
    const tampered = { ...shadowProposal(), proposalId: 'p2' }
    expect(verifyShadowParamsProposalAnchor(tampered).ok).toBe(false)
  })

  it('accepts an evidence proposal whose derived hash still matches its body', () => {
    // evidence 契约里没有 input_hash 字段，故归约时必须 anchorVerified=false。
    const proposal = {
      proposalId: 'p1',
      sessionId: 's1',
      inputHash: computeLearningInputHash('s1', 'p1', { evidence_hash: 'eh1', claim_text: 'claim' }),
      anchorKind: 'evidence' as const,
      anchorVerified: false,
      candidateParams: {},
      confidence: 0.7,
      evidenceHash: 'eh1',
      claimText: 'claim',
    }
    expect(verifyShadowParamsProposalAnchor(proposal)).toEqual({ ok: true })
  })

  it('rejects an evidence proposal whose claim_text was changed', () => {
    const proposal = {
      proposalId: 'p1',
      sessionId: 's1',
      inputHash: computeLearningInputHash('s1', 'p1', { evidence_hash: 'eh1', claim_text: 'claim' }),
      anchorKind: 'evidence' as const,
      anchorVerified: false,
      candidateParams: {},
      confidence: 0.7,
      evidenceHash: 'eh1',
      claimText: 'a different claim',
    }
    const res = verifyShadowParamsProposalAnchor(proposal)
    expect(res.ok).toBe(false)
    expect(res.ok === false && res.reason).toContain('evidence input_hash mismatch')
  })

  it('rejects (does not skip) an evidence proposal missing its anchor fields', () => {
    // "算不出来"绝不能被当成"算出来且一致"。
    const proposal = {
      proposalId: 'p1',
      sessionId: 's1',
      inputHash: 'whatever',
      anchorKind: 'evidence' as const,
      anchorVerified: false,
      candidateParams: {},
      confidence: 0.7,
    }
    const res = verifyShadowParamsProposalAnchor(proposal)
    expect(res.ok).toBe(false)
    expect(res.ok === false && res.reason).toContain('cannot be recomputed')
  })

  it('is stable across a JSON round-trip (contentHash canonicalises keys)', () => {
    // promotion worker 从 Redis 反序列化 proposal —— 往返不得改变判定。
    const proposal = shadowProposal()
    const roundTripped = JSON.parse(JSON.stringify(proposal)) as typeof proposal
    expect(verifyShadowParamsProposalAnchor(roundTripped)).toEqual({ ok: true })
  })

  it('the honest branch really is verified, not merely un-checked', () => {
    // 区分"有声明值且比对过"与"没有声明值可比对"——这正是 anchorVerified 存在的理由。
    const shadow = shadowProposal()
    expect(shadow.anchorKind).toBe('shadow_params')
    expect(shadow.anchorVerified).toBe(true)
  })
})
