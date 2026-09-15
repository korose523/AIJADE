/**
 * L4 biomimetic long-term memory — core types.
 *
 * ## The claim this package exists to test
 *
 * Long-term memory in an agent is usually built as *retrieval over a log*:
 * embed everything, search by similarity, maybe decay by age. That is a storage
 * problem, and it is already well solved (see LPM, arXiv 2606.20911, which
 * compresses history into latent slots far better than we need to).
 *
 * What is **not** solved — and what human memory actually spends its effort on —
 * is the *dynamics*: what gets consolidated, what gets forgotten, and what
 * determines either. This package implements those dynamics.
 *
 * ## v2 / P2 re-frame (this revision)
 *
 * A just-completed experiment (A1, commit `ee1910f`) proved that physiological
 * state* contributes ~0 to recall gain (H2c gap ≈ 0); the real mechanism is
 * content / discourse salience driving selective retention. So:
 *
 * - The memory gate is now driven by content salience (from
 *   `predictSalienceV2` in `src/salience.ts`), NOT by hormones.
 * - L3 hormones are demoted to a SEPARATE `PresentationModulation` that only
 *   affects expression (tone / verbosity / …) and is disable-able via
 *   `MemoryConfig.physiology.enabled` (→ neutral, no effect on memory).
 *
 * The ablation (`gating: on` vs `off`, everything else identical) is preserved:
 * under `NO_GATING` the content coefficients are all 0, so durability collapses to
 * 1 and the decay exponent collapses to the base power law — the control.
 *
 * ## Mapping to human memory (kept explicit so it can be criticised)
 *
 * | Human system | Here |
 * |---|---|
 * | Episodic memory | `Episode` — event + time + context + content-salience encoding |
 * | Semantic memory | `SemanticFact` — distilled from episode clusters |
 * | Procedural memory | `ProceduralMemory` — how-to / skill |
 * | Working memory | `WorkingMemory` — short-term active buffer |
 * | Consolidation | `consolidate()` — offline, gated by **content salience** |
 * | Forgetting | `retrievalStrength()` — power-law decay, salience-modulated |
 * | Spacing effect | access count term in `retrievalStrength` |
 * | Retrieval | multi-cue: similarity + strength + recency + context |
 */

import type { Belief, BeliefRejection, BeliefRevision } from './belief'
import type { CbrConfig, ReplayBundle } from './cbr'
import type { EndogenousState, HacConfig } from './hac'
import type { CdiConfig, IdentityState, IdentityVersion } from './identity'
import type { InterventionConfig, ResolvedIntervention } from './intervention'

/** Affective snapshot (PAD). Kept 0..1 with 0.5 neutral for valence/dominance. */
export interface AffectiveSnapshot {
  /** 0 = negative, 0.5 = neutral, 1 = positive */
  valence: number
  arousal: number
  dominance: number
}

/**
 * @deprecated Physiological *state* no longer gates memory dynamics (A1 proved it
 * contributes ~0 to recall gain). It survives only as a historical type and for the
 * deprecated hormone `deriveGate`. Prefer {@link PhysiologicalStateV3} + the
 * disable-able {@link PresentationModulation}.
 */
export interface PhysiologicalState {
  dopamine: number
  serotonin: number
  cortisol: number
  oxytocin: number
  adrenaline: number
  affect: AffectiveSnapshot
  /** 0..1 closeness to the current interlocutor; weights social memories. */
  intimacy?: number
}

export interface EpisodeContext {
  sessionId?: string
  interlocutor?: string
  task?: string
  tags: string[]
}

/**
 * Content-derived salience used to drive the memory gate. All fields ∈ [0,1]
 * after normalisation at encode time.
 */
export interface ContentSalience {
  /** Overall long-term-memory value of the content (sigmoid of the v2 predictor score). */
  salience: number
  /** Social weight proxy: second-person / person-name density. */
  socialSalience: number
  /** Novelty proxy (v2 `noveltyIdf` feature). */
  novelty: number
}

