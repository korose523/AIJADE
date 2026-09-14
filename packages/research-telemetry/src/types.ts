/**
 * Core data types for the research telemetry layer.
 *
 * Design goals (driven by what a publishable experiment actually needs):
 *
 * 1. **Longitudinal by construction.** Every record carries `sessionId` +
 *    `turnIndex` + `timestamp`, so week/month-scale trajectories can be
 *    reconstructed without any extra bookkeeping. (Gap #1: the time-scale
 *    vacuum — nobody has run a controlled week-scale study with the agent's
 *    internal state as the manipulated variable.)
 *
 * 2. **Ablation-ready.** Every record is bound to an `AblationConfig` and its
 *    fingerprint, so conditions can be grouped for parameter-sensitivity
 *    analysis without ambiguity. (Gap #2: no ablation / parameter sensitivity
 *    exists for affect dynamics used to *drive generation*.)
 *
 * 3. **Cost-aware.** Latency and token accounting are first-class, per-stage,
 *    so the persona-consistency × latency × memory-cost Pareto frontier can be
 *    plotted directly from the export. (Gap #3: no full-stack system has
 *    reported this trade-off surface.)
 *
 * The persona types are structurally cloned from
 * `@proj-aijade/agent-continuous-learning` on purpose — this package must stay
 * dependency-free so it can be imported from any runtime (browser, Electron
 * main, Electron renderer, Node service) without pulling in the whole agent
 * stack. TypeScript structural typing keeps them interchangeable.
 */

// ---------------------------------------------------------------------------
// Affective / persona state
// ---------------------------------------------------------------------------

/** The 13 stable persona traits (0..1). Mirrors `PersonaVector`. */
export interface PersonaVectorSnapshot {
  openness: number
  warmth: number
  curiosity: number
  patience: number
  formality: number
  playfulness: number
  caution: number
  confidence: number
  empathy: number
  spontaneity: number
  diligence: number
  assertiveness: number
  stability: number
}

/** 5 tick-decaying hormones (0..1). Mirrors `EndocrineState`. */
export interface EndocrineSnapshot {
  dopamine: number
  serotonin: number
  cortisol: number
  oxytocin: number
  adrenaline: number
}

/** Pleasure / Arousal / Dominance. Mirrors `PADState`. */
export interface PADSnapshot {
  pleasure: number
  arousal: number
  dominance: number
}

/** Big-Five, derived from the persona vector. Mirrors `BigFive`. */
export interface BigFiveSnapshot {
  O: number
  C: number
  E: number
  A: number
  N: number
}

/** Six asymmetric intimacy dimensions. Mirrors `IntimacyState`. */
export interface IntimacySnapshot {
  warmth: number
  trust: number
  dependence: number
  security: number
  familiarity: number
  longing: number
}

/**
 * A full persona snapshot at a single point in time.
 *
 * Captured *after* a turn is processed, so the series is the actual
 * state trajectory rather than an intent.
 */
export interface PersonaSnapshot {
  vector: PersonaVectorSnapshot
  endocrine: EndocrineSnapshot
  pad: PADSnapshot
  bigFive: BigFiveSnapshot
  intimacy: IntimacySnapshot
  /** Render-time mood label, e.g. "motivated". Useful as a categorical column. */
  moodLabel?: string
  /** Emoji projection, retained for qualitative inspection of logs. */
  moodEmoji?: string
}

// ---------------------------------------------------------------------------
// Performance & cost
// ---------------------------------------------------------------------------

/**
 * Per-stage latency in milliseconds.
 *
 * Every field is optional because not every turn goes through every stage
 * (e.g. a text-only turn has no `asr` / `tts`). Analysis code should treat
 * missing values as "stage not exercised", NOT as zero.
 */
export interface LatencyBreakdown {
  /** Voice activity detection. */
  vad?: number
  /** Automatic speech recognition. */
  asr?: number
  /** LLM generation. */
  llm?: number
  /** Speech synthesis. */
  tts?: number
  /** Lip-sync driving. */
  lipsync?: number
  /** Memory / vector retrieval. */
  memoryRetrieval?: number
  /** End-to-end, user-facing. */
  total?: number
}

/** Token accounting. */
export interface TokenUsage {
  prompt?: number
  completion?: number
  /** Tokens spent injecting retrieved memory / persona context. */
  memoryInjected?: number
}

// ---------------------------------------------------------------------------
// Dynamics parameters (the manipulated variables for Gap #2)
// ---------------------------------------------------------------------------

