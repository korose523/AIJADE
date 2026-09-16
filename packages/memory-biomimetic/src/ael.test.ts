import type { QuestState } from './ael'
import type { LearningQuest, SourceRecord } from './contracts-v8'

import { describe, expect, it } from 'vitest'

import {
  ACTIVE_LEARNING_REQUEST_EDGE,
  buildActiveLearningCompletedEvent,
  buildActiveLearningRequestedEvent,
  canBeIndependentEvidence,
  canBeSystemInstruction,
  evidenceConfidence,
  independentOriginCount,
  planSources,
  QUEST_PIPELINE,
  sharedOriginClusters,
  shouldCompleteActiveLearning,
  shouldRequestActiveLearning,
  transitionQuest,
} from './ael'
import { AIJADE_TOPICS, safeParseAijadeEvent } from './events'

function src(id: string, over: Partial<SourceRecord> = {}): SourceRecord {
  return {
    id,
    schema: 'aijade.source_record@1',
    locator: `https://example.com/${id}`,
    sourceType: 'paper',
    quality: { reliability: 0.8, independence: 0.8, directness: 0.8, recency: 0.8, reproducibility: 0.8 },
    upstreamRefs: [],
    contentHash: `hash-${id}`,
    fetchedAt: 1000,
    ...over,
  }
}

describe('aEL — quest state machine (§48.1)', () => {
  it('advances through the full pipeline in order', () => {
    let s: QuestState = { stage: 'OBSERVE' }
    for (let i = 1; i < QUEST_PIPELINE.length; i++) {
      const next = transitionQuest(s, 'advance')
      expect(next).not.toBeNull()
      expect(next!.stage).toBe(QUEST_PIPELINE[i])
      s = next!
    }
    expect(s.stage).toBe('REFLECT')
    // advancing past REFLECT completes (no further state)
    expect(transitionQuest(s, 'advance')).toBeNull()
  })

  it('pause then resume returns to the resume point', () => {
    const paused = transitionQuest({ stage: 'SEARCH' }, 'pause')
    expect(paused).toEqual({ stage: 'PAUSED', resumePoint: 'SEARCH' })
    const resumed = transitionQuest(paused!, 'resume')
    expect(resumed).toEqual({ stage: 'SEARCH' })
  })

  it('need_consent then grant_consent resumes; resume without consent point fails', () => {
    const nc = transitionQuest({ stage: 'ACQUIRE' }, 'need_consent')
    expect(nc).toEqual({ stage: 'NEEDS_USER_CONSENT', resumePoint: 'ACQUIRE' })
    expect(transitionQuest(nc!, 'grant_consent')).toEqual({ stage: 'ACQUIRE' })
    // grant_consent only valid from NEEDS_USER_CONSENT
    expect(transitionQuest({ stage: 'SEARCH' }, 'grant_consent')).toBeNull()
  })

  it('contradict is resumable after resolution', () => {
    const c = transitionQuest({ stage: 'CROSS_VALIDATE' }, 'contradict')
    expect(c).toEqual({ stage: 'CONTRADICTED', resumePoint: 'CROSS_VALIDATE' })
    expect(transitionQuest(c!, 'resume')).toEqual({ stage: 'CROSS_VALIDATE' })
  })

  it('fail and abandon are terminal (no further events)', () => {
    const f = transitionQuest({ stage: 'SEARCH' }, 'fail')
    expect(f).toEqual({ stage: 'FAILED' })
    expect(transitionQuest(f!, 'advance')).toBeNull()
    const a = transitionQuest({ stage: 'SEARCH' }, 'abandon')
    expect(transitionQuest(a!, 'resume')).toBeNull()
  })

  it('illegal events return null', () => {
    expect(transitionQuest({ stage: 'SEARCH' }, 'resume')).toBeNull()
    expect(transitionQuest({ stage: 'PAUSED', resumePoint: 'SEARCH' }, 'advance')).toBeNull()
  })
})

describe('aEL — evidenceConfidence (§48.5)', () => {
  const full = { reliability: 1, independence: 1, directness: 1, recency: 1, reproducibility: 1, counterEvidence: 0 }
  it('high quality + no counter-evidence → high confidence', () => {
    // support weights sum to 0.9, so the maximum confidence is exactly 0.9
    expect(evidenceConfidence(full)).toBeCloseTo(0.9, 5)
  })
  it('counter-evidence lowers confidence', () => {
    expect(evidenceConfidence({ ...full, counterEvidence: 0.8 })).toBeLessThan(evidenceConfidence(full))
  })
  it('is clamped to [0,1]', () => {
    expect(evidenceConfidence({ reliability: 0, independence: 0, directness: 0, recency: 0, reproducibility: 0, counterEvidence: 1 })).toBe(0)
    expect(evidenceConfidence(full)).toBeLessThanOrEqual(1)
  })
})

