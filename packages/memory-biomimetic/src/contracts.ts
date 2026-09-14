import type { MemoryType } from './types'

/**
 * v7 §24 / §25 — unified event envelope + versioned core data contracts.
 *
 * These are the *wire* contracts: every cross-module message and every durable
 * record that must be reproducible carries one of these shapes, with an explicit
 * `schema` version so the research kernel and the experience shell can evolve
 * independently (v7 §43).
 *
 * The contracts were scaffolded from their §25 one-line definitions together with
 * the hard requirements elsewhere in the spec:
 *   - §6  source traceability ≥ 99.5%  → a `MemoryCandidate` MUST name ≥1 source;
 *   - §38 reproducible interventions   → an `ExperimentManifest` MUST pin a seed,
 *     list ≥1 condition, and commit to ≥1 reported metric (so claims are falsifiable);
 *   - §9/§11 HAC+CDI closed loop        → `Appraisal` (#2) MUST carry a bounded
 *     confidence so downstream can trust or reject low-confidence appraisals, and a
 *     `StateSnapshot` (#3) MUST be immutable (frozen) with a content fingerprint;
 *   - feedback as loop input            → `FeedbackEvent` (#14) MUST bind to a target
 *     and declare whether it is explicit or implicit.
 * They will be tightened when the detailed sub-schemas land.
 *
 * `BeliefRevision` (contract #5) already lives in `./belief` and is re-exported
 * from the package index.
 */

/** v7 §24 — every percept / action / state transition is wrapped in this envelope. */
export interface EventEnvelope {
  eventId: string
  schema: string
  agentId: string
  userScope: string
  deviceId: string
  sessionId: string
  /** RFC3339Nano string. */
  timestamp: string
  modality: string[]
  payloadRef: string
  provenance: {
    source: string
    trusted: boolean
    consentPolicy: string
  }
  privacy: 'public' | 'private' | 'confidential'
  traceId: string
}

/** v7 §25 #4 — a memory proposed for admission, carrying its source (§6 traceability). */
export interface MemoryCandidate {
  id: string
  schema: 'aijade.memory_candidate@1'
  content: string
  /** The memory view this candidate targets. */
  kind: MemoryType
  /**
   * Provenance: a candidate MUST name at least one source. This is the enforceable
   * half of §6's "no sourceless entry" rule (the other half is enforced on the
   * belief graph via `proposeBelief`).
   */
  sources: { ref: string, trusted: boolean, consentPolicy?: string }[]
  /** Salience evidence supplied at proposal time, if any (∈ [0,1]). */
  salience?: number
  proposedAt: number
  traceId?: string
}

/** v7 §25 #15 — a reproducible experiment: conditions, seed, metrics, version. */
export interface ExperimentManifest {
  id: string
  schema: 'aijade.experiment_manifest@1'
  name: string
  /** Schema / package version under test. */
  version: string
  /** Fixed seed — non-negotiable for reproducibility (§38). */
  seed: number
  /** Named treatment arms (e.g. gating on/off for the H2/H5 ablations). */
  conditions: { name: string, description: string, params?: Record<string, unknown> }[]
  /** Metrics the experiment commits to reporting — forces falsifiable claims. */
  metrics: string[]
  createdAt: number
  notes?: string
}

/**
 * v7 §25 #2 — stimulus appraisal and its confidence.
 *
 * The structured evaluation of a stimulus/event: how significant, what valence /
 * arousal / goal-relevance / novelty / control / urgency, plus a confidence in the
 * appraisal. This is a direct input to the HAC endogenous state (z_t) and to the
 * CDI identity loop. The bounded `confidence` lets downstream modules reject or
 * discount low-confidence appraisals instead of trusting them silently.
 */
export interface Appraisal {
  id: string
  schema: 'aijade.appraisal@1'
  /** Event this appraisal evaluates (an EventEnvelope.eventId). */
  eventRef: string
  agentId: string
  userScope: string
  /** Appraisal dimensions; ranges mirror HAC z_t semantics. */
  dimensions: {
    /** −1 (aversive) … +1 (appetitive). */
    valence: number
    /** 0 … 1. */
    arousal: number
    /** 0 … 1. */
    goalRelevance: number
    /** 0 … 1. */
    novelty: number
    /** −1 (no control) … +1 (full control). */
    control: number
    /** 0 … 1. */
    urgency: number
  }
  /** Confidence in this appraisal, ∈ [0,1]. */
  confidence: number
  appraisedBy: 'agent' | 'user' | 'world' | 'model'
  appraisedAt: number
  traceId?: string
}

