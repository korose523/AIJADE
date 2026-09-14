import type { AssociationPath, TransferRecord } from '@proj-aijade/memory-biomimetic'

import { validateAssociationPath, validateTransferRecord } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemoryStorage } from './in-memory'
import { FixedScheduler } from './test-helpers'
import { TransferLab } from './transfer-lab'

function makeService() {
  return new TransferLab(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('transferLab', () => {
  it('proposes a T1 (unvalidated) transfer by default', async () => {
    const svc = makeService()
    const rec = await svc.propose({ sourceDomain: 'math', targetDomain: 'physics' })
    expect(rec.tier).toBe('T1')
    expect(rec.validated).toBe(false)
    expect(validateTransferRecord(rec).ok).toBe(true)
  })

  it('proposes a validated T2 transfer when validated is true', async () => {
    const svc = makeService()
    const rec = await svc.propose({
      sourceDomain: 'math',
      targetDomain: 'physics',
      validated: true,
      invariantsPreserved: ['monotonicity'],
    })
    expect(rec.tier).toBe('T2')
    expect(rec.validated).toBe(true)
    expect(validateTransferRecord(rec).ok).toBe(true)
  })

  it('rejects a T2+ transfer that is not validated (boundary: §49.3)', () => {
    const bad: TransferRecord = {
      id: 'tr-x',
      schema: 'aijade.transfer_record@1',
      agentId: 'a',
      userScope: 's',
      sourceDomain: 'math',
      targetDomain: 'physics',
      invariantsPreserved: [],
      brokenConditions: [],
      predictedOutcome: 'p',
      measuredOutcome: 'p',
      negativeTransferSignal: 0,
      tier: 'T3',
      validated: false,
      createdAt: 1,
    }
    const res = validateTransferRecord(bad)
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.reason).toMatch(/must be validated/)
  })

  it('validates an AssociationPath contract (the "why" path), rejecting pathless ones', () => {
    const good: AssociationPath = {
      id: 'ap-1',
      schema: 'aijade.association_path@1',
      agentId: 'a',
      userScope: 's',
      fromConcept: 'A',
      toConcept: 'B',
      kind: 'semantic',
      path: ['A relates to B because …'],
      score: 0.4,
      evidenceRefs: ['e1'],
      createdAt: 1,
    }
    expect(validateAssociationPath(good).ok).toBe(true)

    const bad: AssociationPath = { ...good, path: [] }
    expect(validateAssociationPath(bad).ok).toBe(false)
  })
})