describe('aEL — planSources (§48.3)', () => {
  it('academic wants papers + reproductions with cross-validation', () => {
    const p = planSources('academic')
    expect(p.sourceTypes).toContain('paper')
    expect(p.sourceTypes).toContain('reproduction_code')
    expect(p.crossValidate).toBe(true)
  })
  it('subjective/cultural preserves multiple perspectives without forcing a single truth', () => {
    const p = planSources('subjective_culture')
    expect(p.preservePerspectives).toBe(true)
    expect(p.crossValidate).toBe(false)
  })
  it('technical wants docs + code + history', () => {
    const p = planSources('technical')
    expect(p.sourceTypes).toContain('official_doc')
    expect(p.sourceTypes).toContain('source_code')
  })
})

describe('aEL — epistemic quarantine (§48.4)', () => {
  it('only system content may be a system instruction', () => {
    expect(canBeSystemInstruction('system')).toBe(true)
    expect(canBeSystemInstruction('web')).toBe(false)
    expect(canBeSystemInstruction('model')).toBe(false)
    expect(canBeSystemInstruction('tool')).toBe(false)
  })
  it('a model summary is never its own independent evidence', () => {
    expect(canBeIndependentEvidence('model', true)).toBe(false)
    expect(canBeIndependentEvidence('web', false)).toBe(true)
  })
})

