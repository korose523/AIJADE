import type { LongTermMemoryService } from '../services/domain/long-term-memory'
import type { HonoEnv } from '../types/hono'

import { Hono } from 'hono'

import { authGuard } from '../middlewares/auth'

export function createMemoryRoutes(service: LongTermMemoryService) {
  return new Hono<HonoEnv>()
    .use('*', authGuard)
    .post('/persona-snapshots', async (c) => {
      const body = await c.req.json()
      const snapshot = await service.savePersonaSnapshot(c.get('user')!.id, body)
      return c.json(snapshot, 201)
    })
    .post('/persona-snapshots/from-memory', async (c) => {
      const body = await c.req.json()
      const generated = await service.generatePersonaFromMemory(c.get('user')!.id, body)
      return c.json(generated, 201)
    })
    .post('/performance-intents', async (c) => {
      const body = await c.req.json()
      const intent = await service.savePerformanceIntent(c.get('user')!.id, body)
      return c.json(intent, 201)
    })
    .get('/sync', async (c) => {
      const deviceId = c.req.query('deviceId')
      if (!deviceId)
        return c.json({ error: 'deviceId is required' }, 400)
      return c.json({ items: await service.pullForDevice(c.get('user')!.id, deviceId) })
    })
    .get('/notifications', async c => c.json({
      notifications: await service.listNotifications(c.get('user')!.id),
    }))
    .post('/notifications', async (c) => {
      const body = await c.req.json()
      const notification = await service.queueShareNotification(c.get('user')!.id, {
        id: body.candidateId ?? body.id,
        channel: body.channel,
        contentRef: body.contentRef,
        score: body.score,
        privacyLevel: body.privacyLevel,
      })
      return c.json(notification, 202)
    })
}
