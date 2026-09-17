import type { AijadeEvent } from './events'

import { describe, expect, it } from 'vitest'

import {
  AIJADE_TOPICS,
  aijadeEventSchema,
  assertV10RequiredFields,
  buildLearningConstraintOpinionEvaluationEvent,
  buildLearningProposedEvidenceEvent,
  buildLearningProposedShadowParamsEvent,
  buildVideoTranscriptObservationEvent,
  buildWebpageTextObservationEvent,
  learningConstraintOpinionEvaluationSchema,
  learningProposedEvidenceSchema,
  learningProposedShadowParamsSchema,
  videoTranscriptObservationSchema,
  webpageTextObservationSchema,
} from './events'

const validWebpageText = {
  source_url: 'https://example.com/page',
  content_hash: 'sha256:abc',
  spans: [{ start_offset: 0, end_offset: 5, label: 'keyword' }],
  observation_text: '页面观察到某关键词',
}
const validVideoTranscript = {
  video_id: 'vid_1',
  transcript_hash: 'sha256:def',
  time_spans: [{ start_ms: 0, end_ms: 1000, text: '你好' }],
  caption_text: '字幕文本',
}
const validShadowParams = {
  session_id: 's1',
  proposal_id: 'p1',
  render_ref: 'r1',
  applied_params_hash: 'h1',
  asset_version_hash: 'av1',
  input_hash: 'i1',
  candidate_params: { lr: 0.1, layers: 3 },
  confidence: 0.5,
}
const validEvidence = {
  session_id: 's1',
  proposal_id: 'p1',
  render_ref: 'r1',
  applied_params_hash: 'h1',
  asset_version_hash: 'av1',
  evidence_hash: 'e1',
  claim_text: '主张文本',
  confidence: 0.5,
}
const validOpinionEval = {
  evaluation_target: 'target_1',
  claims: [{ claim_text: '主张A', confidence: 0.5 }],
  uncertainty_notes: '存在不确定性',
}

const v10Envelope = {
  event_id: 'evt_1',
  trace_id: 'tr_1',
  correlation_id: 'cor_1',
  timestamp: 1_700_000_000_000,
  producer: 'kernel',
  idempotency_key: 'idem_1',
  replay_mode: 'live' as const,
  risk_level: 'low' as const,
  tick: 1,
  causality: { inputHash: 'input-hash-1' },
}
const v9Envelope = {
  ...v10Envelope,
  tick: undefined,
  causality: undefined,
}

describe('v10 payload schema — 校验通过', () => {
  it('webpage_text 合法 payload 通过', () => {
    expect(webpageTextObservationSchema.parse(validWebpageText).source_url).toBe('https://example.com/page')
  })
  it('video_transcript 合法 payload 通过', () => {
    expect(videoTranscriptObservationSchema.parse(validVideoTranscript).video_id).toBe('vid_1')
  })
  it('shadow_params 合法 payload 通过（含 record 字段）', () => {
    expect(learningProposedShadowParamsSchema.parse(validShadowParams).candidate_params).toEqual({ lr: 0.1, layers: 3 })
  })
  it('evidence 合法 payload 通过', () => {
    expect(learningProposedEvidenceSchema.parse(validEvidence).claim_text).toBe('主张文本')
  })
  it('opinion_evaluation 合法 payload 通过', () => {
    expect(learningConstraintOpinionEvaluationSchema.parse(validOpinionEval).evaluation_target).toBe('target_1')
  })
})