/**
 * The tunable knobs of the affective dynamics.
 *
 * Why this is first-class: the existing affect-dynamics literature
 * (Garcia et al., Royal Society Open Science 2016; Pellert et al., EPJ Data
 * Science 2020; the Affective Ising Model) fitted these parameters against
 * **human self-reported emotion traces**. Nobody has validated them for the
 * purpose of *driving LLM generation* — that is the open question this project
 * is positioned to answer, and answering it requires the parameters to be
 * recorded alongside every observation.
 *
 * CTEM/Auri (CHI '26) ablated *discrete modules* (BGI/AdI/ESU) over 21 days;
 * a continuous parameter sweep is a different and still-open experiment.
 */
export interface DynamicsParameters {
  /** Relaxation time constant — how fast state returns to baseline (ms). */
  relaxationMs?: number
  /** Per-dimension baseline the state reverts toward. */
  baseline?: Partial<PersonaVectorSnapshot>
  /** Endocrine → persona coupling coefficients (0 = uncoupled). */
  hormoneCoupling?: Partial<Record<keyof EndocrineSnapshot, number>>
  /** Per-tick noise intensity (σ). */
  noiseSigma?: number
  /** Drift tick interval (ms). */
  tickIntervalMs?: number
  /** Interaction-driven update gain applied in `applyInteraction`. */
  interactionGain?: number
}

// ---------------------------------------------------------------------------
// Turn record
// ---------------------------------------------------------------------------

export type TurnRole = 'user' | 'assistant' | 'system'

/**
 * One recorded interaction turn.
 *
 * This is the atomic unit of every analysis the project will ever produce:
 * longitudinal trajectories, ablations, and Pareto frontiers are all computed
 * by grouping and reducing over this shape.
 */
export interface TurnRecord {
  /** Stable id of the experiment session this turn belongs to. */
  sessionId: string
  /** Monotonic 0-based index within the session. */
  turnIndex: number
  /** Epoch milliseconds. */
  timestamp: number
  /** ISO-8601, for human-readable exports. */
  wallClock: string
  role: TurnRole

  /** Affective state *after* this turn was processed. */
  persona?: PersonaSnapshot

  /** Skill-forge state (RQ-C: skill discovery precision / hallucination rate). */
  skillLibrarySize?: number
  skillsCreatedThisTurn?: number
  skillsRejectedThisTurn?: number

  latency?: LatencyBreakdown
  tokens?: TokenUsage
  /** Number of memory items actually injected into the prompt. */
  memoryHits?: number

  /**
   * Character length of the turn text (kept instead of raw text by default —
   *  see `RecordTextPolicy` — to keep logs shareable under IRB constraints).
   */
  textLength?: number

  /**
   * The dynamics parameters in force at this turn.
   *
   * Normally constant for a session (see `SessionMeta.parameters`); recorded
   * per turn as well so that adaptive / annealed schedules remain analysable.
   */
  parameters?: DynamicsParameters

  /** Free-form hook for experiment-specific columns. */
  metadata?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Ablation
// ---------------------------------------------------------------------------

/**
 * The ablation switches.
 *
 * Each maps to one component whose contribution can be measured.
 * Default is "everything on" so existing behaviour is preserved unless a
 * researcher explicitly disables something.
 */
export interface AblationConfig {
  /** Master switch: affect dynamics (applyInteraction + drift). */
  personaDynamics: boolean
  /** Endocrine → persona coupling inside `drift`. */
  hormoneCoupling: boolean
  /** Memory retrieval / injection. */
  memoryRetrieval: boolean
  /** Automatic skill creation. */
  skillForge: boolean
  /** Discourse memory (bounded recent-turn buffer). */
  discourseMemory: boolean
}

/** Fully-enabled baseline. */
export const FULL_ABLATION: Readonly<AblationConfig> = Object.freeze({
  personaDynamics: true,
  hormoneCoupling: true,
  memoryRetrieval: true,
  skillForge: true,
  discourseMemory: true,
})

/** A named condition, e.g. `no-hormone-coupling`. */
export interface AblationCondition {
  name: string
  config: AblationConfig
  /** Short human note on what this condition is meant to isolate. */
  description?: string
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

export interface SessionMeta {
  sessionId: string
  /** Condition name this session runs under (e.g. `baseline`, `no-memory`). */
  condition: string
  /**
   * Deterministic fingerprint of the ablation config — used to group sessions
   *  that are genuinely the same condition across participants / reruns.
   */
  configFingerprint: string
  startedAt: number
  /** Non-PII participant / run identifier. Keep non-PII under IRB. */
  participantId?: string
  /**
   * The dynamics parameter point this session is assigned to.
   *
   * This is what makes a parameter sweep analysable: each session is one cell
   * of the sweep, and the fingerprint lets you group replicates.
   */
  parameters?: DynamicsParameters
  /** Deterministic fingerprint of `parameters`, for grouping replicates. */
  parameterFingerprint?: string
  /** Free-form, e.g. model name, app version, platform. */
  tags?: Record<string, string>
}

export interface ExperimentSession extends SessionMeta {
  endedAt?: number
  turnCount: number
}
