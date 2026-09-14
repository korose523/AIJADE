import type { PerformanceIntent } from './contracts-v8'

/**
 * v8 §52 — PEF: Persona–Expression Field (人格—表现场).
 *
 * PEF maps the persona stack — Constitutional Self + Character Self +
 * Developmental Self + Relationship Model + Expressive State + Dialogue Act +
 * Scene Context (§52.2) — onto a continuous expression vector e_t (§52.3) and
 * backend-agnostic output channels (text style / voice prosody / face / gaze /
 * gesture / posture / turn-taking / camera). The cognitive layer never depends
 * on a specific renderer: the backend may be a video-generative LPM or a
 * traditional Avatar (VRM / Live2D / MMD).
 *
 * Performance is incremental and full-duplex (§52.4): the system must NOT wait
 * for a complete long answer before generating motion. Every intent is
 * time-marked. After a generative video/motion model produces output, an
 * identity-consistency checker (§52.5) evaluates it; on failure the system
 * degrades to a controllable Avatar or pure voice — visual splendour may never
 * sacrifice identity continuity.
 *
 * Pure and deterministic; renderer wiring lives in the PerformanceDirector /
 * runtime layer.
 */

// ---------------------------------------------------------------------------
// §52.3 — the expression vector e_t
// ---------------------------------------------------------------------------

/**
 * Continuous expression vector (§52.3). All components ∈ [0,1] except
 * `valence` ∈ [−1,1].
 */
export interface ExpressionVector {
  /** −1 … +1: negative … positive affect. */
  valence: number
  arousal: number
  dominance: number
  intimacy: number
  certainty: number
  curiosity: number
  playfulness: number
  reflection: number
  urgency: number
}

/** Neutral baseline: a calm, attentive, mid-everything agent. */
export const NEUTRAL_EXPRESSION: ExpressionVector = {
  valence: 0,
  arousal: 0.4,
  dominance: 0.5,
  intimacy: 0.4,
  certainty: 0.6,
  curiosity: 0.5,
  playfulness: 0.3,
  reflection: 0.4,
  urgency: 0.2,
}

function clamp01(n: number): number {
  if (!Number.isFinite(n))
    return 0
  return Math.min(1, Math.max(0, n))
}

function clampValence(n: number): number {
  if (!Number.isFinite(n))
    return 0
  return Math.min(1, Math.max(-1, n))
}

/** Clamp every component of an expression vector into its legal range. */
export function clampExpression(e: ExpressionVector): ExpressionVector {
  return {
    valence: clampValence(e.valence),
    arousal: clamp01(e.arousal),
    dominance: clamp01(e.dominance),
    intimacy: clamp01(e.intimacy),
    certainty: clamp01(e.certainty),
    curiosity: clamp01(e.curiosity),
    playfulness: clamp01(e.playfulness),
    reflection: clamp01(e.reflection),
    urgency: clamp01(e.urgency),
  }
}

// ---------------------------------------------------------------------------
// §52.2 — persona → expression mapping
// ---------------------------------------------------------------------------

/** Dialogue acts recognised by the performance layer. */
export type DialogueAct
  = | 'inform'
    | 'question'
    | 'answer'
    | 'comfort'
    | 'celebrate'
    | 'apologise'
    | 'refuse'
    | 'backchannel'
    | 'greet'
    | 'farewell'
    | 'think_aloud'

/**
 * The seven persona-stack inputs of §52.2. All fields are optional except the
 * dialogue act — a missing layer simply contributes no adjustment.
 *
 * Note (§52.2): the Developmental Self carries interest/ability spectra,
 * milestones, aesthetics and autobiographical themes — never unverified
 * consciousness claims — so it modulates curiosity/reflection only.
 */
export interface PersonaInput {
  /** Constitutional Self: hard value boundaries + identity narrative. */
  constitutional?: {
    valueBoundaries?: string[]
    identityNarrative?: string
  }
  /** Character Self: stable personality baseline (partial vector). */
  character?: Partial<ExpressionVector>
  /** Developmental Self: growth-derived modulation. */
  developmental?: {
    interests?: string[]
    milestones?: string[]
    aesthetics?: string[]
    autobiographicalThemes?: string[]
  }
  /** Relationship Model: dyadic context with this user. */
  relationship?: {
    /** ∈ [0,1] — closeness with this user. */
    intimacy?: number
    /** ∈ [0,1] — 0 casual … 1 formal. */
    formality?: number
    boundaryTags?: string[]
  }
  /** Expressive State: transient affect right now (partial vector). */
  expressiveState?: Partial<ExpressionVector>
  /** Dialogue Act: what this turn is doing. */
  dialogueAct: DialogueAct
  /** Scene Context tag (also propagated for continuity checking). */
  sceneContext?: string
}

