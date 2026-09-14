import type { EvaluationEvidencePack, EvolutionProposal } from '@proj-aijade/memory-biomimetic'

import { validateSignedRelease } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemorySigning, InMemoryStorage } from './in-memory'
import { FixedScheduler } from './test-helpers'
import { TrustedReleaseController } from './trusted-release-controller'

function makeService() {
  return new TrustedReleaseController(
    {
      storage: new InMemoryStorage(),
      scheduler: new FixedScheduler(1_700_000_000_000),
      signing: new InMemorySigning(),
    },
    'agent-1',
    'scope-1',
  )
}

function proposal(): EvolutionProposal {
  return {
    id: 'ep-1',
    schema: 'aijade.evolution_proposal@1',
    agentId: 'a',
    triggerEvidence: [],
    affectedComponents: ['x'],
    grade: 'E2',
    baselineVersion: 'v1',
    changeSpec: 'change',
    sourceDiff: 'diff',
    generatedBy: 'agent',
    tests: [{ kind: 'contract_property', passed: true }],
    rollbackPlan: 'rollback plan',
    approvalPolicy: 'agent_self_review',
    signature: 'sig_abc',
    createdAt: 1,
  }
}

function pack(): EvaluationEvidencePack {
  return {
    id: 'evp-1',
    schema: 'aijade.evaluation_evidence_pack@1',
    proposalRef: 'ep-1',
    unitContractPropertyTests: { passed: true, total: 1, failed: 0 },
    createdAt: 1,
  }
}

describe('trustedReleaseController', () => {
  it('signs a release when proposal + evidence pack are valid (kernel canPromote gates)', async () => {
    const svc = makeService()
    const res = await svc.release({ proposal: proposal(), evidencePack: pack() })
    expect(res.ok).toBe(true)
    expect(res.release).toBeDefined()
    expect(validateSignedRelease(res.release!).ok).toBe(true)
    expect(res.release!.canaryRatio).toBeGreaterThanOrEqual(0)
    expect(res.release!.canaryRatio).toBeLessThanOrEqual(1)
  })

  it('blocks promotion when the core test gate fails (boundary: canPromote)', async () => {
    const svc = makeService()
    const bad = pack()
    bad.unitContractPropertyTests = { passed: false, total: 1, failed: 1 }
    const res = await svc.release({ proposal: proposal(), evidencePack: bad })
    expect(res.ok).toBe(false)
    expect(res.reason).toMatch(/promotion blocked/)
  })

  it('blocks a proposal missing a rollback plan (boundary: §51.3)', async () => {
    const svc = makeService()
    const p = proposal()
    p.rollbackPlan = ''
    const res = await svc.release({ proposal: p, evidencePack: pack() })
    expect(res.ok).toBe(false)
  })

  it('rejects an invalid evidence pack (boundary: failed > total)', async () => {
    const svc = makeService()
    const bad = pack()
    bad.unitContractPropertyTests = { passed: true, total: 0, failed: 5 }
    const res = await svc.release({ proposal: proposal(), evidencePack: bad })
    expect(res.ok).toBe(false)
    expect(res.reason).toMatch(/evidence pack invalid/)
  })
})