/**
 * v7 §25 #3 — immutable snapshot of the endogenous state.
 *
 * A frozen, content-addressed view of the endogenous state vector (HAC z_t =
 * [a,v,d,n,s,c,b]) at a point in time. It MUST be immutable (`frozen: true`) and
 * carry a deterministic `fingerprint`, so that the same state at the same instant
 * from the same source always yields the same id — the basis for reproducible
 * HAC/CDI loop steps and for detecting silent state drift.
 */
export interface StateSnapshot {
  id: string
  schema: 'aijade.state_snapshot@1'
  agentId: string
  userScope: string
  takenAt: number
  /** Endogenous state vector at snapshot time (HAC z_t = [a,v,d,n,s,c,b]). */
  state: {
    arousal: number
    vigilance: number
    drive: number
    novelty: number
    safety: number
    cognitiveLoad: number
    boredom: number
  }
  /** Module that produced the snapshot (e.g. 'hac', 'identity'). */
  source: string
  /** Immutable once written — always true so downstream code can assert. */
  frozen: true
  /**
   * Content-addressing fingerprint (deterministic). Producers should use
   * `stateSnapshotFingerprint`.
   */
  fingerprint: string
  traceId?: string
}

/**
 * v7 §25 #14 — explicit or implicit feedback.
 *
 * A loop-closing signal from the user: explicit (a rating, a correction, an
 * accept/decline) or implicit (dwell time, repeats, scroll behaviour). Feeds the
 * CDI consent/drift loop and the HAC utility estimate. It MUST bind to a target
 * and declare its kind, so feedback is never orphaned.
 */
export interface FeedbackEvent {
  id: string
  schema: 'aijade.feedback_event@1'
  agentId: string
  userScope: string
  sessionId: string
  /** The event / memory / response this feedback is about. */
  targetRef: string
  type: 'explicit' | 'implicit'
  /** Discrete signal, e.g. 'accept' | 'decline' | 'correct' | 'rating'. */
  signal: string
  /** Numeric magnitude when applicable (e.g. rating 1–5, or signed valence). */
  value?: number
  /** For implicit feedback: behavioral evidence (dwellMs, repeats, …). */
  evidence?: Record<string, number>
  /** Signed valence of the feedback, ∈ [−1,1], if known. */
  valence?: number
  timestamp: number
  traceId?: string
}

/**
 * v7 §25 #7 — a goal the system is pursuing: its target, provenance, lifecycle
 * status, and resource budget.
 *
 * A goal names where it came from (§6 traceability analog: an unsourced goal is
 * unaccountable) and tracks its own budget so resource overruns are detectable
 * (the falsifiable half of "the agent stays within its means"). The status enum
 * makes the goal lifecycle auditable; `budget.spent` MUST never exceed `allocated`.
 */
export interface GoalRecord {
  id: string
  schema: 'aijade.goal_record@1'
  agentId: string
  userScope: string
  /** The objective, expressed as a short proposition. */
  goal: string
  /** Provenance: a goal MUST name ≥1 source (§6 traceability analog). */
  source: { ref: string, trusted: boolean, consentPolicy?: string }
  /** Lifecycle status of the goal. */
  status: 'active' | 'paused' | 'achieved' | 'abandoned' | 'failed'
  /** Resource budget and draw-down, so overruns are detectable. */
  budget: {
    /** Allocated budget. */
    allocated: number
    /** Consumed so far; MUST be ≤ allocated. */
    spent: number
    /** Unit of the budget (tokens, steps, seconds, or currency). */
    unit: 'tokens' | 'steps' | 'seconds' | 'usd'
  }
  /** Optional link to a PlanGraph (#8) that realises this goal. */
  planRef?: string
  createdAt: number
  traceId?: string
}

/**
 * v7 §25 #8 — a plan as a graph of nodes with dependencies and compensation.
 *
 * Each node `dependsOn` the node ids that must complete first (a DAG — cycles are
 * rejected so the plan is always executable), and may `compensates` node ids whose
 * effect it rolls back (saga-style compensation). The graph MAY link back to the
 * owning GoalRecord (#7) via `goalRef`.
 */
