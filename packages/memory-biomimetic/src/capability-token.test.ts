import { describe, expect, it } from 'vitest'

import { createMemoryWriteGate } from './capability-token'

describe('memory write capability gate', () => {
  const grant = {
    id: 'g1',
    schema: 'aijade.capability_grant@1' as const,
    grantee: { userScope: 'u1' },
    capability: 'memory.write',
    scope: 'session:s1',
    grantedBy: 'user',
    issuedAt: 10,
    expiresAt: 100,
    consentPolicy: 'explicit',
    source: [{ ref: 'consent:1', trusted: true }],
  }

  it('accepts a signed token backed by an active grant', async () => {
    const gate = createMemoryWriteGate({
      sign: async () => 'unused',
      verify: async () => ({
        grantId: 'g1',
        capability: 'memory.write',
        scope: 'session:s1',
        grantee: { userScope: 'u1' },
        issuedAt: 10,
        expiresAt: 100,
      }),
    }, [grant])
    await expect(gate.authorize({
      token: 'token',
      capability: 'memory.write',
      scope: 'session:s1',
      now: 50,
    })).resolves.toMatchObject({ grantId: 'g1' })
  })

  it('rejects a token outside its granted scope', async () => {
    const gate = createMemoryWriteGate({
      sign: async () => 'unused',
      verify: async () => ({
        grantId: 'g1',
        capability: 'memory.write',
        scope: 'session:s1',
        grantee: {},
        issuedAt: 10,
        expiresAt: 100,
      }),
    }, [grant])
    await expect(gate.authorize({
      token: 'token',
      capability: 'memory.write',
      scope: 'session:s2',
      now: 50,
    })).rejects.toThrow('scope mismatch')
  })
})
