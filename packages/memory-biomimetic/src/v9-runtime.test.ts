import type { PgcStateRow } from './v9-schema'

import { describe, expect, it } from 'vitest'

import { V9CausalRuntime } from './v9-runtime'

describe('v9CausalRuntime', () => {
  it('runs perception through PGC, MemoryTx and EvidenceWeave in one persisted artifact', async () => {
    const artifacts: any[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (artifact) => {
        artifacts.push(artifact)
      },
    })

    const result = await runtime.processPerception({
      eventId: 'e1',
      sessionId: 's1',
      traceId: 't1',
      correlationId: 't1',
      timestamp: 1,
      originDevice: 'desktop',
      privacyLevel: 1,
      riskScore: 0.1,
      source: 'chat:user',
      content: 'A concrete user observation with a source.',
    })

    expect(artifacts).toHaveLength(1)
    expect(result.artifact.evidencePack.sessionId).toBe('s1')
    expect(result.artifact.pgcState.v6State).toEqual(expect.objectContaining({ a: expect.any(Number) }))
    expect(result.artifact.memoryTx.id).toBe('tx_e1')
    expect(result.artifact.evidenceWeave.txId).toBe('tx_e1')
    expect(result.artifact.events.map(event => event.topic)).toEqual([
      'aijade.pgc.write_plan_ready',
      'aijade.memory_tx.committed',
      'aijade.evidence.weave_candidate_ready',
    ])
  })

  it('rehydrates the previous session state before processing the next perception', async () => {
    const state: PgcStateRow = {
      id: 'pgc-old',
      sessionId: 's1',
      traceId: 'old',
      policyVersion: 'pgc_policy_v1',
      components: {
        plasticity: {
          consolidationGain: 1,
          decayMultiplier: 1,
          retrievalNoise: 0,
          moodCongruenceWeight: 0,
          socialBonus: 0,
          explorationTemperature: 0,
        },
        evidence_strength: 0,
        contradiction_severity: 0,
        evidence_uncertainty: 0,
        persona_shift_risk: 0,
      },
      v6State: { a: 0.7, c: 0.2, d: 0.3, f: 0.1 },
      createdAt: 0,
    }
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => state,
      persist: async () => undefined,
    })
    const result = await runtime.processPerception({
      eventId: 'e2',
      sessionId: 's1',
      traceId: 't2',
      correlationId: 't2',
      timestamp: 2,
      originDevice: 'desktop',
      privacyLevel: 0,
      riskScore: 0,
      source: 'chat:user',
      content: 'next',
    })
    expect(result.artifact.pgcState.v6State.a).not.toBe(state.v6State.a)
  })
})