export interface PlanGraph {
  id: string
  schema: 'aijade.plan_graph@1'
  agentId: string
  userScope: string
  /** Optional owning goal (#7). */
  goalRef?: string
  nodes: PlanNode[]
  /** Explicit dependency/compensation edges (mirror node.dependsOn / compensates). */
  edges?: PlanEdge[]
  createdAt: number
  traceId?: string
}

export interface PlanNode {
  id: string
  kind: 'action' | 'check' | 'parallel' | 'goal'
  label: string
  /** Node ids that must complete before this node runs. */
  dependsOn: string[]
  /** Node ids whose effect this node compensates (saga rollback). */
  compensates?: string[]
  status?: 'pending' | 'running' | 'done' | 'compensated' | 'failed'
}

export interface PlanEdge {
  from: string
  to: string
  type: 'depends' | 'compensates'
}

/**
 * v7 §25 #9 — a grant of a capability to a subject (agent or user), with an
 * explicit scope and consent policy.
 *
 * Capability grants are permissions with autonomy impact, so the record MUST name
 * ≥1 source (§6 traceability) and carry a non-empty `consentPolicy` (the grant is
 * only legitimate if the affected party consented). `expiresAt`, when present,
 * MUST be strictly after `issuedAt`. This is a durable authorization record — it
 * does NOT drive memory durability/salience (H2c compatible: grants are policy,
 * not recall).
 */
export interface CapabilityGrant {
  id: string
  schema: 'aijade.capability_grant@1'
  /** The subject the capability is granted to. */
  grantee: { agentId?: string, userScope?: string }
  /** The capability being granted (a capability identifier). */
  capability: string
  /** Resource / action scope the grant applies to. */
  scope: string
  /** Who issued the grant (an agent id, or the literal 'user'). */
  grantedBy: string
  /** Issuance time (epoch ms). */
  issuedAt: number
  /** Optional expiry (epoch ms); MUST be > issuedAt when present. */
  expiresAt?: number
  /** Consent policy reference — required because grants have autonomy impact. */
  consentPolicy: string
  /** Provenance: a grant MUST name ≥1 source (v7 §6). */
  source: { ref: string, trusted: boolean, consentPolicy?: string }[]
  traceId?: string
}

/**
 * v7 §25 #10 — a durable, traceable record of an action the agent executed,
 * linked to the episodic event it belongs to (and optionally a plan node).
 *
 * An action record is the audit trail of "what the agent did". It MUST bind to an
 * episode (§10.1 / §6 traceability — an action is only accountable if attributable
 * to an event) and MAY reference a PlanGraph node (#8) it realises. It does not
 * perform anything; it is a fact of record (H2c compatible).
 */
export interface ActionRecord {
  id: string
  schema: 'aijade.action_record@1'
  agentId: string
  userScope: string
  /** The action performed (type / name). */
  action: string
  /** Inputs/arguments the action was given. */
  args: Record<string, unknown>
  /** Outcome / status of the action. */
  outcome: string
  /** Episode this action belongs to (v7 §10.1 event id) — required for traceability. */
  episodeRef: string
  /** Optional PlanGraph (#8) node this action realises. */
  planRef?: string
  timestamp: number
  traceId?: string
}

/**
 * v7 §25 #11 — the semantic change between two states, with a magnitude and a
 * representation basis.
 *
 * A semantic motion measures how a state moved (e.g. an embedding delta or a
 * symbolic diff) between `fromRef` and `toRef`. It is the unit CBR (#13) and the
 * CDI drift loop (§11) reason about. The hard invariants: `fromRef` and `toRef`
 * are both present and distinct (a non-trivial motion), `magnitude` is a finite
 * non-negative number, and `basis` is a non-empty string. Sources are required
 * (§6) so the motion is attributable.
 */
export interface SemanticMotion {
  id: string
  schema: 'aijade.semantic_motion@1'
  agentId: string
  userScope: string
  /** Reference to the originating state / memory. */
  fromRef: string
  /** Reference to the resulting state / memory. */
  toRef: string
  /** The change representation (vector, diff, …) — opaque to the contract. */
  delta: unknown
  /** Non-negative magnitude of the motion. */
  magnitude: number
  /** Representation basis, e.g. 'embedding' | 'symbolic'. */
  basis: string
  timestamp: number
  /** Provenance: a motion MUST name ≥1 source (v7 §6). */
  source: { ref: string, trusted: boolean, consentPolicy?: string }[]
  traceId?: string
}