/** Weight of the transient expressive state vs. the stable baseline. */
export const EXPRESSIVE_STATE_WEIGHT = 0.6

/**
 * Per-dialogue-act nudges applied on top of the blended baseline. Values are
 * additive deltas before clamping.
 */
const DIALOGUE_ACT_DELTAS: Record<DialogueAct, Partial<ExpressionVector>> = {
  inform: { certainty: 0.1, reflection: 0.05 },
  question: { curiosity: 0.3, arousal: 0.1 },
  answer: { certainty: 0.15, curiosity: 0.05 },
  comfort: { intimacy: 0.3, arousal: -0.15, valence: 0.1, urgency: -0.1 },
  celebrate: { valence: 0.4, arousal: 0.25, playfulness: 0.2 },
  apologise: { valence: -0.2, dominance: -0.2, intimacy: 0.1, reflection: 0.15 },
  refuse: { certainty: 0.25, dominance: 0.2, playfulness: -0.2 },
  backchannel: { arousal: -0.1, urgency: -0.15, intimacy: 0.05 },
  greet: { valence: 0.2, arousal: 0.1, intimacy: 0.1 },
  farewell: { valence: 0.1, arousal: -0.1, reflection: 0.1 },
  think_aloud: { reflection: 0.3, curiosity: 0.15, certainty: -0.15, urgency: -0.1 },
}

/**
 * §52.2 — map the persona stack to a clamped expression vector.
 *
 * Composition order: Character baseline (over NEUTRAL) → blend with transient
 * Expressive State (weight EXPRESSIVE_STATE_WEIGHT) → Dialogue Act deltas →
 * Relationship modulation (intimacy scales the intimacy component, formality
 * suppresses playfulness) → Developmental modulation (interests/milestones
 * gently raise curiosity/reflection) → clamp.
 */
export function mapPersonaToExpression(input: PersonaInput): ExpressionVector {
  // 1. Character baseline over neutral.
  const base: ExpressionVector = { ...NEUTRAL_EXPRESSION, ...input.character }

  // 2. Blend transient expressive state.
  const blended: ExpressionVector = { ...base }
  if (input.expressiveState) {
    const w = EXPRESSIVE_STATE_WEIGHT
    for (const k of Object.keys(NEUTRAL_EXPRESSION) as (keyof ExpressionVector)[]) {
      const transient = input.expressiveState[k]
      if (typeof transient === 'number')
        blended[k] = base[k] * (1 - w) + transient * w
    }
  }

  // 3. Dialogue act deltas.
  const deltas = DIALOGUE_ACT_DELTAS[input.dialogueAct]
  for (const [k, d] of Object.entries(deltas) as [keyof ExpressionVector, number][])
    blended[k] += d

  // 4. Relationship modulation.
  if (input.relationship) {
    const rel = input.relationship
    if (typeof rel.intimacy === 'number')
      blended.intimacy = blended.intimacy * 0.5 + clamp01(rel.intimacy) * 0.5
    if (typeof rel.formality === 'number')
      blended.playfulness -= clamp01(rel.formality) * 0.3
  }

  // 5. Developmental modulation — growth evidence feeds curiosity/reflection.
  if (input.developmental) {
    const dev = input.developmental
    if (dev.interests && dev.interests.length > 0)
      blended.curiosity += Math.min(0.15, dev.interests.length * 0.02)
    if (dev.milestones && dev.milestones.length > 0)
      blended.reflection += Math.min(0.1, dev.milestones.length * 0.02)
  }

  return clampExpression(blended)
}

// ---------------------------------------------------------------------------
// §52.2/§52.3 — expression vector → backend-agnostic output channels
// ---------------------------------------------------------------------------

