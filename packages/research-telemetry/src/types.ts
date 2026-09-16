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

  /**
   * Audit record of the render that produced (or accompanied) this turn.
   *
   * Optional because not every turn implies a render — a text-only turn may
   * carry no `render` at all. When present it is the concrete landing spot for
   * the design doc's `applied_params_hash` / `asset_version_hash`, so a render
   * is reproducible and attributable post-hoc.
   */
  render?: RenderAuditEntry
}

// ---------------------------------------------------------------------------
// Render audit (the "what was actually written to a render" record)
// ---------------------------------------------------------------------------

/**
 * Deterministic identity of the rendered model asset.
 *
 * `assetVersionHash` comes from the stage side (see
 * `@proj-aijade/stage-ui` `resolveAssetVersionHash`): it is a content hash for
 * file models and a *reference* hash (url + format) for url models.
 */
export interface AssetIdentity {
  /** Deterministic hash of the rendered model asset's content or reference. */
  assetVersionHash: string
  format: string
  displayModelId: string
  renderer: string
}

/**
 * 实际写入渲染模型的「通道名 → 值」映射。
 *
 * 为什么值类型是标量**联合**而不是只有 `number`：表现层真实写入的通道分三类，
 * 只有第一类是数值 ——
 * 1. **数值型**：情绪强度 `emotion.intensity`、眨眼速率倍率 `blink.rateScale`
 * 2. **类别型**：表情预设名 `emotion.preset`、注视方向 `gaze.dir`、手势名 `gesture`
 * 3. **开关型**：是否进入接话状态 `blink.engaged`
 *
 * 若强行只收 `number`，就必须给后两类编造虚假数值编码 —— 那会让"记录到底写了什么"
 * 这件事本身失真，而这份记录的全部意义恰恰是可复现。
 */
export type AppliedParams = Record<string, number | string | boolean>

/**
 * One auditable record of a single render: exactly which parameters were
 * actually written to the model, plus the asset identity, so a render is
 * reproducible and attributable. This is the concrete landing spot for the
 * design doc's `applied_params_hash` / `asset_version_hash`.
 *
 * The kernel-side provenance fields (`pgcStateId`, `evidencePackId`,
 * `contradictionGate`, `tick`, `seed`) are optional: the stage/ui producers can
 * build a complete entry from their own knowledge, but the deeper kernel
 * provenance is only available when the v9-kernel supplies it. Each optional
 * field documents *why* it may be absent.
 */
export interface RenderAuditEntry {
  sessionId: string
  turnIndex: number
  timestamp: number
  wallClock: string
  renderer: string
  displayModelId: string
  assetVersionHash: string
  /**
   * 规范化的「实写通道→值」文本形式（由 `fingerprintAppliedParams` 产出）。
   *
   * ⚠️ 它不是密码学摘要：本仓库的房规是**键排序后的 `key=value` 串**（见
   * `render-audit.ts` 的文件头注释）。所以它可能较长，且**空 map 时是 `''`**。
   * 名字里的 "hash" 沿用设计稿口径；语义以 `render-audit.ts` 为准。
   */
  appliedParamsHash: string
  /** 实际写入模型的 通道名→值 映射（数值/类别/开关三类通道混存，见 {@link AppliedParams}）。 */
  appliedParams: AppliedParams
  // 以下为内核侧溯源，只有内核提供时才存在
  /** Kernel-side PGC state id. Optional: only the v9-kernel producer emits it; stage/ui producers have no such id. */
  pgcStateId?: string
  /** Kernel evidence-pack id. Optional: only the kernel attaches an evidence pack; UI-side audit entries carry none. */
  evidencePackId?: string
  /** Contradiction-gate verdict. Optional: only set when the kernel's contradiction gate actually ran; non-kernel renderers never produce it. */
  contradictionGate?: 'reject' | 'clamp' | 'allow'
  /** Kernel simulation tick. Optional: only meaningful for kernel-driven renders; UI renderers have no tick. */
  tick?: number
  /** Kernel RNG seed. Optional: only the kernel provides the seed it sampled from; UI-side entries have none. */
  seed?: number
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