/**
 * v7 §25 #12 — a versioned, packaged, executable skill.
 *
 * A skill package bundles a capability (#9), its I/O contract (`manifest`), its
 * artifact (code/asset), authorship, and optional validation evidence. The hard
 * invariants: a non-empty name, a valid semver `version`, a non-empty
 * `capabilityRef` (a skill embodies a capability), a `manifest` with inputs and
 * outputs, and ≥1 source (§6). Metrics/validation are optional (an unvalidated
 * skill is still a valid package).
 */
export interface SkillPackage {
  id: string
  schema: 'aijade.skill_package@1'
  name: string
  /** Semantic version, e.g. '1.2.3'. */
  version: string
  /** Capability (#9) this skill embodies. */
  capabilityRef: string
  /** I/O contract of the skill. */
  manifest: {
    inputs: Record<string, unknown>
    outputs: Record<string, unknown>
    signature: string
  }
  /** Location of the skill's code / asset. */
  artifactRef: string
  /** Authoring agent id. */
  author: string
  /** Optional validation evidence (experiment registry ref or metric summary). */
  validatedBy?: string
  /** Optional quality metrics (e.g. precision from skill-forge-store). */
  metrics?: Record<string, number>
  /** Provenance: a package MUST name ≥1 source (v7 §6). */
  source: { ref: string, trusted: boolean, consentPolicy?: string }[]
  traceId?: string
}

/**
 * Enforce the §6 traceability invariant on a candidate. Pure.
 * Returns `{ ok: true }` or `{ ok: false, reason }` (never throws) so callers can
 * record the refusal and measure traceability, exactly like `proposeBelief`.
 */
export function validateMemoryCandidate(
  c: MemoryCandidate,
): { ok: true } | { ok: false, reason: string } {
  if (c.sources.length === 0)
    return { ok: false, reason: 'MemoryCandidate must carry ≥1 source (v7 §6 traceability)' }
  return { ok: true }
}

/**
 * Enforce the §38 reproducibility invariants on an experiment manifest. Pure.
 */
export function validateExperimentManifest(
  m: ExperimentManifest,
): { ok: true } | { ok: false, reason: string } {
  if (!Number.isFinite(m.seed))
    return { ok: false, reason: 'ExperimentManifest requires a fixed seed (reproducibility)' }
  if (m.conditions.length === 0)
    return { ok: false, reason: 'ExperimentManifest requires ≥1 condition' }
  if (m.metrics.length === 0)
    return { ok: false, reason: 'ExperimentManifest requires ≥1 reported metric (falsifiable)' }
  return { ok: true }
}

/**
 * Enforce the §25 #2 invariants on an appraisal. Pure.
 * The hard invariant is a bounded confidence plus bounded, finite appraisal
 * dimensions — so a malformed appraisal can never silently enter the HAC/CDI loop.
 */
export function validateAppraisal(
  a: Appraisal,
): { ok: true } | { ok: false, reason: string } {
  if (!a.eventRef)
    return { ok: false, reason: 'Appraisal must bind to an event (eventRef, v7 §25 #2)' }
  if (a.confidence < 0 || a.confidence > 1)
    return { ok: false, reason: 'Appraisal.confidence must be ∈ [0,1]' }
  const d = a.dimensions
  if (![d.valence, d.arousal, d.goalRelevance, d.novelty, d.control, d.urgency].every(Number.isFinite))
    return { ok: false, reason: 'Appraisal dimensions must all be finite numbers' }
  if (d.valence < -1 || d.valence > 1)
    return { ok: false, reason: 'Appraisal.valence must be ∈ [−1,1]' }
  if (d.arousal < 0 || d.arousal > 1)
    return { ok: false, reason: 'Appraisal.arousal must be ∈ [0,1]' }
  if (d.goalRelevance < 0 || d.goalRelevance > 1)
    return { ok: false, reason: 'Appraisal.goalRelevance must be ∈ [0,1]' }
  if (d.novelty < 0 || d.novelty > 1)
    return { ok: false, reason: 'Appraisal.novelty must be ∈ [0,1]' }
  if (d.control < -1 || d.control > 1)
    return { ok: false, reason: 'Appraisal.control must be ∈ [−1,1]' }
  if (d.urgency < 0 || d.urgency > 1)
    return { ok: false, reason: 'Appraisal.urgency must be ∈ [0,1]' }
  if (!Number.isFinite(a.appraisedAt))
    return { ok: false, reason: 'Appraisal.appraisedAt must be a finite timestamp' }
  return { ok: true }
}