export interface Episode {
  id: string
  content: string
  createdAt: number
  lastAccessedAt: number
  accessCount: number
  /** Baseline strength before any gating multiplier (default 1). */
  baseStrength: number
  /**
   * Durability multiplier, computed at encode time from the **content salience**
   * under the current gating config. Salient episodes get >1; under NO_GATING
   * everything is exactly 1. This single number is what makes the ablation
   * produce different retention.
   */
  durability: number
  /** Salience at the moment of encoding. Drives durability + retrieval decay rate. */
  encoding: {
    /** Overall salience ∈ [0,1] (sigmoid of `predictSalienceV2` score). */
    salience: number
    /** Social-salience proxy ∈ [0,1]. */
    socialSalience: number
    /** Novelty proxy ∈ [0,1]. */
    novelty: number
    /** Affective snapshot at encoding (carried for provenance; not used in scoring). */
    affect: AffectiveSnapshot
  }
  context: EpisodeContext
  embedding?: number[]
  consolidated: boolean
  /** Set true when gating judged this episode not worth keeping and pruned it. */
  forgotten?: boolean
  /** L4 discriminator. */
  memoryType: MemoryType
  /** Lifecycle status (audit / supersession). */
  status: MemoryStatus
  /** Temporal validity window. */
  validTime: ValidTime
}

export interface SemanticFact {
  id: string
  content: string
  /** Episodes this fact was distilled from; kept for provenance + audit. */
  derivedFrom: string[]
  createdAt: number
  lastAccessedAt: number
  accessCount: number
  confidence: number
  /**
   * Baseline strength before gating; for facts this already bakes in the
   * average durability of the source episodes (set at consolidation).
   */
  baseStrength: number
  /** Same semantics as Episode.durability. */
  durability: number
  /** Carried over from source episodes so retrieval scoring is uniform. */
  contextTags: string[]
  /** Salience of the source content, reused for salience-driven decay at retrieval. */
  salience: number
  affect: AffectiveSnapshot
  embedding?: number[]
  /** L4 discriminator. */
  memoryType: MemoryType
  /** Lifecycle status (audit / supersession). */
  status: MemoryStatus
  /** Temporal validity window. */
  validTime: ValidTime
}

/**
 * How-to / skill memory (procedural). Survives by repetition + consolidation;
 * `confidence` tracks how well-established the skill is.
 */
export interface ProceduralMemory {
  id: string
  content: string
  /** Episode / fact this skill was derived from, if any. */
  derivedFrom?: string
  createdAt: number
  lastAccessedAt: number
  accessCount: number
  baseStrength: number
  durability: number
  contextTags: string[]
  validTime: ValidTime
  status: MemoryStatus
  memoryType: 'procedural'
  /** 0..1 how well-established the skill is. */
  confidence: number
}

/**
 * Short-term active buffer (working memory). Same shape as procedural/semantic
 * but scoped to the immediate context; typically low durability and short-lived.
 */
export interface WorkingMemory {
  id: string
  content: string
  createdAt: number
  lastAccessedAt: number
  accessCount: number
  baseStrength: number
  durability: number
  contextTags: string[]
  validTime: ValidTime
  status: MemoryStatus
  memoryType: 'working'
}

/**
 * L4 memory-type discriminator.
 *
 * v7 §10.3: seven **views** over the underlying store. Physically the store keeps
 * events, propositions, programs and media objects; these seven are the views
 * exposed upward — deliberately, to avoid physically duplicating content.
 */
export type MemoryType
  = | 'episodic'
    | 'semantic'
    | 'procedural'
    | 'working'
    | 'emotional'
    | 'relational'
    | 'reflective'

/**
 * Lifecycle status (v7 §10.4).
 *
 *   Candidate → Quarantine → Episodic → Reviewed → Semantic/Procedural
 *            → Consolidated → Decayed/Archived/Retracted
 *
 * `active` / `expired` / `superseded` are retained for backwards compatibility
 * with pre-v7 code paths; `expired` is terminal alongside
 * `archived` / `retracted` / `decayed`.
 */
export type MemoryStatus
  = | 'active'
    | 'expired'
    | 'superseded'
    | 'candidate'
    | 'quarantine'
    | 'episodic'
    | 'reviewed'
    | 'semantic'
    | 'procedural'
    | 'consolidated'
    | 'decayed'
    | 'archived'
    | 'retracted'

/** Statuses that make a memory non-retrievable (terminal). */
export const TERMINAL_MEMORY_STATUSES: readonly MemoryStatus[] = [
  'expired',
  'archived',
  'retracted',
  'decayed',
]

/** True when a memory in this status may still be retrieved. */
export function isRetrievableStatus(s: MemoryStatus): boolean {
  return !TERMINAL_MEMORY_STATUSES.includes(s)
}

