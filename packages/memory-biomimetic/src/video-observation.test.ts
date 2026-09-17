import type { AijadeEvent, AijadeEventEnvelope, VideoTranscriptObservationPayload, WebpageTextObservationPayload } from './events'

import { describe, expect, it } from 'vitest'

import {
  assertV10RequiredFields,
  buildVideoTranscriptObservationEvent,
  buildWebpageTextObservationEvent,
} from './events'
import { decidePgc } from './pgc'
import {
  computeLearningInputHash,
  learningStimulusFeatures,
  shadowParamsProposalFromEvent,
  shadowProposalAsPgcCandidate,
  verifyShadowParamsProposalAnchor,
} from './shadow-params'
import { V9CausalRuntime } from './v9-runtime'
import {
  buildEvidenceEventFromCandidate,
  evidenceFromSubtitleObservation,
  evidenceFromWebpageObservation,
} from './video-observation'

// ---------------------------------------------------------------------------
// 被测用的 payload / 事件构造
// ---------------------------------------------------------------------------

const webpagePayload: WebpageTextObservationPayload = {
  source_url: 'https://example.com/page',
  content_hash: 'abc123contenthash',
  spans: [{ start_offset: 0, end_offset: 11 }],
  observation_text: 'the quick brown fox',
}
const subtitlePayload: VideoTranscriptObservationPayload = {
  video_id: 'vid-42',
  transcript_hash: 'def456transcripthash',
  time_spans: [{ start_ms: 0, end_ms: 1000, text: 'hello world' }],
  caption_text: 'hello world from the video',
}

function observationEnvelope(tick: number, inputHash: string): AijadeEventEnvelope {
  return {
    event_id: 'obs-evt',
    trace_id: 't1',
    correlation_id: 'c1',
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
    tick,
    causality: { inputHash },
  }
}

function webpageObservationEvent(tick: number, inputHash: string): AijadeEvent {
  return buildWebpageTextObservationEvent(webpagePayload, observationEnvelope(tick, inputHash))
}
function subtitleObservationEvent(tick: number, inputHash: string): AijadeEvent {
  return buildVideoTranscriptObservationEvent(subtitlePayload, observationEnvelope(tick, inputHash))
}

