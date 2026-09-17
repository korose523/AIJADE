/**
 * `POST /api/v1/v9/persona/derive` —— derive a real, validated `PerformanceIntent`
 * from a session's committed long-term-memory evidence.
 *
 * Full mount path (app.ts prefix + this router) is:
 *   `POST /api/v1/v9/persona/derive`
 *
 * Failure semantics (never 200 + empty intent):
 * - Unauthenticated            → 401 (authGuard).
 * - Malformed body / extra key → 400 (valibot `strictObject` + JSON parse).
 * - Well-formed but no evidence → 422 (`NO_EVIDENCE`): the request is valid but
 *   the session has nothing to derive a persona from, so no intent is produced.
 */

import type { Database } from '../../libs/db'
import type { HonoEnv } from '../../types/hono'

import { Hono } from 'hono'
import { integer, maxValue, minLength, minValue, number, optional, pipe, safeParse, strictObject, string } from 'valibot'

import { authGuard } from '../../middlewares/auth'
import { createV9PerformanceIntentService, NoEvidenceError } from '../../services/domain/v9-performance-intent'
import { ApiError, createBadRequestError, createUnauthorizedError } from '../../utils/error'

const v9PersonaDeriveSchema = strictObject({
  session_id: pipe(string(), minLength(1)),
  device_id: pipe(string(), minLength(1)),
  agent_id: pipe(string(), minLength(1)),
  user_scope: pipe(string(), minLength(1)),
  privacy_level: pipe(number(), integer(), minValue(0), maxValue(3)),
  step_count: optional(pipe(number(), integer(), minValue(1))),
  duration: optional(pipe(number(), integer(), minValue(0))),
})

export function createV9PersonaRoutes(deps: { db: Database }) {
  const service = createV9PerformanceIntentService({ db: deps.db })

  return new Hono<HonoEnv>()
    .use('*', authGuard)
    .post('/', async (c) => {
      let body: unknown
      try {
        body = await c.req.json()
      }
      catch {
        throw createBadRequestError('Invalid JSON body', 'INVALID_V9_PERSONA')
      }

      const parsed = safeParse(v9PersonaDeriveSchema, body)
      if (!parsed.success)
        throw createBadRequestError('Invalid v9 persona derive request', 'INVALID_V9_PERSONA', parsed.issues)

      const { session_id, device_id, agent_id, user_scope, privacy_level, step_count, duration } = parsed.output

      const user = c.get('user')
      if (!user)
        throw createUnauthorizedError()

      try {
        const { snapshot, intent } = await service.deriveForSession({
          userId: user.id,
          sessionId: session_id,
          deviceId: device_id,
          privacyLevel: privacy_level,
          agentId: agent_id,
          userScope: user_scope,
          stepCount: step_count,
          duration,
        })

        return c.json(
          {
            persona_snapshot_ref: snapshot.id,
            intent_ref: intent.id,
            intent: intent.intent,
          },
          200,
        )
      }
      catch (err) {
        if (err instanceof NoEvidenceError)
          throw new ApiError(422, 'NO_EVIDENCE', 'no committed long-term memory found for session')
        throw err
      }
    })
}