describe('aEL — shared-origin detection (§48.4)', () => {
  it('reposts with identical content hash count as one origin', () => {
    const a = src('a', { contentHash: 'same' })
    const b = src('b', { contentHash: 'same' })
    const c = src('c', { contentHash: 'other' })
    expect(independentOriginCount([a, b, c])).toBe(2)
  })
  it('sources sharing an upstream ref count as one origin', () => {
    const a = src('a', { upstreamRefs: ['root'] })
    const b = src('b', { upstreamRefs: ['root'] })
    expect(independentOriginCount([a, b])).toBe(1)
  })
  it('clusters are returned grouped', () => {
    const a = src('a', { contentHash: 'x' })
    const b = src('b', { contentHash: 'x' })
    const clusters = sharedOriginClusters([a, b])
    expect(clusters.some(cl => cl.includes('a') && cl.includes('b'))).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// §48.2 lifecycle edges → 统一事件（v9 §3）
// ---------------------------------------------------------------------------

function quest(over: Partial<LearningQuest> = {}): LearningQuest {
  return {
    id: 'q1',
    schema: 'aijade.learning_quest@1',
    agentId: 'agent-1',
    userScope: 'user-1',
    interestThreadRef: 'it1',
    researchQuestion: 'PGC 消融是否改变 recall@K？',
    operationalDefinition: '同一语料下 K=10 的命中率差',
    priorBeliefs: [],
    expectedInformationGain: 0.5,
    sourcePlan: { questionType: 'academic', sourceTypes: ['paper'], maxSources: 5 },
    resourceBudget: { allocated: 10, spent: 0, unit: 'queries' },
    privacyClass: 'public',
    stopConditions: ['信息增益低于阈值'],
    successCriteria: ['结论可复现'],
    deliverables: ['claim_map'],
    experimentManifestRef: 'em1',
    status: 'active',
    createdAt: 1,
    ...over,
  }
}

const ENVELOPE = {
  event_id: 'evt_ael_1',
  trace_id: 'tr_ael_1',
  correlation_id: 'cor_ael_1',
  timestamp: 1_700_000_000_000,
  producer: 'ael',
  idempotency_key: 'idem_ael_1',
  replay_mode: 'live' as const,
  risk_level: 'low' as const,
}

describe('aEL — 请求边/完成边判定', () => {
  it('只有 SCOPE_AND_BUDGET → PLAN_SOURCES 是请求边', () => {
    expect(shouldRequestActiveLearning('SCOPE_AND_BUDGET', 'PLAN_SOURCES')).toBe(true)
  })

  it('进入 SCOPE_AND_BUDGET 不算请求边（此刻预算尚未落定）', () => {
    expect(shouldRequestActiveLearning('FORM_QUESTION', 'SCOPE_AND_BUDGET')).toBe(false)
  })

  it('fORM_QUESTION 上不发（此刻没有资源预算/停止条件）', () => {
    expect(shouldRequestActiveLearning('OBSERVE', 'FORM_QUESTION')).toBe(false)
  })

  it('请求边常量本身指向预算阶段之后的第一次推进', () => {
    expect(ACTIVE_LEARNING_REQUEST_EDGE.from).toBe('SCOPE_AND_BUDGET')
    expect(ACTIVE_LEARNING_REQUEST_EDGE.to).toBe('PLAN_SOURCES')
    expect(QUEST_PIPELINE.indexOf(ACTIVE_LEARNING_REQUEST_EDGE.to))
      .toBe(QUEST_PIPELINE.indexOf(ACTIVE_LEARNING_REQUEST_EDGE.from) + 1)
  })

  it('完成边 = REFLECT 上 advance 返回 null（由 transitionQuest 自己定义）', () => {
    expect(shouldCompleteActiveLearning('REFLECT', null)).toBe(true)
    expect(shouldCompleteActiveLearning('REFLECT', 'SHARE_OR_INCUBATE')).toBe(false)
  })

  it('fail / abandon 不算完成（否则事件名会说谎）', () => {
    expect(shouldCompleteActiveLearning('FAILED', null)).toBe(false)
    expect(shouldCompleteActiveLearning('ABANDONED', null)).toBe(false)
  })

  it('完整走一遍流水线：requested 恰好 1 次、completed 恰好 1 次', () => {
    let s: QuestState = { stage: 'OBSERVE' }
    let requested = 0
    let completed = 0
    for (let guard = 0; guard < QUEST_PIPELINE.length + 4; guard++) {
      const next = transitionQuest(s, 'advance')
      const to = next === null ? null : next.stage
      if (shouldRequestActiveLearning(s.stage, to))
        requested++
      if (shouldCompleteActiveLearning(s.stage, to))
        completed++
      if (next === null)
        break
      s = next
    }
    expect(requested).toBe(1)
    expect(completed).toBe(1)
  })

  it('在预算阶段 pause/resume 一次不会重复发射', () => {
    let s: QuestState = { stage: 'FORM_QUESTION' }
    let requested = 0
    // 推进到 SCOPE_AND_BUDGET
    let next = transitionQuest(s, 'advance')!
    expect(next.stage).toBe('SCOPE_AND_BUDGET')
    s = next
    // 暂停再恢复（回到同一阶段）
    const paused = transitionQuest(s, 'pause')!
    s = transitionQuest(paused, 'resume')!
    expect(s.stage).toBe('SCOPE_AND_BUDGET')
    // 再推进：这才第一次也是唯一一次穿过请求边
    next = transitionQuest(s, 'advance')!
    if (shouldRequestActiveLearning(s.stage, next.stage))
      requested++
    // 继续走完，看是否再触发
    s = next
    for (let guard = 0; guard < QUEST_PIPELINE.length + 4; guard++) {
      const n = transitionQuest(s, 'advance')
      if (shouldRequestActiveLearning(s.stage, n === null ? null : n.stage))
        requested++
      if (n === null)
        break
      s = n
    }
    expect(requested).toBe(1)
  })
})

describe('aEL — 事件构造（先校验后发射）', () => {
  it('合法 quest ⇒ 产出合法事件，topic 属于登记集合', () => {
    const ev = buildActiveLearningRequestedEvent(quest(), 'session-1', ENVELOPE)
    expect(ev.topic).toBe('aijade.active_learning.requested')
    expect((AIJADE_TOPICS as readonly string[]).includes(ev.topic)).toBe(true)
    expect(safeParseAijadeEvent(ev).success).toBe(true)
  })

  it('payload 携带 §48.2 的预算与停止条件，且可回指 quest', () => {
    const ev = buildActiveLearningRequestedEvent(quest(), 'session-1', ENVELOPE)
    const p = ev.payload as Record<string, unknown>
    expect(p.quest_ref).toBe('q1')
    expect(p.session_id).toBe('session-1')
    expect(p.stop_conditions).toEqual(['信息增益低于阈值'])
    expect(p.resource_budget).toEqual({ allocated: 10, spent: 0, unit: 'queries' })
  })

  it('requested_at 取自信封 timestamp（不另取时钟 ⇒ 可回放）', () => {
    const ev = buildActiveLearningRequestedEvent(quest(), 'session-1', ENVELOPE)
    expect((ev.payload as { requested_at: number }).requested_at).toBe(ENVELOPE.timestamp)
  })

  it('无停止条件 ⇒ 抛错，而不是发出不可审计的请求', () => {
    expect(() => buildActiveLearningRequestedEvent(quest({ stopConditions: [] }), 'session-1', ENVELOPE)).toThrow(/§48.2/)
  })

  it('预算超额（spent > allocated）⇒ 抛错', () => {
    expect(() => buildActiveLearningRequestedEvent(
      quest({ resourceBudget: { allocated: 5, spent: 6, unit: 'queries' } }),
      'session-1',
      ENVELOPE,
    )).toThrow(/§48.2/)
  })

  it('缺 experimentManifestRef ⇒ 抛错（§48.2 可复现性要求）', () => {
    expect(() => buildActiveLearningRequestedEvent(quest({ experimentManifestRef: '' }), 'session-1', ENVELOPE)).toThrow(/§48.2/)
  })

  it('completed 事件与 requested 同 quest_ref，可配对', () => {
    const ev = buildActiveLearningCompletedEvent(quest(), 'session-1', ENVELOPE)
    expect(ev.topic).toBe('aijade.active_learning.completed')
    expect((ev.payload as Record<string, unknown>).quest_ref).toBe('q1')
    expect(safeParseAijadeEvent(ev).success).toBe(true)
  })

  it('completed 的 result_ref 只在提供时出现（不伪造占位值）', () => {
    const without = buildActiveLearningCompletedEvent(quest(), 'session-1', ENVELOPE)
    expect('result_ref' in (without.payload as Record<string, unknown>)).toBe(false)
    const withRef = buildActiveLearningCompletedEvent(quest(), 'session-1', ENVELOPE, 'ka_1')
    expect((withRef.payload as Record<string, unknown>).result_ref).toBe('ka_1')
  })
})