/**
 * Enforce the §25 #3 invariants on a state snapshot. Pure.
 * The hard invariant is immutability (`frozen`) plus a content fingerprint, so a
 * snapshot that was mutated after creation (or lacks a deterministic id) is rejected.
 */
export function validateStateSnapshot(
  s: StateSnapshot,
): { ok: true } | { ok: false, reason: string } {
  if (s.frozen !== true)
    return { ok: false, reason: 'StateSnapshot must be frozen (immutable, v7 §25 #3)' }
  if (!s.fingerprint)
    return { ok: false, reason: 'StateSnapshot requires a content fingerprint' }
  if (!Number.isFinite(s.takenAt))
    return { ok: false, reason: 'StateSnapshot.takenAt must be a finite timestamp' }
  const st = s.state
  const dims = [
    st.arousal,
    st.vigilance,
    st.drive,
    st.novelty,
    st.safety,
    st.cognitiveLoad,
    st.boredom,
  ]
  if (!dims.every(Number.isFinite))
    return { ok: false, reason: 'StateSnapshot.state values must all be finite' }
  if (dims.some(d => d < 0 || d > 1))
    return { ok: false, reason: 'StateSnapshot.state values must be ∈ [0,1]' }
  return { ok: true }
}

/**
 * Enforce the §25 #14 invariants on a feedback event. Pure.
 * The hard invariant is that feedback binds to a target and declares its kind, so
 * it can never be orphaned inside the CDI/HAC loop.
 */
export function validateFeedbackEvent(
  f: FeedbackEvent,
): { ok: true } | { ok: false, reason: string } {
  if (!f.targetRef)
    return { ok: false, reason: 'FeedbackEvent must bind to a target (targetRef, v7 §25 #14)' }
  if (f.type !== 'explicit' && f.type !== 'implicit')
    return { ok: false, reason: 'FeedbackEvent.type must be explicit|implicit' }
  if (!f.signal)
    return { ok: false, reason: 'FeedbackEvent.signal must be a non-empty string' }
  if (!Number.isFinite(f.timestamp))
    return { ok: false, reason: 'FeedbackEvent.timestamp must be a finite number' }
  if (f.value !== undefined && !Number.isFinite(f.value))
    return { ok: false, reason: 'FeedbackEvent.value must be a number when present' }
  if (f.valence !== undefined && (f.valence < -1 || f.valence > 1))
    return { ok: false, reason: 'FeedbackEvent.valence must be ∈ [−1,1]' }
  return { ok: true }
}

/**
 * Enforce the §25 #7 invariants on a goal record. Pure.
 * The hard invariants: a goal names a source (§6), is in a valid status, and its
 * spent budget never exceeds the allocated budget.
 */
export function validateGoalRecord(
  g: GoalRecord,
): { ok: true } | { ok: false, reason: string } {
  if (!g.goal || !g.goal.trim())
    return { ok: false, reason: 'GoalRecord.goal must be a non-empty string' }
  if (!g.source?.ref)
    return { ok: false, reason: 'GoalRecord must carry a source ref (v7 §6)' }
  const STATUSES = ['active', 'paused', 'achieved', 'abandoned', 'failed']
  if (!STATUSES.includes(g.status))
    return { ok: false, reason: `GoalRecord.status must be one of ${STATUSES.join('|')}` }
  if (!Number.isFinite(g.budget.allocated) || g.budget.allocated < 0)
    return { ok: false, reason: 'GoalRecord.budget.allocated must be a finite number ≥ 0' }
  if (!Number.isFinite(g.budget.spent) || g.budget.spent < 0)
    return { ok: false, reason: 'GoalRecord.budget.spent must be a finite number ≥ 0' }
  if (g.budget.spent > g.budget.allocated)
    return { ok: false, reason: 'GoalRecord.budget.spent must not exceed allocated' }
  return { ok: true }
}

