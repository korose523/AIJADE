import type Redis from 'ioredis'

import { describe, expect, it } from 'vitest'

import {
  dequeueMemoryJob,
  enqueueMemoryJob,
  LONG_TERM_MEMORY_QUEUE,
} from './long-term-memory'

describe('long-term memory jobs', () => {
  it('round-trips sync and share jobs through Redis', async () => {
    const values: string[] = []
    const redis = {
      lpush: async (_queue: string, value: string) => {
        values.unshift(value)
        return values.length
      },
      brpop: async (queue: string) => {
        expect(queue).toBe(LONG_TERM_MEMORY_QUEUE)
        const value = values.pop()
        return value ? [queue, value] as [string, string] : null
      },
    } as unknown as Redis

    await enqueueMemoryJob(redis, { kind: 'sync', outboxId: 'outbox-1' })
    await enqueueMemoryJob(redis, { kind: 'share', notificationId: 'notification-1' })
    expect(await dequeueMemoryJob(redis)).toEqual({ kind: 'sync', outboxId: 'outbox-1' })
    expect(await dequeueMemoryJob(redis)).toEqual({ kind: 'share', notificationId: 'notification-1' })
  })

  it('rejects malformed jobs', async () => {
    const redis = {
      brpop: async () => ['queue', JSON.stringify({ nope: true })],
    } as unknown as Redis
    await expect(dequeueMemoryJob(redis)).rejects.toThrow('invalid long-term memory job')
  })
})
