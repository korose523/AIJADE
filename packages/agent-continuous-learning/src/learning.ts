import type { SkillForge } from '@proj-aijade/agent-skill-forge'
import type { MemoryPort } from '@proj-aijade/memory-pgvector/port'

import type { DiscourseMemory } from './discourse-memory'
import type { PersonaDynamicsConfig } from './dynamics'
import type { InteractionSignal, PersonaState } from './persona'
import type { SignalExtractor } from './signal'
import type { LearningLLM } from './types'

import { createLogger } from '@proj-aijade/agent-llm-client'

import { createDiscourseMemory } from './discourse-memory'
import { DEFAULT_DYNAMICS, resolveDynamics } from './dynamics'
import {
  applyInteraction,
  createPersonaState,
  drift,

  toContext,
} from './persona'
import { createLexiconSignalExtractor } from './signal'

const logger = createLogger('agent-continuous-learning')

/**
 * Emitted every time the persona changes, so a telemetry layer can persist the
 * trajectory without this package depending on `@proj-aijade/research-telemetry`.
 */
export interface PersonaUpdateEvent {
  /** The persona *after* the update. */
  state: PersonaState
  /** What caused the change — needed to separate interaction effects from drift. */
  cause: 'interaction' | 'drift'
  timestamp: number
  role?: 'user' | 'assistant'
  signal?: InteractionSignal
}

export interface ContinuousLearningOptions {
  llm: LearningLLM
  /** AIJADE's layered memory port (the LPM long-term backbone). */
  memory?: MemoryPort
  /** Skill forge used for feedback-driven evolution. */
  skillForge?: SkillForge
  /** Initial persona seed (0..1). */
  personaSeed?: number
  /** Abs-valence threshold above which feedback triggers skill evolution. */
  feedbackThreshold?: number
  /**
   * Affective dynamics parameters. Omit to use {@link DEFAULT_DYNAMICS}, which
   * reproduces the original hard-coded behaviour exactly.
   */
  dynamics?: Partial<PersonaDynamicsConfig>
  /**
   * Derives valence/arousal from turn text when the caller does not supply a
   * signal. Defaults to the deterministic lexicon extractor.
   *
   * Set to `null` to restore the legacy behaviour (no signal → no
   * interaction-driven update). Only do this for ablation conditions that
   * deliberately disable interaction-driven learning.
   */
  signalExtractor?: SignalExtractor | null
  /** Called after every persona change; wire to telemetry to record trajectories. */
  onPersonaUpdate?: (event: PersonaUpdateEvent) => void
}

export interface ContinuousLearning {
  getPersona: () => PersonaState
  /** The affective dynamics parameters currently in force. */
  getDynamics: () => PersonaDynamicsConfig
  /** Ingest a finished turn; updates discourse, memory and persona. */
  ingestTurn: (role: 'user' | 'assistant', text: string, signal?: InteractionSignal) => void
  /** Periodic drift tick (drive from a "silence clock"). */
  tick: (dtMs: number) => void
  /** Milliseconds since the last ingested interaction (silence clock). */
  idleMs: () => number
  /** Capture explicit user feedback and evolve the best-matching skill. */
  captureFeedback: (feedback: string, relatedText?: string) => Promise<void>
  /** Persona + discourse prompt supplement for `runtimeContextProvider`. */
  contextSupplement: () => string
  /** Trigger bounded-memory compaction. */
  compact: () => Promise<void>
  readonly discourse: DiscourseMemory
}

/**
 * Continuous-learning orchestrator. Wires three reference ideas together:
 * - emotion_spirit: a 13-dim persona vector + leuke endocrine dynamics.
 * - LPM: bounded discourse memory sitting on top of AIJADE's layered `MemoryPort`.
 * - HY-Motion RL-from-feedback: user feedback is turned into skill evolution
 *   via the skill forge's `evolveSkill`.
 */
export function createContinuousLearning(options: ContinuousLearningOptions): ContinuousLearning {
  const { llm, memory, skillForge } = options
  const threshold = options.feedbackThreshold ?? 0.5
  const dynamics = resolveDynamics(options.dynamics)
  const extractor = options.signalExtractor === undefined
    ? createLexiconSignalExtractor()
    : options.signalExtractor
  const onPersonaUpdate = options.onPersonaUpdate
  let persona = createPersonaState(options.personaSeed)
  const discourse = createDiscourseMemory({ llm })
  let lastInteractionTs = Date.now()

  function applySignal(signal: InteractionSignal, role?: 'user' | 'assistant'): void {
    persona = applyInteraction(persona, signal, dynamics)
    onPersonaUpdate?.({ state: persona, cause: 'interaction', timestamp: persona.updatedAt, role, signal })
  }

  function ingestTurn(role: 'user' | 'assistant', text: string, signal?: InteractionSignal): void {
    discourse.ingest(role, text)
    if (memory) {
      if (role === 'user')
        void memory.ingestUser(text)
      else
        void memory.ingestAssistant(text)
    }

    // The interaction-driven path used to be dead: callers never passed a
    // signal, so `applyInteraction` never ran and the persona only ever moved
    // with wall-clock drift. Deriving a signal here makes the path live for
    // every caller, existing ones included.
    const resolved = signal ?? (extractor ? extractor(text, role) : undefined)
    if (resolved instanceof Promise) {
      void resolved.then(s => applySignal(s, role)).catch((err) => {
        logger.warn(`async signal extraction failed: ${(err as Error).message}`)
      })
    }
    else if (resolved) {
      applySignal(resolved, role)
    }
    lastInteractionTs = Date.now()
  }

  function tick(dtMs: number): void {
    persona = drift(persona, dtMs, dynamics)
    onPersonaUpdate?.({ state: persona, cause: 'drift', timestamp: persona.updatedAt })
  }

  /** The dynamics parameters actually in force. Record these with every observation. */
  function getDynamics(): PersonaDynamicsConfig {
    return dynamics
  }

  function idleMs(): number {
    return Date.now() - lastInteractionTs
  }

  async function captureFeedback(feedback: string, relatedText?: string): Promise<void> {
    if (!skillForge) {
      logger.debug('captureFeedback: no skillForge wired; skipping evolution')
      return
    }
    const skills = skillForge.registry.list()
    if (skills.length === 0)
      return
    const haystack = (relatedText ?? feedback).toLowerCase()
    const firstWord = (haystack.split(/\s+/)[0] ?? '').replace(/[^a-z0-9-]/g, '')
    const match = skills.find(s =>
      haystack.includes(s.frontmatter.name.toLowerCase())
      || (firstWord && s.frontmatter.description.toLowerCase().includes(firstWord)),
    )
    if (!match) {
      logger.debug('captureFeedback: no skill matched the feedback')
      return
    }
    try {
      const evolved = await skillForge.evolveSkill(match, feedback)
      skillForge.registry.add(evolved)
      logger.info(`evolved skill "${match.frontmatter.name}" from feedback: ${feedback.slice(0, 60)}`)
    }
    catch (err) {
      logger.warn(`skill evolution failed: ${(err as Error).message}`)
    }
    void threshold
  }

  function contextSupplement(): string {
    const personaCtx = toContext(persona)
    const discourseCtx = discourse.context()
    return `${personaCtx}\n\n${discourseCtx}`.trim()
  }

  async function compact(): Promise<void> {
    await discourse.compact()
    if (memory?.maybeCompact)
      void memory.maybeCompact()
  }

  return {
    getPersona: () => persona,
    getDynamics,
    ingestTurn,
    tick,
    idleMs,
    captureFeedback,
    contextSupplement,
    compact,
    discourse,
  }
}