describe('v10 payload schema — 缺字段/空串/越界 抛错', () => {
  it('webpage_text：缺 source_url ⇒ 拒', () => {
    const { source_url: _d, ...rest } = validWebpageText
    expect(webpageTextObservationSchema.safeParse(rest).success).toBe(false)
  })
  it('webpage_text：source_url 空串 ⇒ 拒', () => {
    expect(webpageTextObservationSchema.safeParse({ ...validWebpageText, source_url: '' }).success).toBe(false)
  })
  it('webpage_text：spans 空数组 ⇒ 拒', () => {
    expect(webpageTextObservationSchema.safeParse({ ...validWebpageText, spans: [] }).success).toBe(false)
  })
  it('webpage_text：span.label 空串 ⇒ 拒', () => {
    expect(webpageTextObservationSchema.safeParse({
      ...validWebpageText,
      spans: [{ start_offset: 0, end_offset: 5, label: '' }],
    }).success).toBe(false)
  })
  it('video_transcript：start_ms 为负 ⇒ 拒', () => {
    expect(videoTranscriptObservationSchema.safeParse({
      ...validVideoTranscript,
      time_spans: [{ start_ms: -1, end_ms: 1000, text: 'x' }],
    }).success).toBe(false)
  })
  it('shadow_params：confidence 越界(>1) ⇒ 拒', () => {
    expect(learningProposedShadowParamsSchema.safeParse({ ...validShadowParams, confidence: 1.5 }).success).toBe(false)
  })
  it('shadow_params：confidence 越界(<0) ⇒ 拒', () => {
    expect(learningProposedShadowParamsSchema.safeParse({ ...validShadowParams, confidence: -0.1 }).success).toBe(false)
  })
  it('evidence：缺 evidence_hash ⇒ 拒', () => {
    const { evidence_hash: _d, ...rest } = validEvidence
    expect(learningProposedEvidenceSchema.safeParse(rest).success).toBe(false)
  })
  it('opinion_evaluation：claims 空数组 ⇒ 拒', () => {
    expect(learningConstraintOpinionEvaluationSchema.safeParse({ ...validOpinionEval, claims: [] }).success).toBe(false)
  })
  it('opinion_evaluation：claim confidence 越界 ⇒ 拒', () => {
    expect(learningConstraintOpinionEvaluationSchema.safeParse({
      ...validOpinionEval,
      claims: [{ claim_text: 'x', confidence: 2 }],
    }).success).toBe(false)
  })
})

describe('v10 payload schema — 未知额外字段 抛错（strict）', () => {
  it('webpage_text：payload 含未知字段 ⇒ 拒', () => {
    expect(webpageTextObservationSchema.safeParse({ ...validWebpageText, extra: 1 }).success).toBe(false)
  })
  it('video_transcript：payload 含未知字段 ⇒ 拒', () => {
    expect(videoTranscriptObservationSchema.safeParse({ ...validVideoTranscript, extra: 1 }).success).toBe(false)
  })
  it('shadow_params：payload 含未知字段 ⇒ 拒', () => {
    expect(learningProposedShadowParamsSchema.safeParse({ ...validShadowParams, extra: 1 }).success).toBe(false)
  })
  it('evidence：payload 含未知字段 ⇒ 拒', () => {
    expect(learningProposedEvidenceSchema.safeParse({ ...validEvidence, extra: 1 }).success).toBe(false)
  })
  it('opinion_evaluation：payload 含未知字段 ⇒ 拒', () => {
    expect(learningConstraintOpinionEvaluationSchema.safeParse({ ...validOpinionEval, extra: 1 }).success).toBe(false)
  })
})

describe('v10 工厂 — 合法构造', () => {
  it('buildWebpageTextObservationEvent 返回已 parse 事件', () => {
    const ev = buildWebpageTextObservationEvent(validWebpageText, v10Envelope)
    expect(ev.topic).toBe('aijade.video.observation.webpage_text')
    expect(ev.tick).toBe(1)
    expect(ev.causality?.inputHash).toBe('input-hash-1')
  })
  it('buildVideoTranscriptObservationEvent 返回已 parse 事件', () => {
    const ev = buildVideoTranscriptObservationEvent(validVideoTranscript, v10Envelope)
    expect(ev.topic).toBe('aijade.video.observation.video_transcript')
  })
  it('buildLearningProposedShadowParamsEvent 返回已 parse 事件', () => {
    const ev = buildLearningProposedShadowParamsEvent(validShadowParams, v10Envelope)
    expect(ev.topic).toBe('aijade.learning.proposed.shadow_params')
  })
  it('buildLearningProposedEvidenceEvent 返回已 parse 事件', () => {
    const ev = buildLearningProposedEvidenceEvent(validEvidence, v10Envelope)
    expect(ev.topic).toBe('aijade.learning.proposed.evidence')
  })
  it('buildLearningConstraintOpinionEvaluationEvent 返回已 parse 事件', () => {
    const ev = buildLearningConstraintOpinionEvaluationEvent(validOpinionEval, v10Envelope)
    expect(ev.topic).toBe('aijade.learning.constraint.opinion_evaluation')
  })
})

