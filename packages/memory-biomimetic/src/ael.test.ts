import type { QuestState } from './ael'
import type { SourceRecord } from './contracts-v8'

import { describe, expect, it } from 'vitest'

import {
  canBeIndependentEvidence,
  canBeSystemInstruction,
  evidenceConfidence,
  independentOriginCount,
  planSources,
  QUEST_PIPELINE,
  sharedOriginClusters,
  transitionQuest,
} from './ael'

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
