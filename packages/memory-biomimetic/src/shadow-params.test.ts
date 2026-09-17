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