describe('v10 工厂 — 非法 payload / 缺 tick·causality 抛错', () => {
  it('webpage_text 非法 payload ⇒ 构造即抛错', () => {
    expect(() => buildWebpageTextObservationEvent({ ...validWebpageText, source_url: '' }, v10Envelope)).toThrow()
  })
  it('video/learning 前缀缺 tick ⇒ 抛错', () => {
    expect(() => buildVideoTranscriptObservationEvent(validVideoTranscript, { ...v10Envelope, tick: undefined })).toThrow()
  })
  it('video/learning 前缀缺 causality ⇒ 抛错', () => {
    expect(() => buildLearningProposedShadowParamsEvent(validShadowParams, { ...v10Envelope, causality: undefined })).toThrow()
  })
  it('video/learning 前缀 causality.inputHash 空串 ⇒ 抛错', () => {
    expect(() => buildLearningProposedEvidenceEvent(validEvidence, { ...v10Envelope, causality: { inputHash: '' } })).toThrow()
  })
})

describe('v10 强制校验 — 与边界口径一致', () => {
  it('aijade.video.* / aijade.learning.* 缺 tick·causality ⇒ assertV10RequiredFields 抛错', () => {
    const payloads: Record<string, Record<string, unknown>> = {
      'aijade.video.observation.webpage_text': validWebpageText,
      'aijade.video.observation.video_transcript': validVideoTranscript,
      'aijade.learning.proposed.shadow_params': validShadowParams,
      'aijade.learning.proposed.evidence': validEvidence,
      'aijade.learning.constraint.opinion_evaluation': validOpinionEval,
    }
    for (const topic of Object.keys(payloads)) {
      const ev = aijadeEventSchema.parse({ ...v9Envelope, topic, payload: payloads[topic] }) as AijadeEvent
      expect(() => assertV10RequiredFields(ev), `topic ${topic} 缺 tick/causality 应抛错`).toThrow()
    }
  })
  it('7 个 v9 topic 不带 tick·causality 仍可通过（且 assertV10RequiredFields 不抛）', () => {
    const v9Topics = AIJADE_TOPICS.filter(t => !t.startsWith('aijade.video.') && !t.startsWith('aijade.learning.'))
    expect(v9Topics.length).toBe(7)
    for (const topic of v9Topics) {
      const samplePayloads: Record<string, Record<string, unknown>> = {
        'aijade.active_learning.requested': { session_id: 's', trace_id: 't', requested_at: 1, quest_ref: 'q1', resource_budget: { allocated: 10, spent: 0, unit: 'queries' }, stop_conditions: ['c'] },
        'aijade.active_learning.completed': { session_id: 's', trace_id: 't', completed_at: 2, quest_ref: 'q1' },
        'aijade.evidence.weave_candidate_ready': { tx_id: 'x', weave_id: 'w', graph_hash: 'h', candidate_memory_write_ids: [] },
        'aijade.pgc.write_plan_ready': { pgc_state_id: 'p', write_plan_size: 1, policy_version: 'v1' },
        'aijade.memory_tx.committed': { tx_id: 'x', trace_id: 't', committed_count: 1, rejected_count: 0, throttled_count: 0 },
        'aijade.persona.render_requested': { session_id: 's', persona_snapshot_ref: 'ps1', intent_ref: 'pi1' },
        'aijade.lpm.render_ready': { session_id: 's', render_ref: 'rr1', applied_params_hash: 'h1' },
      }
      const r = aijadeEventSchema.safeParse({ ...v9Envelope, topic, payload: samplePayloads[topic] })
      expect(r.success, `v9 topic ${topic} 应被接受`).toBe(true)
      if (r.success)
        expect(() => assertV10RequiredFields(r.data)).not.toThrow()
    }
  })
})
