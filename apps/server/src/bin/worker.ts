import process from 'node:process'

import { V9CausalRuntime } from '@proj-aijade/memory-biomimetic'

import { createDrizzle, migrateDatabase } from '../libs/db'
import { parseEnv } from '../libs/env'
import { createRedis } from '../libs/redis'
import { createLongTermMemoryService, dequeueMemoryJob } from '../services/domain/long-term-memory'
import { dequeueV9Perception, dequeueV9Promotion, parkDeadLetter, V9_MEMORY_DEAD_LETTER, V9_PERCEPTION_DEAD_LETTER, V9_PROMOTION_DEAD_LETTER } from '../services/domain/v9-jobs'
import { createV9PromotionService } from '../services/domain/v9-promotion'
import { createV9RuntimeStore } from '../services/domain/v9-runtime-store'

async function main(): Promise<void> {
  const runtimeEnv = parseEnv(process.env)
  const { db, pool } = createDrizzle(runtimeEnv)
  const redis = createRedis(runtimeEnv.REDIS_URL)
  await redis.connect()
  await db.execute('SELECT 1')
  await migrateDatabase(db)
  const runtime = new V9CausalRuntime(createV9RuntimeStore(db))
  const memory = createLongTermMemoryService(db, redis)
  const promotion = createV9PromotionService({ db })
  process.once('SIGTERM', () => { void shutdown() })
  process.once('SIGINT', () => { void shutdown() })

  while (true) {
    const [v9Job, memoryJob, promotionJob] = await Promise.all([
      dequeueV9Perception(redis),
      dequeueMemoryJob(redis),
      dequeueV9Promotion(redis),
    ])
    if (v9Job) {
      try {
        await runtime.processPerception(v9Job.input)
      }
      catch (error) {
        console.error(`[v9-worker] job ${v9Job.jobId} failed`, error)
        await parkDeadLetter(redis, V9_PERCEPTION_DEAD_LETTER, { job: v9Job, error: String(error) })
      }
    }
    if (memoryJob) {
      try {
        if (memoryJob.kind === 'sync')
          await memory.processSync(memoryJob.outboxId)
        else
          await memory.processShare(memoryJob.notificationId)
      }
      catch (error) {
        console.error(`[memory-worker] ${memoryJob.kind} failed`, error)
        await parkDeadLetter(redis, V9_MEMORY_DEAD_LETTER, { job: memoryJob, error: String(error) })
      }
    }
    if (promotionJob) {
      try {
        const result = await promotion.process(promotionJob)
        if (!result.ok) {
          console.error(`[v9-promotion-worker] job ${promotionJob.jobId} refused at ${result.stage}: ${result.reason}`)
        }
      }
      catch (error) {
        console.error(`[v9-promotion-worker] job ${promotionJob.jobId} failed`, error)
        await parkDeadLetter(redis, V9_PROMOTION_DEAD_LETTER, { job: promotionJob, error: String(error) })
      }
    }
  }

  async function shutdown(): Promise<void> {
    await redis.quit()
    await pool.end()
    process.exit(0)
  }
}

void main().catch((error) => {
  console.error('[v9-worker] fatal error', error)
  process.exit(1)
})
