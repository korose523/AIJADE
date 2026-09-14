import type { InterestComponents } from './dive'

import { describe, expect, it } from 'vitest'

import {
  DEFAULT_INTEREST_WEIGHTS,
  intrinsicValue,
  nextInterestStatus,
  selectPortfolio,
} from './dive'

function comp(over: Partial<InterestComponents> = {}): InterestComponents {
  return {
    novelty: 0.5,
    knowledgeGap: 0.5,
    identityRelevance: 0.5,
    challenge: 0.5,
    userRelevance: 0.5,
    futureUtility: 0.5,
    cost: 0.5,
    risk: 0.5,
    repetitionPenalty: 0.5,
    ...over,
  }
}

describe('dIVE — intrinsicValue (§47.1)', () => {
  it('is higher with more novelty/gap and lower with more cost/risk', () => {
    // keep both values inside (0,1) so the comparison is not clamped away
    const base = { identityRelevance: 0, challenge: 0, userRelevance: 0, futureUtility: 0, repetitionPenalty: 0 }
    const attractive = intrinsicValue(comp({ ...base, novelty: 0.4, knowledgeGap: 0.3, cost: 0, risk: 0 }))
    const inhibited = intrinsicValue(comp({ ...base, novelty: 0.4, knowledgeGap: 0.3, cost: 0.5, risk: 0.5 }))
    expect(attractive).toBeGreaterThan(inhibited)
    expect(inhibited).toBe(0)
  })
  it('is clamped to [0,1]', () => {
    expect(intrinsicValue(comp({ novelty: 1, knowledgeGap: 1, identityRelevance: 1, challenge: 1, userRelevance: 1, futureUtility: 1, cost: 0, risk: 0, repetitionPenalty: 0 }))).toBeLessThanOrEqual(1)
    expect(intrinsicValue(comp({ novelty: 0, knowledgeGap: 0, identityRelevance: 0, challenge: 0, userRelevance: 0, futureUtility: 0, cost: 1, risk: 1, repetitionPenalty: 1 }))).toBe(0)
  })
  it('both attraction and inhibition are mandatory (not novelty-only)', () => {
    // pure novelty with heavy inhibition must score below balanced moderate value
    const noveltyOnly = intrinsicValue(comp({ novelty: 1, knowledgeGap: 0, identityRelevance: 0, challenge: 0, userRelevance: 0, futureUtility: 0, cost: 0.8, risk: 0.8, repetitionPenalty: 0.8 }))
    const balanced = intrinsicValue(comp({ novelty: 0.6, knowledgeGap: 0.6, identityRelevance: 0.6, challenge: 0.5, userRelevance: 0.5, futureUtility: 0.5, cost: 0.2, risk: 0.2, repetitionPenalty: 0.2 }))
    expect(balanced).toBeGreaterThan(noveltyOnly)
  })
  it('weights shape the result (risk-weighted engine penalises risk harder)', () => {
    const risky = comp({ risk: 1, cost: 0, repetitionPenalty: 0 })
    const hi = intrinsicValue(risky, { ...DEFAULT_INTEREST_WEIGHTS, wRisk: 5 })
    const lo = intrinsicValue(risky, { ...DEFAULT_INTEREST_WEIGHTS, wRisk: 0.1 })
    expect(hi).toBeLessThan(lo)
  })
})

describe('dIVE — nextInterestStatus lifecycle (§47.2)', () => {
  it('seed → latent', () => {
    expect(nextInterestStatus('active', 'seed')).toBe('latent')
  })
  it('probe/deepen/revisit keep a live thread active', () => {
    expect(nextInterestStatus('latent', 'probe')).toBe('active')
    expect(nextInterestStatus('active', 'deepen')).toBe('active')
    expect(nextInterestStatus('incubating', 'revisit')).toBe('active')
  })
  it('incubate only from active', () => {
    expect(nextInterestStatus('active', 'incubate')).toBe('incubating')
    expect(nextInterestStatus('latent', 'incubate')).toBeNull()
  })
  it('satisfy/saturate from active or incubating', () => {
    expect(nextInterestStatus('active', 'satisfy')).toBe('satisfied')
    expect(nextInterestStatus('incubating', 'saturate')).toBe('satisfied')
    expect(nextInterestStatus('latent', 'satisfy')).toBeNull()
  })
  it('abandon from any non-terminal state; terminal states reject further moves', () => {
    expect(nextInterestStatus('active', 'abandon')).toBe('abandoned')
    expect(nextInterestStatus('incubating', 'abandon')).toBe('abandoned')
    expect(nextInterestStatus('satisfied', 'abandon')).toBeNull()
    expect(nextInterestStatus('abandoned', 'probe')).toBeNull()
  })
})

describe('dIVE — selectPortfolio (§47.4)', () => {
  function c(id: string, subject: string, intrinsicValue: number, identityRelevance = 0.3, userRelevance = 0.7) {
    return { thread: { id, subject, intrinsicValue, identityRelevance, userRelevance } }
  }

  it('respects the budget', () => {
    const sel = selectPortfolio([c('1', 'a', 0.9), c('2', 'b', 0.8), c('3', 'c', 0.7)], { budget: 2, identityReserve: 0 })
    expect(sel.selected.length).toBeLessThanOrEqual(2)
  })

  it('hard-excludes forbidden subjects regardless of value', () => {
    const sel = selectPortfolio([c('1', 'crypto', 0.99), c('2', 'bci', 0.5)], { budget: 2, identityReserve: 0, forbiddenSubjects: ['crypto'] })
    expect(sel.forbidden).toEqual(['1'])
    expect(sel.selected).not.toContain('1')
    expect(sel.selected).toContain('2')
  })

  it('reserves budget for identity-linked (non-sycophantic) exploration', () => {
    // identity-linked: high identityRelevance, low userRelevance
    const identityCand = c('id1', 'agent-history', 0.5, 0.9, 0.1)
    const userCand = c('u1', 'user-task', 0.9, 0.2, 0.9)
    const sel = selectPortfolio([userCand, identityCand], { budget: 2, identityReserve: 0.5 })
    expect(sel.identityReserved).toEqual(['id1'])
    expect(sel.selected).toContain('id1')
    expect(sel.selected).toContain('u1')
  })

  it('diversity bonus prefers a novel subject over a redundant one', () => {
    const sel = selectPortfolio(
      [c('1', 'bci', 0.9), c('2', 'bci', 0.85), c('3', 'neuro', 0.8)],
      { budget: 2, identityReserve: 0, diversityWeight: 0.5, redundancyWeight: 0.5 },
    )
    // after picking 'bci'(#1), the next pick should favour the novel 'neuro' over redundant 'bci'
    expect(sel.selected).toContain('1')
    expect(sel.selected).toContain('3')
    expect(sel.selected).not.toContain('2')
  })
})