/** Backend-agnostic channel directives derived from an expression vector. */
export interface PerformanceChannels {
  textStyle: string
  voiceProsody: { rate: number, pitch: number, energy: number }
  face: string
  gaze: string
  gesture: string
  posture: string
  turnTaking: NonNullable<PerformanceIntent['turnTaking']>
  cameraBehavior: string
}

/**
 * Map a clamped expression vector + dialogue act onto output channels.
 * All thresholds are fixed so the mapping is deterministic and testable.
 */
export function deriveChannels(e: ExpressionVector, act: DialogueAct): PerformanceChannels {
  const v = clampExpression(e)

  // Voice prosody: rate ← urgency/arousal, pitch ← arousal/valence, energy ← arousal/dominance.
  const voiceProsody = {
    rate: clamp01(0.5 + v.urgency * 0.35 + (v.arousal - 0.5) * 0.3),
    pitch: clamp01(0.5 + (v.arousal - 0.5) * 0.4 + v.valence * 0.15),
    energy: clamp01(0.3 + v.arousal * 0.5 + (v.dominance - 0.5) * 0.2),
  }

  const textStyle
    = v.reflection > 0.65
      ? 'reflective'
      : v.playfulness > 0.6
        ? 'playful'
        : v.certainty > 0.75
          ? 'declarative'
          : v.intimacy > 0.65
            ? 'warm'
            : 'neutral'

  const face
    = v.valence > 0.3
      ? (v.arousal > 0.6 ? 'bright_smile' : 'soft_smile')
      : v.valence < -0.3
        ? (v.arousal > 0.6 ? 'concerned' : 'subdued')
        : v.curiosity > 0.65
          ? 'attentive_curious'
          : 'neutral_attentive'

  const gaze
    = v.intimacy > 0.6
      ? 'sustained_soft'
      : v.reflection > 0.65
        ? 'briefly_averted_thinking'
        : v.dominance > 0.7
          ? 'steady_direct'
          : 'natural_conversational'

  const gesture
    = v.arousal > 0.7 && v.playfulness > 0.5
      ? 'animated_open'
      : v.reflection > 0.65
        ? 'minimal_contained'
        : v.intimacy > 0.6
          ? 'gentle_open_palm'
          : 'rest_neutral'

  const posture
    = v.dominance > 0.7
      ? 'upright_forward'
      : v.arousal < 0.3
        ? 'relaxed_settled'
        : v.curiosity > 0.65
          ? 'leaning_in'
          : 'neutral_engaged'

  const turnTaking: PerformanceChannels['turnTaking']
    = act === 'backchannel'
      ? 'backchannel'
      : act === 'question'
        ? 'yield'
        : 'hold'

  const cameraBehavior
    = v.intimacy > 0.7
      ? 'close_up_slow_push'
      : v.arousal > 0.7
        ? 'medium_dynamic'
        : v.reflection > 0.65
          ? 'static_contemplative'
          : 'medium_static'

  return { textStyle, voiceProsody, face, gaze, gesture, posture, turnTaking, cameraBehavior }
}

/**
 * §52.4 — build a complete, time-marked incremental `PerformanceIntent`
 * (contract #28) from the persona stack. The result satisfies
 * `validatePerformanceIntent` by construction (all components clamped).
 */
export function buildPerformanceIntent(
  input: PersonaInput,
  ids: { id: string, agentId: string, userScope: string, personaSnapshotRef: string },
  timeMarked: number,
  duration: number,
): PerformanceIntent {
  const expression = mapPersonaToExpression(input)
  const channels = deriveChannels(expression, input.dialogueAct)
  return {
    id: ids.id,
    schema: 'aijade.performance_intent@1',
    agentId: ids.agentId,
    userScope: ids.userScope,
    personaSnapshotRef: ids.personaSnapshotRef,
    timeMarked,
    expression,
    textStyle: channels.textStyle,
    voiceProsody: channels.voiceProsody,
    face: channels.face,
    gaze: channels.gaze,
    gesture: channels.gesture,
    posture: channels.posture,
    turnTaking: channels.turnTaking,
    cameraBehavior: channels.cameraBehavior,
    sceneContext: input.sceneContext,
    duration,
  }
}

// ---------------------------------------------------------------------------
// §52.4 — full-duplex performance scheduling
// ---------------------------------------------------------------------------

