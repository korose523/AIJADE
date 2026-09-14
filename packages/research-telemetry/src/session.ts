/**
 * Experiment session + turn recorder.
 *
 * This is the API the rest of AIJADE calls. It is deliberately tiny —
 * `startSession()` → `recordTurn()` → `exportCsv()` — because a telemetry
 * layer that is annoying to call does not get called, and uncalled telemetry
 * produces no data. That is exactly the failure mode this package exists to
 * fix: the persona-dynamics and skill-forge code in this repo is real and
 * correct, but nothing ever invoked it, so nothing was ever measured.
 */

import type { TelemetryStorage } from './storage'
import type { AblationCondition, AblationConfig, DynamicsParameters, ExperimentSession, PersonaSnapshot, SessionMeta, TurnRecord, TurnRole } from './types'

import {
  fingerprintConfig,
  resolveCondition,
} from './ablation'
import {
  createMemoryStorage,

} from './storage'
import { fingerprintParameters } from './sweep'
import {

  FULL_ABLATION,

} from './types'

export interface StartSessionOptions {
  /** Condition name (see `DEFAULT_CONDITIONS`) or a custom condition object. */
  condition?: string | AblationCondition
  /** Explicit ablation config; overrides `condition` when both are given. */
  config?: AblationConfig
  /** Non-PII participant / run identifier. */
  participantId?: string
  /**
   * Dynamics parameters assigned to this session (Gap #2 sweep cell).
   * Recorded on every turn so a sweep remains analysable even if the
   * parameters are adapted mid-session.
   */
  parameters?: DynamicsParameters
  /** Extra context to carry into the export (model, app version, platform…). */
  tags?: Record<string, string>
  /** Inject a storage adapter; defaults to in-memory. */
  storage?: TelemetryStorage
  /** Override id generation (tests). */
  sessionId?: string
  /** Override clock (tests). */
  now?: () => number
}

/**
 * Everything that may be attached to a turn. All fields optional — call sites
 * pass what they have and omit what they do not measure.
 */
export interface RecordTurnInput {
  role: TurnRole
  persona?: PersonaSnapshot
  skillLibrarySize?: number
  skillsCreatedThisTurn?: number
  skillsRejectedThisTurn?: number
  latency?: TurnRecord['latency']
  tokens?: TurnRecord['tokens']
  memoryHits?: number
  textLength?: number
  /**
   * Override the session-level dynamics parameters for this turn.
   * Only needed for adaptive / annealed schedules; leave unset otherwise and
   * the session value is recorded automatically.
   */
  parameters?: DynamicsParameters
  metadata?: Record<string, unknown>
}

export class ExperimentSessionRunner {
  readonly sessionId: string
  readonly condition: AblationCondition
  readonly config: AblationConfig
  readonly configFingerprint: string
  /** Dynamics parameters for this session; `{}` when not part of a sweep. */
  readonly parameters: DynamicsParameters
  readonly parameterFingerprint: string
  readonly startedAt: number

  private readonly storage: TelemetryStorage
  private readonly now: () => number
  private readonly meta: SessionMeta
  private index = 0
  private ended = false

  constructor(options: StartSessionOptions = {}) {
    this.now = options.now ?? (() => Date.now())
    this.sessionId = options.sessionId ?? generateId()
    this.startedAt = this.now()

    this.condition = typeof options.condition === 'string'
      ? resolveCondition(options.condition)
      : options.condition ?? resolveCondition('baseline')

    this.config = options.config ?? this.condition.config ?? { ...FULL_ABLATION }
    this.configFingerprint = fingerprintConfig(this.config)
    this.parameters = options.parameters ?? {}
    this.parameterFingerprint = fingerprintParameters(this.parameters)
    this.storage = options.storage ?? createMemoryStorage()

    this.meta = {
      sessionId: this.sessionId,
      condition: this.condition.name,
      configFingerprint: this.configFingerprint,
      startedAt: this.startedAt,
      ...(options.participantId !== undefined ? { participantId: options.participantId } : {}),
      ...(options.parameters ? { parameters: options.parameters } : {}),
      ...(options.parameters ? { parameterFingerprint: this.parameterFingerprint } : {}),
      ...(options.tags ? { tags: options.tags } : {}),
    }
  }

  /**
   * Persist session metadata. Fire-and-forget safe: resolved before the first
   * `recordTurn` completes, so downstream exports always see the session.
   */
  async init(): Promise<this> {
    await this.storage.saveSession(this.meta)
    return this
  }

  /** Convenience: is this component enabled under the current ablation? */
  isEnabled(component: keyof AblationConfig): boolean {
    return this.config[component] === true
  }

  /** Record one turn. Returns the persisted record. */
  async recordTurn(input: RecordTurnInput): Promise<TurnRecord> {
    if (this.ended)
      throw new Error(`Session ${this.sessionId} has already been closed`)

    const ts = this.now()
    const record: TurnRecord = {
      sessionId: this.sessionId,
      turnIndex: this.index++,
      timestamp: ts,
      wallClock: new Date(ts).toISOString(),
      role: input.role,
      ...(input.persona ? { persona: input.persona } : {}),
      ...(input.skillLibrarySize !== undefined ? { skillLibrarySize: input.skillLibrarySize } : {}),
      ...(input.skillsCreatedThisTurn !== undefined ? { skillsCreatedThisTurn: input.skillsCreatedThisTurn } : {}),
      ...(input.skillsRejectedThisTurn !== undefined ? { skillsRejectedThisTurn: input.skillsRejectedThisTurn } : {}),
      ...(input.latency ? { latency: input.latency } : {}),
      ...(input.tokens ? { tokens: input.tokens } : {}),
      ...(input.memoryHits !== undefined ? { memoryHits: input.memoryHits } : {}),
      ...(input.textLength !== undefined ? { textLength: input.textLength } : {}),
      // Recorded per turn (not just per session) so adaptive schedules and
      // parameter ratchets stay reconstructible after the fact.
      parameters: input.parameters ?? this.parameters,
      ...(input.metadata ? { metadata: input.metadata } : {}),
    }

    await this.storage.appendTurn(record)
    return record
  }

  /** Mark the session closed and return its final metadata. */
  async close(): Promise<ExperimentSession> {
    if (!this.ended) {
      this.ended = true
      await this.storage.saveSession(this.meta)
    }
    return {
      ...this.meta,
      endedAt: this.now(),
      turnCount: this.index,
    }
  }

  get turnCount(): number {
    return this.index
  }

  getStorage(): TelemetryStorage {
    return this.storage
  }
}

/** Create and persist a session in one call. */
export async function startSession(options: StartSessionOptions = {}): Promise<ExperimentSessionRunner> {
  return new ExperimentSessionRunner(options).init()
}

function generateId(): string {
  // Prefer the platform CSPRNG; fall back to a time+random composite.
  const g = globalThis as { crypto?: { randomUUID?: () => string } }
  if (g.crypto?.randomUUID)
    return g.crypto.randomUUID()
  return `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
