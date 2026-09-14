import type { ConsistencyObservation, PersonaInput } from '@proj-aijade/memory-biomimetic'

import { identityConsistencyCheck, validatePerformanceIntent } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemoryStorage } from './in-memory'
import { PerformanceDirector } from './performance-director'
import { FixedScheduler } from './test-helpers'

const PERSONA: PersonaInput = { dialogueAct: 'inform' }

function makeService() {
  return new PerformanceDirector(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('performanceDirector', () => {
  it('builds time-marked PerformanceIntents that pass validatePerformanceIntent', async () => {
    const svc = makeService()
    const res = await svc.direct({ personaSnapshotRef: 'snap-1', persona: PERSONA, stepCount: 2 })
    expect(res.steps.length).toBe(2)
    for (const s of res.steps) {
      expect(validatePerformanceIntent(s.intent).ok).toBe(true)
      expect(s.degradeMode).toBe('none')
    }
  })

  it('downgrades to voice when identity-level consistency fails (kernel identityConsistencyCheck)', async () => {
    const svc = makeService()
    const obs: ConsistencyObservation[] = [{ faceIdentityDrift: 0.5 }] // > 0.2 threshold
    const res = await svc.direct({ personaSnapshotRef: 'snap-1', persona: PERSONA, observations: obs })
    expect(res.steps[0]!.degradeMode).toBe('voice')
    expect(identityConsistencyCheck(obs[0]!).ok).toBe(false)
  })

  it('downgrades to avatar for expression-level drift only', async () => {
    const svc = makeService()
    const obs: ConsistencyObservation[] = [{ clothingDrift: 0.5 }] // > 0.3 threshold
    const res = await svc.direct({ personaSnapshotRef: 'snap-1', persona: PERSONA, observations: obs })
    expect(res.steps[0]!.degradeMode).toBe('avatar')
  })

  it('prefers voice over avatar when both kinds of failure are present (worstDegrade)', async () => {
    const svc = makeService()
    const obs: ConsistencyObservation[] = [{ clothingDrift: 0.5, faceIdentityDrift: 0.5 }]
    const res = await svc.direct({ personaSnapshotRef: 'snap-1', persona: PERSONA, observations: obs })
    expect(res.steps[0]!.degradeMode).toBe('voice')
  })

  it('schedules full-duplex events via the kernel scheduleDuplex', async () => {
    const svc = makeService()
    const res = await svc.direct({
      personaSnapshotRef: 'snap-1',
      persona: PERSONA,
      duplexEvents: [{ type: 'user_interruption' }, { type: 'listen_signal' }],
    })
    expect(res.duplexDecisions[0]!.abortSpeech).toBe(true)
    expect(res.duplexDecisions[0]!.turnTaking).toBe('yield')
    expect(res.duplexDecisions[1]!.turnTaking).toBe('backchannel')
  })
})