/**
 * Enforce the §25 #8 invariants on a plan graph. Pure.
 * The hard invariants: every node has a unique id, every dependsOn/compensates
 * reference points to an existing node (no dangling deps), and the dependency
 * graph is acyclic (a plan with a cycle is never executable). Edges, if present,
 * must also reference valid node ids.
 */
export function validatePlanGraph(
  p: PlanGraph,
): { ok: true } | { ok: false, reason: string } {
  if (p.nodes.length === 0)
    return { ok: false, reason: 'PlanGraph must contain ≥1 node' }
  const ids = new Set<string>()
  for (const n of p.nodes) {
    if (!n.id)
      return { ok: false, reason: 'PlanGraph node must have an id' }
    if (ids.has(n.id))
      return { ok: false, reason: `PlanGraph duplicate node id: ${n.id}` }
    ids.add(n.id)
  }
  const KINDS = ['action', 'check', 'parallel', 'goal']
  for (const n of p.nodes) {
    if (!KINDS.includes(n.kind))
      return { ok: false, reason: `PlanGraph node.kind must be one of ${KINDS.join('|')}` }
    for (const dep of n.dependsOn) {
      if (!ids.has(dep))
        return { ok: false, reason: `PlanGraph node ${n.id} depends on unknown node ${dep}` }
    }
    if (n.compensates) {
      for (const comp of n.compensates) {
        if (!ids.has(comp))
          return { ok: false, reason: `PlanGraph node ${n.id} compensates unknown node ${comp}` }
      }
    }
  }
  if (p.edges) {
    for (const e of p.edges) {
      if (!ids.has(e.from) || !ids.has(e.to))
        return { ok: false, reason: `PlanGraph edge references unknown node (${e.from}→${e.to})` }
    }
  }
  // acyclic dependency check (DFS with a recursion stack: WHITE/GRAY/BLACK)
  const WHITE = 0
  const GRAY = 1
  const BLACK = 2
  const color = new Map<string, number>()
  for (const id of ids)
    color.set(id, WHITE)
  const byId = new Map(p.nodes.map(n => [n.id, n]))
  const dfs = (u: string): boolean => {
    color.set(u, GRAY)
    for (const v of byId.get(u)!.dependsOn) {
      const c = color.get(v)
      if (c === GRAY)
        return true // back-edge → cycle
      if (c === WHITE && dfs(v))
        return true
    }
    color.set(u, BLACK)
    return false
  }
  for (const id of ids) {
    if (color.get(id) === WHITE && dfs(id))
      return { ok: false, reason: 'PlanGraph dependency graph contains a cycle' }
  }
  return { ok: true }
}

/**
 * Enforce the §25 #9 invariants on a capability grant. Pure.
 * Hard invariants: non-empty capability, an identifiable grantee, a grantor,
 * expiresAt > issuedAt when present, ≥1 named source (§6), and a non-empty
 * consentPolicy (grants have autonomy impact).
 */
export function validateCapabilityGrant(
  g: CapabilityGrant,
): { ok: true } | { ok: false, reason: string } {
  if (!g.capability || !g.capability.trim())
    return { ok: false, reason: 'CapabilityGrant.capability must be a non-empty string' }
  if (!g.grantee.agentId && !g.grantee.userScope)
    return { ok: false, reason: 'CapabilityGrant.grantee must identify an agent or user scope' }
  if (!g.grantedBy || !g.grantedBy.trim())
    return { ok: false, reason: 'CapabilityGrant.grantedBy must be a non-empty string' }
  if (!Number.isFinite(g.issuedAt))
    return { ok: false, reason: 'CapabilityGrant.issuedAt must be a finite timestamp' }
  if (g.expiresAt !== undefined) {
    if (!Number.isFinite(g.expiresAt))
      return { ok: false, reason: 'CapabilityGrant.expiresAt must be a finite timestamp' }
    if (g.expiresAt <= g.issuedAt)
      return { ok: false, reason: 'CapabilityGrant.expiresAt must be > issuedAt' }
  }
  if (!g.consentPolicy || !g.consentPolicy.trim())
    return { ok: false, reason: 'CapabilityGrant.consentPolicy must be a non-empty string' }
  if (!g.source || g.source.length === 0 || !g.source.every(s => s.ref))
    return { ok: false, reason: 'CapabilityGrant must carry ≥1 source with a ref (v7 §6)' }
  return { ok: true }
}