// ===========================================================================
// D.1 归约确定性：同输入两次归约逐位相同。
// ===========================================================================
describe('video-observation reduction (A 路 / 纯视频输入)', () => {
  it('reduces a webpage observation deterministically (bit-for-bit identical)', () => {
    const a = evidenceFromWebpageObservation(webpagePayload)
    const b = evidenceFromWebpageObservation(webpagePayload)
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
    expect(a.evidenceHash).toBe(b.evidenceHash)
    expect(a.sourceKind).toBe('webpage_text')
  })

  it('reduces a subtitle observation deterministically (bit-for-bit identical)', () => {
    const a = evidenceFromSubtitleObservation(subtitlePayload)
    const b = evidenceFromSubtitleObservation(subtitlePayload)
    expect(JSON.stringify(a)).toBe(JSON.stringify(b))
    expect(a.evidenceHash).toBe(b.evidenceHash)
    expect(a.sourceKind).toBe('video_transcript')
  })

  // 跨来源类型，哈希不同（source_kind 维度参与哈希）。
  it('webpage and subtitle produce distinct evidence hashes for the same text', () => {
    const wp = evidenceFromWebpageObservation(webpagePayload)
    const sub = evidenceFromSubtitleObservation({ ...subtitlePayload, caption_text: webpagePayload.observation_text })
    expect(wp.evidenceHash).not.toBe(sub.evidenceHash)
  })

  // -------------------------------------------------------------------------
  // D.2 端到端锚点闭合（本任务核心断言）：用归约结果构造事件 → proposal，
  // anchorKind==='evidence' 且 verifyShadowParamsProposalAnchor 返回 { ok: true }。
  // 证明生产者与下游闸门口径一致，而非两套哈希。
  // -------------------------------------------------------------------------
  it('webpage reduction closes the anchor end-to-end (producer == gate)', () => {
    const candidate = evidenceFromWebpageObservation(webpagePayload)
    const ev = buildEvidenceEventFromCandidate(candidate, { sessionId: 's1', proposalId: 'p1' }, observationEnvelope(1, 'h'))
    const proposal = shadowParamsProposalFromEvent(ev)
    expect(proposal.anchorKind).toBe('evidence')
    expect(proposal.anchorVerified).toBe(false)
    expect(verifyShadowParamsProposalAnchor(proposal)).toEqual({ ok: true })
  })

  it('subtitle reduction closes the anchor end-to-end (producer == gate)', () => {
    const candidate = evidenceFromSubtitleObservation(subtitlePayload)
    const ev = buildEvidenceEventFromCandidate(candidate, { sessionId: 's2', proposalId: 'p2' }, observationEnvelope(1, 'h'))
    const proposal = shadowParamsProposalFromEvent(ev)
    expect(proposal.anchorKind).toBe('evidence')
    expect(verifyShadowParamsProposalAnchor(proposal)).toEqual({ ok: true })
  })

  // 显式点出耦合：本模块证据哈希 + 原样 claim_text，复算出的 input_hash 与
  // shadowParamsProposalFromEvent 在归约时复算的 input_hash 逐位一致。
  it('self-consistency: evidenceProposalInputHash matches the proposal inputHash bit-for-bit', () => {
    const candidate = evidenceFromWebpageObservation(webpagePayload)
    const expected = computeLearningInputHash('s1', 'p1', {
      evidence_hash: candidate.evidenceHash,
      claim_text: candidate.claimText,
    })
    const ev = buildEvidenceEventFromCandidate(candidate, { sessionId: 's1', proposalId: 'p1' }, observationEnvelope(1, 'h'))
    const proposal = shadowParamsProposalFromEvent(ev)
    expect(proposal.inputHash).toBe(expected)
    expect(proposal.evidenceHash).toBe(candidate.evidenceHash)
    expect(proposal.claimText).toBe(candidate.claimText)
  })

  // -------------------------------------------------------------------------
  // D.3 闸门非恒真：把产出的 claim_text 改一个字符（input_hash 不变）⇒ 必须 ok:false。
  // -------------------------------------------------------------------------
  it('gate is not a tautology: tampering claim_text (input_hash unchanged) is rejected', () => {
    const candidate = evidenceFromWebpageObservation(webpagePayload)
    const ev = buildEvidenceEventFromCandidate(candidate, { sessionId: 's1', proposalId: 'p1' }, observationEnvelope(1, 'h'))
    const proposal = shadowParamsProposalFromEvent(ev)
    expect(verifyShadowParamsProposalAnchor(proposal).ok).toBe(true)
    const tampered = { ...proposal, claimText: `${proposal.claimText}x` }
    const res = verifyShadowParamsProposalAnchor(tampered)
    expect(res.ok).toBe(false)
    expect(res.ok === false && res.reason).toContain('evidence input_hash mismatch')
  })

  // -------------------------------------------------------------------------
  // D.5 退化输入必须有明确行为：本任务选「拒绝」（抛错），而不是产出空证据。
  // -------------------------------------------------------------------------
  it('rejects a webpage observation with empty observation_text', () => {
    expect(() => evidenceFromWebpageObservation({ ...webpagePayload, observation_text: '' })).toThrow()
  })
  it('rejects a webpage observation with empty spans', () => {
    expect(() => evidenceFromWebpageObservation({ ...webpagePayload, spans: [] })).toThrow()
  })
  it('rejects a subtitle observation with empty caption_text', () => {
    expect(() => evidenceFromSubtitleObservation({ ...subtitlePayload, caption_text: '' })).toThrow()
  })
  it('rejects a subtitle observation with empty time_spans', () => {
    expect(() => evidenceFromSubtitleObservation({ ...subtitlePayload, time_spans: [] })).toThrow()
  })

  // -------------------------------------------------------------------------
  // D.6 归约出的提案经 decidePgc 后，高疲劳/低 w 场景使其 commit_reason !== 'committed'
  // （证明门控真会拒，而不是恒提交）。
  // -------------------------------------------------------------------------
  it('the reduced evidence proposal is actually rejected by decidePgc under high fatigue / low w', () => {
    const candidate = evidenceFromWebpageObservation(webpagePayload)
    const ev = buildEvidenceEventFromCandidate(candidate, { sessionId: 's1', proposalId: 'p1' }, observationEnvelope(1, 'h'))
    const proposal = shadowParamsProposalFromEvent(ev)
    const candidateWrite = shadowProposalAsPgcCandidate(proposal)
    const decision = decidePgc({
      session_id: 's1',
      trace_id: 't1',
      pgc_policy_version: 'pgc_policy_v1',
      candidate_memory_writes: [candidateWrite],
      pgc_read_context: {
        now: 1,
        last_n_events: [{ topic: 'aijade.learning.proposed.evidence' }],
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
    expect([
      'w_max_below_theta',
      'contradiction_high',
      'evidence_insufficient',
      'fatigue_deferred',
      'w_below_theta',
    ]).toContain(reason)
  })
})

// ===========================================================================
// D.4 processVideoObservation 产出的 envelope 同时含 tick 与 causality.inputHash，
// 且等于传入值；assertV10RequiredFields 对其通过。
// ===========================================================================
describe('processVideoObservation (A 路归约入口)', () => {
  function runtime() {
    const artifacts: unknown[] = []
    return {
      runtime: new V9CausalRuntime({
        readLatestPgcState: async () => undefined,
        persist: async (a) => {
          artifacts.push(a)
        },
      }),
      artifacts,
    }
  }

  it('emits a v10 learning.evidence event carrying tick + causality propagated from the video observation input', async () => {
    const { runtime: rt, artifacts } = runtime()
    const tick = 7
    const inputHash = 'vid-input-hash-123'
    const result = await rt.processVideoObservation({
      eventId: 'e-vid',
      sessionId: 's-vid',
      traceId: 't-vid',
      correlationId: 'c-vid',
      timestamp: 11,
      originDevice: 'pixel-9-pro',
      privacyLevel: 3,
      riskScore: 0.42,
      tick,
      inputHash,
      proposalId: 'prop-1',
      event: webpageObservationEvent(tick, inputHash),
    })

    expect(artifacts).toHaveLength(1)
    const learningEvents = result.artifact.events.filter(e => e.topic === 'aijade.learning.proposed.evidence')
    expect(learningEvents.length).toBe(1)
    const le = learningEvents[0]!
    // tick / causality 由输入 video 观察事件传播而来，不是运行时发明。
    expect(le.tick).toBe(tick)
    expect(le.causality).toEqual({ inputHash })
    expect(le.origin_device).toBe('pixel-9-pro')

    // 通过 v10 必填字段校验（证明它可被 HTTP 边界接受）。
    expect(() => assertV10RequiredFields(le)).not.toThrow()

    // 产出的提案确实是 evidence 锚点、且闸门接受。
    expect(result.proposal.anchorKind).toBe('evidence')
    expect(verifyShadowParamsProposalAnchor(result.proposal)).toEqual({ ok: true })
  })

  it('reduces a subtitle observation end-to-end through processVideoObservation', async () => {
    const { runtime: rt } = runtime()
    const tick = 9
    const inputHash = 'vid-input-hash-456'
    const result = await rt.processVideoObservation({
      eventId: 'e-sub',
      sessionId: 's-sub',
      traceId: 't-sub',
      correlationId: 'c-sub',
      timestamp: 12,
      originDevice: 'tablet-2',
      privacyLevel: 2,
      riskScore: 0.1,
      tick,
      inputHash,
      proposalId: 'prop-2',
      event: subtitleObservationEvent(tick, inputHash),
    })
    const le = result.artifact.events.find(e => e.topic === 'aijade.learning.proposed.evidence')!
    expect(le.tick).toBe(tick)
    expect(le.causality).toEqual({ inputHash })
    expect(result.proposal.anchorKind).toBe('evidence')
    expect(verifyShadowParamsProposalAnchor(result.proposal)).toEqual({ ok: true })
  })

  it('rejects an unsupported video observation topic', async () => {
    const { runtime: rt } = runtime()
    const bogus = { ...webpageObservationEvent(1, 'h'), topic: 'aijade.active_learning.requested' } as AijadeEvent
    await expect(rt.processVideoObservation({
      eventId: 'e-x',
      sessionId: 's-x',
      traceId: 't-x',
      correlationId: 'c-x',
      timestamp: 1,
      originDevice: 'd',
      privacyLevel: 1,
      riskScore: 0,
      tick: 1,
      inputHash: 'h',
      proposalId: 'p-x',
      event: bogus,
    })).rejects.toThrow(/unsupported video observation topic/)
  })
})
