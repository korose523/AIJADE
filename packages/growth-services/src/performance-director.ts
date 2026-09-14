/**
 * §52 PEF — PerformanceDirector.
 *
 * Maps a persona snapshot (`PersonaInput`) onto a time-marked stream of incremental
 * `PerformanceIntent`s via `buildPerformanceIntent`, reacts to full-duplex events
 * with `scheduleDuplex`, and runs `identityConsistencyCheck` against renderer
 * observations — when the check fails it records a `DegradeMode` (avatar → voice)
 * so the runtime can fall back to a controllable avatar or pure voice. Every
 * emitted intent passes `validatePerformanceIntent`.
 */

import type { ConsistencyObservation, DegradeMode, DuplexDecision, DuplexEvent, PerformanceIntent, PersonaInput } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import {
  buildPerformanceIntent,
  identityConsistencyCheck,
  scheduleDuplex,
  validatePerformanceIntent,
} from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'performance_intent'

export interface DirectInput {
  /** Persona / identity snapshot this performance is expressed from (required). */
  personaSnapshotRef: string
  persona: PersonaInput
  /** Renderer-side consistency observations to evaluate. */
  observations?: ConsistencyObservation[]
  /** Number of incremental intent steps to emit (default 1). */
  stepCount?: number
  /** Per-intent duration in ms. */
  duration?: number
  /** Full-duplex events to schedule against. */
  duplexEvents?: DuplexEvent[]
}

export interface IntentStep {
  intent: PerformanceIntent
  /** Per-intent identity-consistency degraded mode (none | avatar | voice). */
  degradeMode: DegradeMode
}

export interface DirectResult {
  steps: IntentStep[]
  verdicts: ReturnType<typeof identityConsistencyCheck>[]
  duplexDecisions: DuplexDecision[]
}

export interface PerformanceDirectorDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class PerformanceDirector {
  constructor(
    private readonly deps: PerformanceDirectorDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  async direct(input: DirectInput): Promise<DirectResult> {
    const now = this.deps.scheduler.now()
    const steps: IntentStep[] = []
    const stepCount = Math.max(1, input.stepCount ?? 1)
    const duration = input.duration ?? 200

    for (let i = 0; i < stepCount; i++) {
      const timeMarked = now + i * duration
      const intent = buildPerformanceIntent(
        input.persona,
        {
          id: genId('pi'),
          agentId: this.agentId,
          userScope: this.userScope,
          personaSnapshotRef: input.personaSnapshotRef,
        },
        timeMarked,
        duration,
      )
      const check = validatePerformanceIntent(intent)
      if (!check.ok)
        throw new Error(`PerformanceIntent rejected: ${check.reason}`)
      // When identity consistency fails, the whole stream is downgraded.
      const degradeMode: DegradeMode
        = (input.observations ?? []).some(o => !identityConsistencyCheck(o).ok)
          ? this.worstDegrade(input.observations ?? [])
          : 'none'
      steps.push({ intent, degradeMode })
      await this.deps.storage.put(KIND, intent.id, intent)
    }

    const verdicts = (input.observations ?? []).map(o => identityConsistencyCheck(o))
    const duplexDecisions = (input.duplexEvents ?? []).map(e => scheduleDuplex(e))

    return { steps, verdicts, duplexDecisions }
  }

  /** Worst (voice > avatar) degrade among failing observations. */
  private worstDegrade(observations: ConsistencyObservation[]): DegradeMode {
    let voice = false
    let avatar = false
    for (const o of observations) {
      const v = identityConsistencyCheck(o)
      if (!v.ok) {
        if (v.degrade === 'voice')
          voice = true
        else avatar = true
      }
    }
    return voice ? 'voice' : avatar ? 'avatar' : 'none'
  }
}
