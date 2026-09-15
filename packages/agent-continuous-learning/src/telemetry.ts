/**
 * Bridge from the live persona state to `@proj-aijade/research-telemetry`'s
 * snapshot shape.
 *
 * `research-telemetry` deliberately clones the persona types rather than import
 * them, so it can be loaded from any runtime without dragging in the whole agent
 * stack. That means the *values* must be projected here, where the derivation
 * maths (PAD / Big-Five / mood) already lives. The result is structurally
 * identical to `PersonaSnapshot`, so it drops straight into a {@link TurnRecord}.
 */

import type { ExperimentSessionRunner, PersonaSnapshot, TelemetryStorage } from '@proj-aijade/research-telemetry'

import type { PersonaUpdateEvent } from './learning'
import type { PersonaState } from './persona'

import { createIndexedDbStorage, startSession } from '@proj-aijade/research-telemetry'

import { toBigFive, toMoodProfile, toPAD } from './persona'

/** Project a live persona into a telemetry-compatible snapshot. */
export function toPersonaSnapshot(state: PersonaState): PersonaSnapshot {
  const pad = toPAD(state)
  const bigFive = toBigFive(state.vector)
  const mood = toMoodProfile(state)
  return {
    vector: { ...state.vector },
    endocrine: { ...state.endocrine },
    pad,
    bigFive,
    intimacy: { ...state.intimacy },
    moodLabel: mood.label,
    moodEmoji: mood.emoji,
  }
}

export interface PersonaTelemetryOptions {
  /**
   * Polled on **every** persona update. Recording happens only while this
   * returns true, and flipping it from true to false **erases** what has been
   * recorded so far.
   *
   * There is deliberately no way to make this default to true: a longitudinal
   * persona trajectory is human-subjects data, and collecting it without an
   * explicit, withdrawable consent would not survive an IRB review.
   */
  consent: () => boolean
  /**
   * Storage adapter. Defaults to IndexedDB in a browser-like environment;
   * when no durable storage is available recording fails (reported via
   * `onError`) rather than silently degrading to memory — silent memory
   * telemetry is how a dissertation ends up citing data that never existed.
   */
  storage?: TelemetryStorage
  condition?: string
  participantId?: string
  /** Session id override (tests). */
  sessionId?: string
  /** Override clock (tests). */
  now?: () => number
  /** Receives every telemetry failure. Telemetry is best-effort, never fatal. */
  onError?: (error: unknown) => void
}

export interface PersonaTelemetryRecorder {
  /**
   * Drop straight into `AgentCapabilitiesOptions.onPersonaUpdate`. Fire-and-forget:
   * it never throws and never blocks a chat turn.
   */
  record: (event: PersonaUpdateEvent) => void
  /** For tests and for a future settings panel. */
  diagnostics: () => { recording: boolean, turnsRecorded: number, lastError?: string }
}

/**
 * Wire the live persona trajectory into `@proj-aijade/research-telemetry`.
 *
 * This is the piece that was missing. `AgentCapabilitiesOptions.onPersonaUpdate`
 * has been plumbed through the bridge since it was written — its docstring calls
 * the trajectory "the data backbone of the dissertation" — but no call site ever
 * passed a listener, and `toPersonaSnapshot` had no production caller. The
 * longitudinal data the dissertation depends on was simply never produced.
 *
 * Consent-gated by design; see {@link PersonaTelemetryOptions.consent}.
 */
export function createPersonaTelemetryRecorder(options: PersonaTelemetryOptions): PersonaTelemetryRecorder {
  let sessionPromise: Promise<ExperimentSessionRunner> | undefined
  let turnsRecorded = 0
  let lastError: string | undefined
  let lastConsent = options.consent()

  function fail(error: unknown): void {
    if (error instanceof Error)
      lastError = error.message
    else
      lastError = String(error)
    options.onError?.(error)
  }

  function resolveStorage(): TelemetryStorage {
    if (options.storage)
      return options.storage
    if (typeof globalThis.indexedDB === 'undefined')
      throw new Error('research telemetry consented but no durable storage is available in this environment')
    return createIndexedDbStorage()
  }

  function openSession(): Promise<ExperimentSessionRunner> {
    sessionPromise ??= startSession({
      condition: options.condition ?? 'baseline',
      participantId: options.participantId,
      sessionId: options.sessionId,
      now: options.now,
      storage: resolveStorage(),
    })
    return sessionPromise
  }

  async function purge(): Promise<void> {
    const session = sessionPromise
    sessionPromise = undefined
    turnsRecorded = 0
    if (!session)
      return
    try {
      const storage = (await session).getStorage()
      await storage.clear()
    }
    catch (error) {
      fail(error)
    }
  }

  function record(event: PersonaUpdateEvent): void {
    const consent = options.consent()
    // Withdrawal: stop recording *and* erase what was recorded. Keeping
    // already-written turns after a withdrawal is precisely what an IRB review
    // treats as a violation.
    if (lastConsent && !consent)
      void purge()
    lastConsent = consent
    if (!consent)
      return

    void (async () => {
      try {
        const session = await openSession()
        await session.recordTurn({
          role: event.role ?? 'user',
          persona: toPersonaSnapshot(event.state),
        })
        turnsRecorded++
        lastError = undefined
      }
      catch (error) {
        // A failed open must be retried on the next update, not cached forever.
        sessionPromise = undefined
        fail(error)
      }
    })()
  }

  return {
    record,
    diagnostics: () => ({ recording: lastConsent, turnsRecorded, ...(lastError ? { lastError } : {}) }),
  }
}
