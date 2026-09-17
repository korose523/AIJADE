/**
 * v9 — derive a *real*, validated `PerformanceIntent` from a persona snapshot.
 *
 * This is the single bridge that turns committed long-term-memory evidence into
 * a kernel `PerformanceIntent` (contract #28, `aijade.performance_intent@1`).
 * It does NOT hand-roll an intent-shaped object: it delegates to the real
 * `PerformanceDirector` from `@proj-aijade/growth-services`, which calls
 * `buildPerformanceIntent` and `validatePerformanceIntent` internally, and then
 * re-validates the emitted intent once more before it is persisted. The persisted
 * row is therefore a genuine kernel intent — not a look-alike.
 *
 * Determinism: given the same inputs and the same `Date.now()`, the emitted
 * `PerformanceIntent` content is reproducible. `id` is minted by `genId` inside
 * the kernel (non-deterministic by design); no other field is randomly filled.
 */

import type { DialogueAct, PerformanceIntent, PersonaInput } from '@proj-aijade/memory-biomimetic'

import type { Database } from '../../libs/db'

import { InMemoryScheduler, InMemoryStorage, PerformanceDirector } from '@proj-aijade/growth-services'
import { validatePerformanceIntent } from '@proj-aijade/memory-biomimetic'
import { desc, eq } from 'drizzle-orm'

import * as ltmSchema from '../../schemas/long-term-memory'
import * as v9Schema from '../../schemas/memory-v9'

/**
 * Thrown when a session has no committed evidence to derive a persona from.
 * The route maps this to 422 (well-formed request, but no producible intent).
 */
export class NoEvidenceError extends Error {
  constructor(message = 'no committed long-term memory found for session') {
    super(message)
    this.name = 'NoEvidenceError'
  }
}

export interface V9PerformanceIntentDeriveInput {
  userId: string
  sessionId: string
  deviceId: string
  /** 0..3 privacy level. */
  privacyLevel: number
  /** Agent identity for the intent (kernel requires it). */
  agentId: string
  /** User scope for the intent (kernel requires it). */
  userScope: string
  /** Optional step count (default 1). */
  stepCount?: number
  /** Optional per-intent duration in ms (default 200). */
  duration?: number
}

export interface V9PerformanceIntentService {
  /**
   * Derive a validated `PerformanceIntent` for `sessionId`.
   *
   * @throws {NoEvidenceError} when the session has no committed evidence.
   * @throws {Error} when the emitted intent fails `validatePerformanceIntent`.
   */
  deriveForSession: (input: V9PerformanceIntentDeriveInput) => Promise<{
    snapshot: typeof ltmSchema.personaSnapshots.$inferSelect
    intent: typeof ltmSchema.performanceIntents.$inferSelect
  }>
}

export function createV9PerformanceIntentService(deps: { db: Database }): V9PerformanceIntentService {
  const { db } = deps

  return {
    async deriveForSession(input) {
      if (!Number.isInteger(input.privacyLevel) || input.privacyLevel < 0 || input.privacyLevel > 3)
        throw new Error('privacyLevel must be an integer from 0 to 3')

      // 1. Read the session's committed evidence, exactly as the legacy
      //    `generatePersonaFromMemory` did (join chunks → packs, latest 20).
      const evidence = await db
        .select({
          content: v9Schema.v9EvidenceChunks.content,
          source: v9Schema.v9EvidencePacks.source,
        })
        .from(v9Schema.v9EvidenceChunks)
        .innerJoin(v9Schema.v9EvidencePacks, eq(v9Schema.v9EvidenceChunks.packId, v9Schema.v9EvidencePacks.id))
        .where(eq(v9Schema.v9EvidencePacks.sessionId, input.sessionId))
        .orderBy(desc(v9Schema.v9EvidenceChunks.createdAt))
        .limit(20)

      // Evidence empty ⇒ explicitly refuse. We never fabricate a blank intent.
      if (evidence.length === 0)
        throw new NoEvidenceError()

      // 2. Insert a real persona snapshot row and take its real (minted) id.
      const [snapshot] = await db
        .insert(ltmSchema.personaSnapshots)
        .values({
          userId: input.userId,
          deviceId: input.deviceId,
          privacyLevel: input.privacyLevel,
          version: 1,
          persona: {
            source: 'v9-persona-intent',
            sessionId: input.sessionId,
            evidenceCount: evidence.length,
            evidenceSources: [...new Set(evidence.map(e => e.source))],
            // The derived persona stack — stored verbatim so the snapshot is
            // itself auditable (not a black box).
            persona: derivePersonaInput(evidence),
          },
        })
        .returning()

      // 3. Derive the persona stack from evidence (real, reproducible — no RNG).
      const persona = derivePersonaInput(evidence)

      // 4. Run the REAL kernel director. `storage` is an in-memory adapter
      //    (the director persists its own bookkeeping there); `scheduler.now`
      //    uses the wall clock so `timeMarked` is real. The director internally
      //    calls `buildPerformanceIntent` + `validatePerformanceIntent`.
      const director = new PerformanceDirector(
        { storage: new InMemoryStorage(), scheduler: new InMemoryScheduler() },
        input.agentId,
        input.userScope,
      )
      const result = await director.direct({
        personaSnapshotRef: snapshot.id,
        persona,
        stepCount: input.stepCount,
        duration: input.duration,
      })

      // 5. Double-check the emitted intent (defence in depth; director already
      //    validated, but we never trust a single gate).
      const intent = result.steps[0].intent
      const check = validatePerformanceIntent(intent)
      if (!check.ok)
        throw new Error(`PerformanceIntent rejected: ${check.reason}`)

      // 6. Persist THIS kernel intent (not a hand-rolled look-alike).
      const [row] = await db
        .insert(ltmSchema.performanceIntents)
        .values({
          userId: input.userId,
          deviceId: input.deviceId,
          personaSnapshotRef: snapshot.id,
          privacyLevel: input.privacyLevel,
          // `intent` is the genuine kernel object (schema === 'aijade.performance_intent@1').
          intent: intent as unknown as Record<string, unknown>,
          timeMarked: new Date(intent.timeMarked),
        })
        .returning()

      return { snapshot, intent: row }
    },
  }
}

/**
 * Derive a `PersonaInput` from committed evidence.
 *
 * Derivation rules (all deterministic, no randomness / no wall-clock):
 * - `dialogueAct`: the only required layer. Inferred from the joined evidence
 *   text — a question mark ⇒ `question`, an exclamation ⇒ `celebrate`, else
 *   `inform`. This modulates the expression via the fixed §52.2 deltas.
 * - `developmental.interests`: the set of distinct evidence `source`s. These are
 *   real, observed provenance strings — a honest, minimal signal of what this
 *   user's memory is about.
 * - `character` / `expressiveState` / `relationship` / `constitutional`: left
 *   UNSET. We have no verified basis for them, so we let the kernel fall back to
 *   its neutral baseline rather than fabricate a personality. (§52.2: a missing
 *   layer contributes no adjustment.)
 */
function derivePersonaInput(evidence: { content: string, source: string }[]): PersonaInput {
  const joined = evidence.map(e => e.content).join(' ').toLowerCase()
  let dialogueAct: DialogueAct = 'inform'
  if (joined.includes('?'))
    dialogueAct = 'question'
  else if (joined.includes('!'))
    dialogueAct = 'celebrate'

  const sources = [...new Set(evidence.map(e => e.source))]

  return {
    dialogueAct,
    developmental: { interests: sources },
  }
}

export type { PerformanceIntent, PersonaInput }