/** Temporal validity window. A memory is retrievable only while `now` is inside it. */
export interface ValidTime {
  validFrom?: number
  validUntil?: number
}

/**
 * Coefficients mapping **content salience** onto memory dynamics.
 *
 * Every one of these is a hypothesis, not a constant of nature. They are
 * configurable precisely so they can be ablated: setting all of them to 0
 * reduces the model to ungated decay, which is the control condition.
 */
export interface GatingCoefficients {
  /** Content salience → durability multiplier + slower decay. */
  kSalience: number
  /** Social salience → durability multiplier. */
  kSocial: number
  /** Novelty → retrieval breadth / exploration temperature. */
  kNovelty: number
}

/** All-zero gating = the control condition (pure decay, no content modulation). */
export const NO_GATING: GatingCoefficients = {
  kSalience: 0,
  kSocial: 0,
  kNovelty: 0,
}

export const DEFAULT_GATING: GatingCoefficients = {
  kSalience: 0.8,
  kSocial: 0.5,
  kNovelty: 0.3,
}

export interface ForgettingConfig {
  /** Base decay exponent d0 for the power law (1 + age)^-d. */
  baseDecay: number
  /** Spacing-effect exponent: each successful retrieval multiplies by (1+n)^beta. */
  spacingBeta: number
  /** Age is normalised by this before the power law, so decay is scale-free. */
  ageScaleMs: number
}

export const DEFAULT_FORGETTING: ForgettingConfig = {
  baseDecay: 0.35,
  spacingBeta: 0.5,
  ageScaleMs: 86_400_000, // one day
}

export interface RetrievalWeights {
  similarity: number
  strength: number
  recency: number
  context: number
  /**
   * @deprecated Mood-congruent affect is now a **presentation-only** concern and
   * is not used in the memory score. Kept for telemetry/explanation; the store
   * passes 0 for this term at retrieval.
   */
  affect: number
}

export const DEFAULT_RETRIEVAL_WEIGHTS: RetrievalWeights = {
  similarity: 1,
  strength: 0.6,
  recency: 0.3,
  context: 0.4,
  affect: 0.25,
}

/**
 * How the four retrieval components are combined before weighting. See
 * {@link MemoryConfig.retrievalScoreMode}.
 */
export type RetrievalScoreMode = 'additive' | 'standardized'

/**
 * Belief-graph thresholds (v7 §10.2; contract #5 `BeliefRevision`).
 *
 * Every threshold is configurable precisely so it can be ablated.
 */
export interface BeliefConfig {
  /** Confidence at/above which a belief becomes `accepted`. */
  acceptThreshold: number
  /** Confidence at/below which a belief is auto-`retracted`. */
  retractThreshold: number
  /** Counter-evidence share of total logit mass that marks a belief `contested`. */
  contestedRatio: number
  /** Hard bound on a single evidence contribution |ℓ_k| — the validator clamp. */
  maxAbsLikelihood: number
  /** Prior confidence for a freshly proposed belief. */
  priorConfidence: number
}

export const DEFAULT_BELIEF_CONFIG: BeliefConfig = {
  acceptThreshold: 0.65,
  retractThreshold: 0.2,
  contestedRatio: 0.5,
  maxAbsLikelihood: 2,
  priorConfidence: 0.5,
}

