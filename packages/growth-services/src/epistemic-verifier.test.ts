import type { SourceRecord } from '@proj-aijade/memory-biomimetic'

import { validateClaimMap } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { EpistemicVerifier } from './epistemic-verifier'
import { InMemoryStorage } from './in-memory'
import { FixedScheduler } from './test-helpers'

function mkSource(id: string, sourceType: string, reliability = 0.7): SourceRecord {
  return {
    id,
    schema: 'aijade.source_record@1',
    locator: `https://example.com/${id}`,
    sourceType,
    quality: { reliability, independence: 0.8, directness: 0.6, recency: 0.7, reproducibility: 0.6 },
    upstreamRefs: [],
    contentHash: `h_${id}`,
    fetchedAt: 1_700_000_000_000,
  }
}

function makeService() {
  return new EpistemicVerifier(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('epistemicVerifier', () => {
  it('produces a ClaimMap that passes validateClaimMap and a [0,1] confidence', async () => {
    const svc = makeService()
    const res = await svc.verify({
      sources: [mkSource('s1', 'web'), mkSource('s2', 'paper')],
      questRef: 'q-1',
      proposition: 'birds migrate south',
    })
    expect(validateClaimMap(res.claimMap).ok).toBe(true)
    expect(res.confidence).toBeGreaterThanOrEqual(0)
    expect(res.confidence).toBeLessThanOrEqual(1)
    // at least the proposition claim names a support source (§6)
    expect(res.claimMap.claims[0]!.supportSourceRefs.length).toBeGreaterThan(0)
  })

  it('calls the kernel and produces a non-empty provenance trace', async () => {
    const svc = makeService()
    const res = await svc.verify({
      sources: [mkSource('s1', 'web')],
      questRef: 'q-1',
    })
    expect(res.traceChain.length).toBeGreaterThan(0)
    expect(res.independentOriginCount).toBe(1)
  })

  it('rejects empty sources (boundary: §6 traceability)', async () => {
    const svc = makeService()
    await expect(svc.verify({ sources: [], questRef: 'q-1' })).rejects.toThrow(/ClaimMap rejected/)
  })

  it('filters model summaries out of independent evidence', async () => {
    const svc = makeService()
    const res = await svc.verify({
      sources: [mkSource('s1', 'web'), mkSource('s2', 'model')],
      questRef: 'q-1',
    })
    // the model summary cannot count as independent evidence
    expect(res.effectiveIndependentCount).toBe(1)
  })
})