/** Real-time events the performance scheduler reacts to (§52.4). */
export type DuplexEvent
  = | { type: 'listen_signal' } // user is speaking; backchannel opportunity
    | { type: 'partial_semantics' } // committed clause not ready; anticipate
    | { type: 'committed_clause' } // a clause is ready to perform
    | { type: 'user_interruption' } // user barged in

/** Scheduling decision for one duplex event. */
export interface DuplexDecision {
  turnTaking: NonNullable<PerformanceIntent['turnTaking']>
  /** Human-readable motion directive for the renderer layer. */
  motion: string
  /** Whether in-flight speech must be aborted. */
  abortSpeech: boolean
  /** Whether in-flight motion must blend out. */
  blendOutMotion: boolean
}

/**
 * §52.4 — full-duplex scheduling. Pure mapping:
 *
 *   Listen Signals    → Backchannel Planner  → micro-expression / nod / short ack
 *   Partial Semantics → Anticipatory Affect  → gaze & posture preparation
 *   Committed Clause  → Prosody + Gesture Phrase + Lip Timeline
 *   User Interruption → Speech Abort + Motion Blend-out + Listen Pose
 */
export function scheduleDuplex(event: DuplexEvent): DuplexDecision {
  switch (event.type) {
    case 'listen_signal':
      return { turnTaking: 'backchannel', motion: 'micro_expression_nod_short_ack', abortSpeech: false, blendOutMotion: false }
    case 'partial_semantics':
      return { turnTaking: 'hold', motion: 'anticipatory_gaze_posture_preparation', abortSpeech: false, blendOutMotion: false }
    case 'committed_clause':
      return { turnTaking: 'hold', motion: 'prosody_gesture_phrase_lip_timeline', abortSpeech: false, blendOutMotion: false }
    case 'user_interruption':
      return { turnTaking: 'yield', motion: 'listen_pose', abortSpeech: true, blendOutMotion: true }
  }
}

// ---------------------------------------------------------------------------
// §52.5 — identity-consistency checking with degrade policy
// ---------------------------------------------------------------------------

/**
 * Observations about one generated performance segment, produced by the
 * renderer-side evaluators. All drift/conflict scores ∈ [0,1] (0 = perfect).
 */
export interface ConsistencyObservation {
  /** Facial identity drift vs. the persona reference. */
  faceIdentityDrift?: number
  /** Clothing/appearance identity drift. */
  clothingDrift?: number
  /** Voiceprint drift vs. the persona voice reference. */
  voiceprintDrift?: number
  /** Prosody drift vs. the intended prosody. */
  prosodyDrift?: number
  /** Observed actions that are forbidden for this character. */
  forbiddenActions?: string[]
  /** Emotion–semantics conflict score (face/voice vs. text meaning). */
  emotionSemanticConflict?: number
  /** Lip-sync deviation from speech, milliseconds. */
  lipSyncDeviationMs?: number
  /** Scene continuity broken (background/props/lighting jump). */
  sceneContinuityBreak?: boolean
  /** Cultural / relationship boundary violations observed. */
  boundaryViolations?: string[]
}

/** Thresholds above which an observation counts as a failure. */
export interface ConsistencyThresholds {
  faceIdentityDrift: number
  clothingDrift: number
  voiceprintDrift: number
  prosodyDrift: number
  emotionSemanticConflict: number
  lipSyncDeviationMs: number
}

export const DEFAULT_CONSISTENCY_THRESHOLDS: ConsistencyThresholds = {
  faceIdentityDrift: 0.2,
  clothingDrift: 0.3,
  voiceprintDrift: 0.25,
  prosodyDrift: 0.4,
  emotionSemanticConflict: 0.5,
  lipSyncDeviationMs: 120,
}

/** Which consistency dimension failed. */
export type ConsistencyFailureKind
  = | 'face_identity_drift'
    | 'clothing_drift'
    | 'voiceprint_drift'
    | 'prosody_drift'
    | 'forbidden_action'
    | 'emotion_semantic_conflict'
    | 'lip_sync_deviation'
    | 'scene_continuity'
    | 'boundary_violation'

export interface ConsistencyFailure {
  kind: ConsistencyFailureKind
  detail: string
}

