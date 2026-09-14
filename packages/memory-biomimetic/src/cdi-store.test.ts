import type { Appraisal, FeedbackEvent } from './contracts'

import { describe, expect, it } from 'vitest'

import { DEFAULT_HAC_CONFIG } from './hac'
import { DEFAULT_CDI_CONFIG } from './identity'
import { InMemoryStorageAdapter } from './storage'
import { BioticMemory } from './store'
import { DEFAULT_MEMORY_CONFIG } from './types'

/**
 * Closed-loop config: HAC+CDI on, and minIndependentEpisodes relaxed to 1 so a
 *  single-feedback candidate is admissible in the test (the §11.2 guard is still
 *  exercised by the constitutional/agent test).
 */
function loopConfig() {
  return {
    ...DEFAULT_MEMORY_CONFIG,
    hac: { ...DEFAULT_HAC_CONFIG, enabled: true },
    cdi: { ...DEFAULT_CDI_CONFIG, minIndependentEpisodes: 1 },
  }
}

describe('cdi integration in store (§11, opt-in)', () => {
  it('is absent unless the closed loop is enabled', () => {
    const m = new BioticMemory()
    expect(m.cdiState()).toBeUndefined()
    expect(m.cdiFromFeedback(mkFeedback(), {
      episodeId: 'ep1',
      layer: 'character',
      paramKey: 'curiosity',
      deltaValue: 0.1,
    })).toBeUndefined()
    expect(m.cdiObserveHac('ep1')).toBeUndefined()
  })

  it('applies a feedback-derived identity change when enabled', () => {
    const m = new BioticMemory(loopConfig())
    const r = m.cdiFromFeedback(mkFeedback('f1'), {
      episodeId: 'ep1',
      layer: 'character',
      paramKey: 'curiosity',
      deltaValue: 0.1,
    })
    expect(r?.ok).toBe(true)
    expect(m.cdiState()?.character.curiosity).toBeCloseTo(0.6, 6)
    expect(m.cdiVersions()).toHaveLength(1)
    // the candidate is also retrievable for shadow eval before commit
    expect(m.cdiProposalFromFeedback(mkFeedback('f2'), {
      episodeId: 'ep2',
      layer: 'character',
      paramKey: 'curiosity',
      deltaValue: 0.1,
    })?.candidateId).toBe('fb_f2')
  })

  it('rejects a constitutional change proposed by an agent (§11.1)', () => {
    const m = new BioticMemory(loopConfig())
    const r = m.cdiFromFeedback(mkFeedback('f1'), {
      episodeId: 'ep1',
      layer: 'constitutional',
      paramKey: 'userConsent',
      deltaValue: 0.1,
      proposedBy: 'agent',
    })
    expect(r?.ok).toBe(false)
  })

  it('produces HAC→CDI evidence after an appraisal step', () => {
    const m = new BioticMemory(loopConfig())
    m.stepHacAppraisal(mkAppraisal())
    const ev = m.cdiObserveHac('ep1')
    expect(ev).toBeDefined()
    expect(ev!.source).toBe('world')
    expect(ev!.kind).toBe('observation')
    expect(ev!.traceable).toBe(true)
  })

  it('persists identity across rehydration (§26 + §11) via the storage adapter', () => {
    const adapter = new InMemoryStorageAdapter()
    const m1 = new BioticMemory({ ...loopConfig(), storage: adapter })
    m1.cdiFromFeedback(mkFeedback('f1'), { episodeId: 'ep1', layer: 'character', paramKey: 'curiosity', deltaValue: 0.1 })
    m1.cdiFromFeedback(mkFeedback('f2'), { episodeId: 'ep2', layer: 'character', paramKey: 'curiosity', deltaValue: 0.1 })

    const m2 = new BioticMemory({ ...loopConfig(), storage: adapter })
    expect(m2.cdiState()?.character.curiosity).toBeCloseTo(0.7, 6)
    expect(m2.cdiVersions()).toHaveLength(2)
  })
})

function mkFeedback(id = 'f1'): FeedbackEvent {
  return {
    id,
    schema: 'aijade.feedback_event@1',
    agentId: 'agent-01',
    userScope: 'user-01',
    sessionId: 'session-01',
    targetRef: 'mem-1',
    type: 'explicit',
    signal: 'rating',
    value: 4,
    valence: 0.5,
    timestamp: 1000,
  }
}

function mkAppraisal(): Appraisal {
  return {
    id: 'a1',
    schema: 'aijade.appraisal@1',
    eventRef: 'e1',
    agentId: 'agent-01',
    userScope: 'user-01',
    dimensions: { valence: 0, arousal: 1, goalRelevance: 0.5, novelty: 0.5, control: 0, urgency: 0.5 },
    confidence: 1,
    appraisedBy: 'agent',
    appraisedAt: 0,
  }
}