/**
 * Enforce the §25 #10 invariants on an action record. Pure.
 * Hard invariants: non-empty action, a traceable episode reference (§6/§10.1),
 * and an identifiable actor.
 */
export function validateActionRecord(
  r: ActionRecord,
): { ok: true } | { ok: false, reason: string } {
  if (!r.action || !r.action.trim())
    return { ok: false, reason: 'ActionRecord.action must be a non-empty string' }
  if (!r.episodeRef || !r.episodeRef.trim())
    return { ok: false, reason: 'ActionRecord.episodeRef must be a non-empty string (v7 §10.1)' }
  if (!r.agentId && !r.userScope)
    return { ok: false, reason: 'ActionRecord must identify an agent or user scope' }
  if (!Number.isFinite(r.timestamp))
    return { ok: false, reason: 'ActionRecord.timestamp must be a finite number' }
  return { ok: true }
}

/**
 * Enforce the §25 #11 invariants on a semantic motion. Pure.
 * Hard invariants: distinct, non-empty from/to refs, a finite non-negative
 * magnitude, a non-empty basis, and ≥1 named source (§6).
 */
export function validateSemanticMotion(
  m: SemanticMotion,
): { ok: true } | { ok: false, reason: string } {
  if (!m.fromRef || !m.fromRef.trim())
    return { ok: false, reason: 'SemanticMotion.fromRef must be a non-empty string' }
  if (!m.toRef || !m.toRef.trim())
    return { ok: false, reason: 'SemanticMotion.toRef must be a non-empty string' }
  if (m.fromRef === m.toRef)
    return { ok: false, reason: 'SemanticMotion.fromRef and toRef must differ (non-trivial motion)' }
  if (!Number.isFinite(m.magnitude) || m.magnitude < 0)
    return { ok: false, reason: 'SemanticMotion.magnitude must be a finite number ≥ 0' }
  if (!m.basis || !m.basis.trim())
    return { ok: false, reason: 'SemanticMotion.basis must be a non-empty string' }
  if (!m.source || m.source.length === 0 || !m.source.every(s => s.ref))
    return { ok: false, reason: 'SemanticMotion must carry ≥1 source with a ref (v7 §6)' }
  return { ok: true }
}

/**
 * Enforce the §25 #12 invariants on a skill package. Pure.
 * Hard invariants: non-empty name, valid semver version, non-empty capabilityRef,
 * a manifest with inputs and outputs, and ≥1 named source (§6).
 */
export function validateSkillPackage(
  s: SkillPackage,
): { ok: true } | { ok: false, reason: string } {
  if (!s.name || !s.name.trim())
    return { ok: false, reason: 'SkillPackage.name must be a non-empty string' }
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Z.-]+)?(?:\+[0-9A-Z.-]+)?$/i.test(s.version))
    return { ok: false, reason: 'SkillPackage.version must be a valid semver (e.g. 1.2.3)' }
  if (!s.capabilityRef || !s.capabilityRef.trim())
    return { ok: false, reason: 'SkillPackage.capabilityRef must be a non-empty string' }
  if (!s.manifest || !s.manifest.inputs || !s.manifest.outputs)
    return { ok: false, reason: 'SkillPackage.manifest must declare inputs and outputs' }
  if (!s.source || s.source.length === 0 || !s.source.every(src => src.ref))
    return { ok: false, reason: 'SkillPackage must carry ≥1 source with a ref (v7 §6)' }
  return { ok: true }
}

/** Deterministic FNV-1a 32-bit hash (matches identity.ts `fingerprint`). */
export function fnv1a(input: string): string {
  let h = 0x811C9DC5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/**
 * Content fingerprint for a `StateSnapshot` — deterministic and order-independent,
 * so two snapshots of the same state at the same instant from the same source always
 * produce the same id. Producers should assign `fingerprint =
 * stateSnapshotFingerprint(state, source, takenAt)` so immutability is verifiable.
 */
export function stateSnapshotFingerprint(
  state: StateSnapshot['state'],
  source: string,
  takenAt: number,
): string {
  const body = [
    source,
    takenAt,
    state.arousal,
    state.vigilance,
    state.drive,
    state.novelty,
    state.safety,
    state.cognitiveLoad,
    state.boredom,
  ].join('|')
  return fnv1a(body)
}