/**
 * §52.5 — degrade target. 'avatar' = fall back to a controllable Avatar
 * (parametric face/motion, identity guaranteed); 'voice' = pure voice only —
 * the strongest fallback, used when identity itself cannot be trusted on
 * screen. 'none' = no degradation needed.
 */
export type DegradeMode = 'none' | 'avatar' | 'voice'

export type ConsistencyVerdict
  = | { ok: true, degrade: 'none', failures: [] }
    | { ok: false, degrade: Exclude<DegradeMode, 'none'>, failures: ConsistencyFailure[] }

/**
 * §52.5 — evaluate a generated segment against identity-consistency
 * constraints. Never throws.
 *
 * Degrade policy (§52.5: "失败时降级为可控 Avatar 动作或纯语音"):
 *   - identity-level failures (face identity drift, forbidden actions,
 *     boundary violations, scene-continuity break) → degrade to pure 'voice':
 *     the visual channel can no longer be trusted with the persona's identity;
 *   - expression-level failures only (clothing drift, voiceprint/prosody
 *     drift, emotion–semantic conflict, lip-sync deviation) → degrade to
 *     controllable 'avatar'.
 */
export function identityConsistencyCheck(
  obs: ConsistencyObservation,
  thresholds: ConsistencyThresholds = DEFAULT_CONSISTENCY_THRESHOLDS,
): ConsistencyVerdict {
  const failures: ConsistencyFailure[] = []
  const identityLevel = new Set<ConsistencyFailureKind>([
    'face_identity_drift',
    'forbidden_action',
    'boundary_violation',
    'scene_continuity',
  ])

  if (typeof obs.faceIdentityDrift === 'number' && obs.faceIdentityDrift > thresholds.faceIdentityDrift)
    failures.push({ kind: 'face_identity_drift', detail: `face identity drift ${obs.faceIdentityDrift} > ${thresholds.faceIdentityDrift}` })
  if (typeof obs.clothingDrift === 'number' && obs.clothingDrift > thresholds.clothingDrift)
    failures.push({ kind: 'clothing_drift', detail: `clothing drift ${obs.clothingDrift} > ${thresholds.clothingDrift}` })
  if (typeof obs.voiceprintDrift === 'number' && obs.voiceprintDrift > thresholds.voiceprintDrift)
    failures.push({ kind: 'voiceprint_drift', detail: `voiceprint drift ${obs.voiceprintDrift} > ${thresholds.voiceprintDrift}` })
  if (typeof obs.prosodyDrift === 'number' && obs.prosodyDrift > thresholds.prosodyDrift)
    failures.push({ kind: 'prosody_drift', detail: `prosody drift ${obs.prosodyDrift} > ${thresholds.prosodyDrift}` })
  if (obs.forbiddenActions && obs.forbiddenActions.length > 0)
    failures.push({ kind: 'forbidden_action', detail: `role-forbidden actions observed: ${obs.forbiddenActions.join(', ')}` })
  if (typeof obs.emotionSemanticConflict === 'number' && obs.emotionSemanticConflict > thresholds.emotionSemanticConflict)
    failures.push({ kind: 'emotion_semantic_conflict', detail: `emotion-semantic conflict ${obs.emotionSemanticConflict} > ${thresholds.emotionSemanticConflict}` })
  if (typeof obs.lipSyncDeviationMs === 'number' && obs.lipSyncDeviationMs > thresholds.lipSyncDeviationMs)
    failures.push({ kind: 'lip_sync_deviation', detail: `lip-sync deviation ${obs.lipSyncDeviationMs}ms > ${thresholds.lipSyncDeviationMs}ms` })
  if (obs.sceneContinuityBreak === true)
    failures.push({ kind: 'scene_continuity', detail: 'scene continuity break detected' })
  if (obs.boundaryViolations && obs.boundaryViolations.length > 0)
    failures.push({ kind: 'boundary_violation', detail: `cultural/relationship boundary violations: ${obs.boundaryViolations.join(', ')}` })

  if (failures.length === 0)
    return { ok: true, degrade: 'none', failures: [] }

  const degrade: Exclude<DegradeMode, 'none'>
    = failures.some(f => identityLevel.has(f.kind)) ? 'voice' : 'avatar'
  return { ok: false, degrade, failures }
}
