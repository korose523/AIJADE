import { describe, expect, it } from 'vitest'

import { createReleaseExecutor } from './release-executor'

function deps() {
  const values = new Map<string, unknown>()
  return {
    storage: {
      put: async (_kind: string, id: string, value: unknown) => {
        values.set(id, value)
      },
      get: async <T>(_kind: string, id: string) => values.get(id) as T | undefined,
      list: async <T>() => [...values.values()] as T[],
      query: async <T>() => [...values.values()] as T[],
    },
    scheduler: { now: () => 10, consumeBudget: () => true },
  }
}

describe('release executor', () => {
  it('persists canary activation and explicit rollback', async () => {
    const d = deps()
    const executor = createReleaseExecutor(d)
    const release = {
      id: 'r1',
      schema: 'aijade.signed_release@1' as const,
      version: 'v1',
      proposalRef: 'p1',
      evidencePackRef: 'e1',
      approvedBy: 'user',
      signedAt: 1,
      signature: 'sig',
      canaryRatio: 0.1,
      rollbackAvailable: true,
    }
    await d.storage.put('signed_release', release.id, release)
    await executor.activate(release)
    await expect(executor.active()).resolves.toMatchObject({ id: 'r1' })
    await executor.rollback('r1', 'regression')
    await expect(executor.active()).resolves.toBeUndefined()
  })

  it('assigns a stable user to a canary and records the selected version', async () => {
    const d = deps()
    const executor = createReleaseExecutor(d)
    const release = {
      id: 'r1',
      schema: 'aijade.signed_release@1' as const,
      version: 'v1',
      proposalRef: 'p1',
      evidencePackRef: 'e1',
      approvedBy: 'user',
      signedAt: 1,
      signature: 'sig',
      canaryRatio: 1,
      rollbackAvailable: true,
    }
    await d.storage.put('signed_release', release.id, release)
    await executor.activate(release)
    const first = await executor.select({ userId: 'real-user' }, 'trace-1')
    const second = await executor.select({ userId: 'real-user' }, 'trace-2')
    expect(first).toMatchObject({ releaseId: 'r1', version: 'v1', eligible: true })
    expect(second.bucket).toBe(first.bucket)
    await expect(d.storage.get('release_routing_trace', 'trace-1')).resolves.toMatchObject({
      traceId: 'trace-1',
      version: 'v1',
      userId: 'real-user',
    })
  })

  it('does not route a canary after rollback', async () => {
    const d = deps()
    const executor = createReleaseExecutor(d)
    const release = {
      id: 'r1',
      schema: 'aijade.signed_release@1' as const,
      version: 'v1',
      proposalRef: 'p1',
      evidencePackRef: 'e1',
      approvedBy: 'user',
      signedAt: 1,
      signature: 'sig',
      canaryRatio: 1,
      rollbackAvailable: true,
    }
    await d.storage.put('signed_release', release.id, release)
    await executor.activate(release)
    await executor.rollback('r1', 'regression')
    await expect(executor.select({ sessionId: 'session-1' }, 'trace-rollback'))
      .resolves
      .toMatchObject({ eligible: false, releaseId: undefined, version: undefined })
  })
})