export interface MemoryConfig {
  gating: GatingCoefficients
  forgetting: ForgettingConfig
  weights: RetrievalWeights
  /** Consolidate once the unconsolidated buffer reaches this size. */
  consolidateThreshold: number
  /** Hard floor below which a memory is treated as inaccessible. */
  retrievalFloor: number
  /**
   * How the four retrieval components are combined before weighting.
   *
   * - `'standardized'` (default) — each component is z-scored **within the
   *   candidate pool** and only then weighted; see
   *   `scoreCandidatesStandardized` in `retrieval.ts`.
   * - `'additive'` — the legacy raw weighted sum, kept so previously published
   *   numbers stay reproducible. It also retains the legacy K-dependent
   *   R-conflict reranking, because the two only diverge together in practice.
   *
   * Why this exists: on real corpora the components are **not** on comparable
   * scales (a sparse TF-IDF cosine between a short query and a long utterance
   * lands around 0.05–0.2, while the saturated strength and recency terms sit
   * near 0.5–1.0). A raw weighted sum therefore does not express the weights as
   * importance at all — it silently hands the ranking to whichever component
   * happens to occupy the widest absolute range. Standardising first makes the
   * weights mean what they were always documented to mean, **without changing
   * any weight value**.
   */
  retrievalScoreMode: RetrievalScoreMode
  /**
   * Collapse candidates whose whitespace-normalised content is identical,
   * keeping the `episode` for provenance. `LexicalDistiller` emits one fact per
   * episode carrying byte-identical content, so with this disabled every piece
   * of evidence occupies two ranks and `recall@K` is really `recall@K/2`.
   */
  dedupeByContent: boolean
  /**
   * L3 presentation layer. When `enabled` is false, the hormone-driven
   * `PresentationModulation` is forced to neutral and has **no** effect on memory
   * (it only ever affected expression, never the gate).
   */
  physiology: { enabled: boolean }
  /** Multiplier applied to the *loser* of a detected retrieval conflict (≤1). */
  conflictPenalty: number
  /** Belief-graph thresholds (v7 §10.2). Optional for backwards compatibility. */
  belief?: BeliefConfig
  /** HAC endogenous-state + gates (v7 §9). Optional; off unless explicitly enabled. */
  hac?: HacConfig
  /**
   * v7 §11 CDI (constrained developmental identity) configuration. Independently
   * tunable; the CDI controller is only constructed when the HAC+CDI closed loop
   * is enabled (`config.hac?.enabled`), so it never perturbs the baseline.
   */
  cdi?: CdiConfig
  /**
   * v7 §38 统一干预 API（基线/消融登记）。opt-in：仅当 `enabled` 显式 true 才接入；
   * 接入后仅描述「这次跑的是哪套配置」，绝不改动记忆 durability/salience（H2c）。
   */
  intervention?: InterventionConfig
  /**
   * v7 §12 CBR（因果具身回放 + 配对 ITE 估计）研究内核。opt-in，与 HAC/CDI 解耦
   * （P8/§43）；只持有回放证据，不介入记忆动力学。
   */
  cbr?: CbrConfig
  /**
   * v7 §26 storage tiering — opt-in persistence adapter. When omitted (default),
   * the store is fully in-memory and nothing is written to disk. The adapter only
   * ever *carries* state; it must never decide retention or salience (§9.3 / H2c).
   */
  storage?: StorageAdapter
}

/**
 * v7 §26 — a serializable point-in-time snapshot of the store's durable state.
 * Adapters persist/restore this shape; the store itself decides what goes in.
 */
export interface StoreSnapshotV1 {
  schema: 'aijade.store_snapshot@1'
  /** Config at snapshot time (adapter stripped — the rehydrating instance supplies its own). */
  config: MemoryConfig
  collections: {
    episodes: Episode[]
    facts: SemanticFact[]
    procedural: ProceduralMemory[]
    working: WorkingMemory[]
    beliefs: Belief[]
    beliefRevisions: BeliefRevision[]
    beliefRejections: BeliefRejection[]
  }
  /** HAC endogenous state + monotonic call counter (only when HAC enabled). */
  hac?: { z: EndogenousState, call: number }
  /** CDI identity state + signed version history (only when the closed loop is enabled). */
  cdi?: { state: IdentityState, versions: IdentityVersion[] }
  /** §38 已解析干预（仅当干预 API 接入时）。携带 resolved 状态以便复现。 */
  intervention?: { resolved: ResolvedIntervention }
  /** §12 CBR 回放日志（仅当 CBR 接入时）。 */
  cbr?: { bundles: ReplayBundle[] }
}

/**
 * v7 §26 storage tiering — the single abstraction the store depends on. Concrete
 * adapters (in-memory, JSON file, …) implement this; the store stays agnostic to
 * the physical medium. All methods are synchronous so durability never perturbs
 * the memory dynamics (no async I/O in the gate path).
 */
export interface StorageAdapter {
  readonly kind: string
  persist: (snapshot: StoreSnapshotV1) => void
  load: () => StoreSnapshotV1 | null
  clear: () => void
}

export const DEFAULT_MEMORY_CONFIG: MemoryConfig = {
  gating: { ...DEFAULT_GATING },
  forgetting: { ...DEFAULT_FORGETTING },
  weights: { ...DEFAULT_RETRIEVAL_WEIGHTS },
  consolidateThreshold: 8,
  retrievalFloor: 0.02,
  retrievalScoreMode: 'standardized',
  dedupeByContent: true,
  physiology: { enabled: true },
  conflictPenalty: 0.5,
  belief: { ...DEFAULT_BELIEF_CONFIG },
}

export type CandidateKind = 'episode' | 'fact' | 'procedural' | 'working'

export interface ScoredCandidate {
  kind: CandidateKind
  id: string
  content: string
  score: number
  /** Component scores, exposed so a surprising retrieval can be explained. */
  parts: {
    similarity: number
    strength: number
    recency: number
    context: number
    /** Presentation-only; 0 in the memory score. */
    affect: number
    /**
     * 注入的检索噪声幅值（v3 §5）。内容驱动 gate 下由 novelty 决定；恒等
     * content（中性）下为 0。
     */
    noise?: number
    /** True if this candidate was penalised as the *loser* of an R-conflict. */
    conflict?: boolean
    /**
     * `'standardized'` mode only — the z-scored component values that were
     * actually weighted. The sibling scalars above stay **raw** so a surprising
     * retrieval can be read from either side of the standardisation.
     */
    z?: {
      similarity: number
      strength: number
      recency: number
      context: number
    }
    /**
     * Ids collapsed into this candidate by content deduplication. The collapsed
     * memories remain in the store for audit; they are only excluded from
     * ranking.
     */
    deduplicatedIds?: string[]
  }
}

export interface ConsolidationResult {
  facts: SemanticFact[]
  /** Episode ids that were consumed. */
  consumed: string[]
  /** Clusters skipped because gating judged them not worth consolidating. */
  skipped: { episodeIds: string[], reason: string }[]
}

// ============================================================================
// L3 — three-layer physiological state + disable-able presentation modulation
// ============================================================================

/** A single hormone layer (all ∈ [0,1]). */
export interface HormoneLevels {
  dopamine: number
  serotonin: number
  cortisol: number
  oxytocin: number
  adrenaline: number
}

/**
 * Layered L3 state (v4): trait / baseline, mood / state, transient / acute.
 * The store never reads this for the memory gate; it is only consumed by
 * {@link derivePresentationModulation} when `MemoryConfig.physiology.enabled`.
 */
export interface PhysiologicalStateV3 {
  /** Baseline personality-level hormone set. */
  trait: HormoneLevels
  /** Slower-moving mood state. */
  mood: HormoneLevels
  /** Acute, moment-to-moment transient. */
  transient: HormoneLevels
  /** Current affect snapshot. */
  affect: AffectiveSnapshot
  /** 0..1 closeness to the current interlocutor. */
  intimacy?: number
}

/**
 * Expression-only modulation derived from the layered L3 state. Never affects
 * memory dynamics; only how a memory would be *phrased* if surfaced.
 */
export interface PresentationModulation {
  /** 0..1 warmth (oxytocin / serotonin). 0.5 = neutral. */
  warmth: number
  /** 0..1 verbosity (dopamine / arousal). 0.5 = neutral. */
  verbosity: number
  /** 0..1 hesitation (cortisol). 0 = neutral. */
  hesitation: number
  /** 0..1 energy (adrenaline / arousal). 0.5 = neutral. */
  energy: number
}

/** Neutral presentation = no expressive bias. Returned when physiology is disabled. */
export const NEUTRAL_PRESENTATION: PresentationModulation = Object.freeze({
  warmth: 0.5,
  verbosity: 0.5,
  hesitation: 0,
  energy: 0.5,
})

/** Neutral affect, used as the encode-time fallback. */
export const NEUTRAL_AFFECT: AffectiveSnapshot = Object.freeze({
  valence: 0.5,
  arousal: 0.5,
  dominance: 0.5,
})

/** Neutral three-layer state (all hormones 0.5, affect neutral). */
export const NEUTRAL_PHYSIOLOGY_V3: PhysiologicalStateV3 = Object.freeze({
  trait: { dopamine: 0.5, serotonin: 0.5, cortisol: 0.5, oxytocin: 0.5, adrenaline: 0.5 },
  mood: { dopamine: 0.5, serotonin: 0.5, cortisol: 0.5, oxytocin: 0.5, adrenaline: 0.5 },
  transient: { dopamine: 0.5, serotonin: 0.5, cortisol: 0.5, oxytocin: 0.5, adrenaline: 0.5 },
  affect: NEUTRAL_AFFECT,
  intimacy: 0.5,
})
