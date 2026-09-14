/**
 * v8 §53.2 — the autonomous-growth data contracts (#16–#28).
 *
 * These extend the v7 §25 wire contracts (#1–#15) with the records the growth
 * loop (§46) needs: DIVE interest threads, AEL learning quests and evidence,
 * transfer/association, the life journal and selective sharing, and the VSE /
 * PEF self-evolution + persona-expression records. Every contract inherits the
 * §24 envelope concerns (source traceability §6, privacy, versioning, trace).
 *
 * Hard requirements encoded here:
 *   - §6  source traceability ≥ 99.5%  → any contract that asserts or synthesises
 *     knowledge MUST name ≥1 source (with a ref), mirroring v7.
 *   - §47/§48 interest & learning are bounded → `InterestThread.attentionBudget`
 *     and `LearningQuest.resourceBudget` track allocated vs spent, and a quest
 *     MUST declare stop conditions ("no endless browsing", §48.2).
 *   - §51 evolution must be recoverable → an `EvolutionProposal` MUST carry a
 *     rollback plan, not decrease safety, and name its baseline version.
 *   - §52 persona expression must be identity-safe → a `PerformanceIntent` MUST
 *     carry a bounded expression vector and reference a persona snapshot.
 *
 * Pure validators return `{ ok: true }` / `{ ok: false, reason }` and never throw,
 * matching v7, so refusals are recordable and measurable.
 */

/** Provenance shape shared by all v8 contracts (mirrors v7 `source` fields). */
export interface ContractSource {
  ref: string
  trusted: boolean
  consentPolicy?: string
}

// ---------------------------------------------------------------------------
// DIVE — §47 (interest formation)
// ---------------------------------------------------------------------------

/**
 * v8 §47.2 #16 — a developmental interest thread.
 *
 * An interest is NOT a topic list: it carries why it formed (origin events +
 * motivating questions), its intrinsic value, its relevance to identity and the
 * user, its knowledge gaps and live hypotheses, a progress measure, and an
 * attention budget. It MUST name ≥1 origin event (an interest with no history is
 * a random browse, §47.1) and MUST track attention spend ≤ budget (falsifiable
 * resource-bounding). Status makes the lifecycle auditable; "abandoning" an
 * interest is normal growth, so `abandonedReason` is recorded, not deleted.
 */
export interface InterestThread {
  id: string
  schema: 'aijade.interest_thread@1'
  agentId: string
  userScope: string
  /** Short subject label. */
  subject: string
  /** Events that seeded this interest (≥1, §47.1 history requirement). */
  originEventIds: string[]
  /** Open questions that keep this thread alive. */
  motivatingQuestions: string[]
  /** Current intrinsic value (∈ [0,1], see dive.ts `intrinsicValue`). */
  intrinsicValue: number
  /** Relevance to developmental identity / stable preferences, ∈ [0,1]. */
  identityRelevance: number
  /** Relevance to the user / shared goals, ∈ [0,1]. */
  userRelevance: number
  /** Remaining novelty frontier, ∈ [0,1] (0 = saturated). */
  noveltyFrontier: number
  /** Known gaps this thread wants to close. */
  knowledgeGaps: string[]
  /** Live hypotheses under test. */
  currentHypotheses: string[]
  /** Progress toward satisfaction, ∈ [0,1]. */
  progress: number
  /** Attention budget and draw-down (allocated ≥ spent). */
  attentionBudget: { allocated: number, spent: number, unit: 'minutes' | 'queries' | 'tokens' }
  status: 'latent' | 'active' | 'incubating' | 'satisfied' | 'abandoned'
  /** Why the thread was abandoned, when status === 'abandoned'. */
  abandonedReason?: string
  lastReflectedAt: number
  traceId?: string
}

// ---------------------------------------------------------------------------
// AEL — §48 (autonomous epistemic learning)
// ---------------------------------------------------------------------------

/**
 * v8 §48.2 #17 — a bounded learning quest.
 *
 * Every learning task MUST be bounded before it starts: it declares stop
 * conditions (e.g. "marginal information gain below threshold", "time budget
 * reached") so browsing always has an end (§48.2 "禁止无终点浏览"). It pins an
 * interest thread, a research question, prior beliefs, an expected information
 * gain, a source plan, a resource budget (allocated ≥ spent), a privacy class,
 * success criteria and deliverables, and references its ExperimentManifest (#15).
 */
export interface LearningQuest {
  id: string
  schema: 'aijade.learning_quest@1'
  agentId: string
  userScope: string
  /** Owning interest thread (#16). */
  interestThreadRef: string
  /** The research question being investigated. */
  researchQuestion: string
  /** Operational definition: how the question will be answered measurably. */
  operationalDefinition: string
  /** Prior beliefs this quest starts from (proposition refs). */
  priorBeliefs: string[]
  /** Expected information gain, ∈ [0,1] (justifies the budget). */
  expectedInformationGain: number
  /** Planned source strategy (see ael.ts `planSources`). */
  sourcePlan: { questionType: string, sourceTypes: string[], maxSources: number }
  /** Resource budget and draw-down (allocated ≥ spent). */
  resourceBudget: { allocated: number, spent: number, unit: 'queries' | 'minutes' | 'usd' | 'tokens' }
  /** Privacy class governing acquisition (§24 privacy). */
  privacyClass: 'public' | 'private' | 'confidential'
  /** Stop conditions — MUST be non-empty (no endless browsing, §48.2). */
  stopConditions: string[]
  /** Success criteria for the quest to be considered answered. */
  successCriteria: string[]
  /** Artefacts the quest commits to producing (§48.6). */
  deliverables: string[]
  /** Experiment / reproducibility manifest (#15). */
  experimentManifestRef: string
  status: 'active' | 'paused' | 'needs_consent' | 'contradicted' | 'failed' | 'abandoned' | 'satisfied'
  createdAt: number
  traceId?: string
}

/**
 * v8 §48.3/§48.5 #18 — a source with its provenance lineage and quality.
 *
 * A source record keeps its upstream lineage (`upstreamRefs`) so the system can
 * detect when multiple citations actually share one origin (§48.4: reposts of
 * the same source must NOT masquerade as multi-source validation), plus the
 * quality dimensions that feed `evidenceConfidence` (Reliability, Independence,
 * Directness, Recency, Reproducibility).
 */
export interface SourceRecord {
  id: string
  schema: 'aijade.source_record@1'
  /** Locator (URL, DOI, local path, tool result ref). */
  locator: string
  /** Coarse source type (official_doc | paper | news | code | social | tool | …). */
  sourceType: string
  /** Quality dimensions, each ∈ [0,1]; feed evidence confidence (§48.5). */
  quality: {
    reliability: number
    independence: number
    directness: number
    recency: number
    reproducibility: number
  }
  /** Upstream sources this one reposts / derives from (shared-origin detection). */
  upstreamRefs: string[]
  /** Content-address hash so reposts of identical content can be deduped. */
  contentHash: string
  /** License tag for reuse policy. */
  license?: string
  fetchedAt: number
  traceId?: string
}

/**
 * v8 §48.6 #19 — a claim map: propositions with support / counter-evidence.
 *
 * Each claim MUST name ≥1 evidence source (§6) and separates observed facts from
 * inferences and tentative hypotheses (§48.5 output discipline). A claim may be
 * contested without being deleted — counter-evidence is retained, mirroring DGM.
 */
export interface ClaimMap {
  id: string
  schema: 'aijade.claim_map@1'
  agentId: string
  userScope: string
  /** The quest (#17) this map was produced from. */
  questRef: string
  claims: {
    proposition: string
    /** Observed | source-statement | system-inference | tentative-hypothesis | value-judgment | unknown. */
    epistemicStatus: 'observed' | 'source_statement' | 'inference' | 'hypothesis' | 'value_judgment' | 'unknown'
    supportSourceRefs: string[]
    counterSourceRefs: string[]
    /** ∈ [0,1]. */
    confidence: number
  }[]
  createdAt: number
  traceId?: string
}

/**
 * v8 §48.6 #20 — a knowledge artefact produced by synthesis.
 *
 * One of the §48.6 product kinds. It MUST bind to the quest that produced it and
 * name ≥1 source (§6). A summary is only a view — the evidence graph is the
 * substrate — so `evidenceGraphRef` links back to the DGM episode/belief refs.
 */
export interface KnowledgeArtifact {
  id: string
  schema: 'aijade.knowledge_artifact@1'
  agentId: string
  userScope: string
  kind: 'claim_map' | 'concept_map' | 'causal_model' | 'procedure' | 'comparison_matrix' | 'open_question_set' | 'learning_note' | 'shareable_story'
  /** The quest (#17) this artefact was produced from. */
  questRef: string
  /** Opaque artefact payload (structure depends on `kind`). */
  payload: unknown
  /** Backing evidence (DGM episode/belief refs) so the summary is not the source. */
  evidenceGraphRef: string
  /** Provenance: MUST name ≥1 source (v7 §6). */
  sources: ContractSource[]
  createdAt: number
  traceId?: string
}

/**
 * v8 §49.2 #21 — an association with its "why" path.
 *
 * Every association MUST keep the path that produced it (`path`): pathless free
 * association may NOT be submitted as fact (§49.2 "无路径的自由联想不得提交为事实").
 * The score balances relevance + novelty + utility against spuriousness + cost.
 */
export interface AssociationPath {
  id: string
  schema: 'aijade.association_path@1'
  agentId: string
  userScope: string
  fromConcept: string
  toConcept: string
  /** Association family (§49.2 A_semantic ∪ A_causal ∪ … ∪ A_embodied). */
  kind: 'semantic' | 'causal' | 'temporal' | 'structural' | 'autobiographical' | 'embodied'
  /** Ordered reasoning steps that produced this association (≥1, the "why" path). */
  path: string[]
  /** Final association score (Rel + Novel + Utility − Spurious − Cost). */
  score: number
  /** Backing evidence event refs. */
  evidenceRefs: string[]
  createdAt: number
  traceId?: string
}

/**
 * v8 §49.3 #22 — a knowledge/skill transfer record.
 *
 * Records source → target, the invariants preserved, the constraints that broke,
 * predicted vs measured outcome, and any negative-transfer signal. Tiers T2+ must
 * be validated (`validated: true`); a failed transfer is kept as a counter-example
 * (`negativeTransferSignal`), not deleted (§49.3).
 */
export interface TransferRecord {
  id: string
  schema: 'aijade.transfer_record@1'
  agentId: string
  userScope: string
  sourceDomain: string
  targetDomain: string
  /** Invariants held across the transfer. */
  invariantsPreserved: string[]
  /** Conditions under which the transfer broke. */
  brokenConditions: string[]
  /** Predicted outcome before application. */
  predictedOutcome: string
  /** Measured outcome after application. */
  measuredOutcome: string
  /** Negative-transfer signal (∈ [0,1]; 0 = none). */
  negativeTransferSignal: number
  /** Transfer tier (T0 expression … T4 meta-learning). */
  tier: 'T0' | 'T1' | 'T2' | 'T3' | 'T4'
  /** T2+ must have been validated (§49.3). */
  validated: boolean
  createdAt: number
  traceId?: string
}

// ---------------------------------------------------------------------------
// Life journal & selective sharing — §50
// ---------------------------------------------------------------------------

/**
 * v8 §50.3 #23 — a privacy-filtered autobiographical journal entry.
 *
 * A journal is NOT a full monitoring log; it is a privacy-filtered
 * autobiographical view. `sharePolicy` governs what may leave the device, and
 * user-private information MUST NOT be relayed to other channels merely to seem
 * "natural" (§50.3). Every listed item references evidence (§6).
 */
export interface LifeJournalEntry {
  id: string
  schema: 'aijade.life_journal_entry@1'
  agentId: string
  userScope: string
  /** ISO date (YYYY-MM-DD). */
  date: string
  experiencedEvents: string[]
  activeInterests: string[]
  learnedClaims: string[]
  changedBeliefs: string[]
  practicedSkills: string[]
  unresolvedQuestions: string[]
  identityReflections: string[]
  /** What may be shared off-device: private | diary_only | shareable. */
  sharePolicy: 'private' | 'diary_only' | 'shareable'
  /** Evidence refs backing the entry (§6). */
  evidenceRefs: string[]
  createdAt: number
  traceId?: string
}

/**
 * v8 §50.1 #24 — a candidate share, with its utility and channel.
 *
 * A share is NOT a broadcast: it carries the computed utility components and one
 * of the four channels (diary | next_chat | light_hint | full_share). Only when
 * utility exceeds the user's personalised threshold and quiet-hours policy allows
 * may it be actively sent (§50.1). The decision is auditable (`decidedAt`).
 */
export interface ShareCandidate {
  id: string
  schema: 'aijade.share_candidate@1'
  agentId: string
  userScope: string
  /** Content reference (a LifeJournalEntry / KnowledgeArtifact / episode ref). */
  contentRef: string
  /** Utility components feeding V_share (§50.1), each ∈ [0,1] (costs positive). */
  utility: {
    relevance: number
    novelty: number
    relationalValue: number
    timeliness: number
    uncertainty: number
    interruption: number
    privacyRisk: number
    repetition: number
  }
  /** Computed V_share score. */
  score: number
  /** Chosen delivery channel (§50.1 four channels). */
  channel: 'diary' | 'next_chat' | 'light_hint' | 'full_share'
  decidedAt: number
  traceId?: string
}

// ---------------------------------------------------------------------------
// VSE — §51 (verified self-evolution)
// ---------------------------------------------------------------------------

/**
 * v8 §51.5 #25 — an evolution proposal.
 *
 * The immutable evidence pack for a candidate change. Hard invariants: it names
 * a baseline version, a change spec, a rollback plan (§51.3 rollback is
 * non-negotiable), ≥1 test, and a signature. E4/E5 objects cannot be proposed for
 * autonomous modification at all (§51.1) — see vse.ts `assertEvolvable`.
 */
export interface EvolutionProposal {
  id: string
  schema: 'aijade.evolution_proposal@1'
  agentId: string
  /** Trigger evidence (failure patterns, cost overruns, …). */
  triggerEvidence: string[]
  /** Components the change touches. */
  affectedComponents: string[]
  /** Evolution grade (E0–E5, see vse.ts). */
  grade: 'E0' | 'E1' | 'E2' | 'E3' | 'E4' | 'E5'
  /** Version the change is based on. */
  baselineVersion: string
  /** Human/machine-readable change specification. */
  changeSpec: string
  /** Diff / config / skill reference. */
  sourceDiff: string
  /** What generated this candidate (never has release rights, §51.3). */
  generatedBy: string
  /** Dependency changes introduced. */
  dependencyDiff?: string
  /** Data / state migration plan. */
  migrationPlan?: string
  /** Tests run against the candidate (≥1). */
  tests: { kind: string, passed: boolean, evidenceRef?: string }[]
  /** Benchmark comparison vs baseline. */
  benchmarkResults?: Record<string, number>
  /** Safety evaluation results. */
  safetyResults?: Record<string, number | boolean>
  /** Behavioural diff summary. */
  behaviorDiff?: string
  /** Identity diff summary (drift). */
  identityDiff?: string
  /** Rollback plan — REQUIRED (recoverability, §51.3). */
  rollbackPlan: string
  /** Approval policy that governs promotion. */
  approvalPolicy: string
  /** Detached signature over the proposal body. */
  signature: string
  createdAt: number
  traceId?: string
}

/**
 * v8 §51.3 #26 — the evaluation evidence pack for a candidate version.
 *
 * Aggregates the per-stage evaluation results the release controller needs before
 * signing: static analysis, dependency/license scan, unit/contract/property tests,
 * security sandbox, historical replay, adversarial evaluation, benchmark
 * comparison, behaviour and identity diffs. A pack with no passing core test gate
 * cannot be promoted.
 */
export interface EvaluationEvidencePack {
  id: string
  schema: 'aijade.evaluation_evidence_pack@1'
  /** The proposal (#25) under evaluation. */
  proposalRef: string
  staticAnalysis?: { passed: boolean, findings?: number }
  dependencyLicenseScan?: { passed: boolean, violations?: string[] }
  /** Core gate: unit/contract/property tests. MUST pass to promote. */
  unitContractPropertyTests: { passed: boolean, total: number, failed: number }
  securitySandbox?: { passed: boolean, escapes?: number }
  historicalReplay?: { passed: boolean, regressions?: number }
  adversarialEval?: { passed: boolean, findings?: number }
  benchmarkComparison?: { improved: boolean, delta?: Record<string, number> }
  behaviorDiff?: string
  identityDiff?: string
  createdAt: number
  traceId?: string
}

/**
 * v8 §51 #27 — a signed release.
 *
 * The release controller's promotion record: which proposal + evidence pack, who
 * approved, the signature, canary ratio, and whether rollback is available.
 * Rollback MUST be available (§51.3 keep-or-rollback), and canary ratio ∈ [0,1].
 */
export interface SignedRelease {
  id: string
  schema: 'aijade.signed_release@1'
  version: string
  /** Proposal (#25) being promoted. */
  proposalRef: string
  /** Evidence pack (#26) backing the promotion. */
  evidencePackRef: string
  /** Approver (agent id or the literal 'user'). */
  approvedBy: string
  signedAt: number
  /** Detached signature. */
  signature: string
  /** Canary rollout fraction, ∈ [0,1]. */
  canaryRatio: number
  /** Whether an automatic rollback path is available (must be true). */
  rollbackAvailable: boolean
  traceId?: string
}

// ---------------------------------------------------------------------------
// PEF — §52 (persona-expression field)
// ---------------------------------------------------------------------------

/**
 * v8 §52.3 #28 — an incremental, time-marked persona-expression intent.
 *
 * The performance system does NOT wait for a complete long answer before
 * generating motion (§52.4); each intent is time-marked and carries the
 * continuous expression vector plus backend-agnostic output channels. The
 * expression vector components are all ∈ [0,1] except `valence` ∈ [−1,1]. It MUST
 * reference a persona snapshot so identity continuity is auditable (§52.5).
 */
export interface PerformanceIntent {
  id: string
  schema: 'aijade.performance_intent@1'
  agentId: string
  userScope: string
  /** Persona / identity snapshot this intent is expressed from. */
  personaSnapshotRef: string
  /** Time marker (epoch ms) within the incremental performance stream. */
  timeMarked: number
  /** Continuous expression vector (§52.3 e_t). */
  expression: {
    /** −1 … +1. */
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
  /** Output channels (backend-agnostic). */
  textStyle?: string
  voiceProsody?: { rate?: number, pitch?: number, energy?: number }
  face?: string
  gaze?: string
  gesture?: string
  posture?: string
  turnTaking?: 'backchannel' | 'hold' | 'yield' | 'interrupt_response'
  cameraBehavior?: string
  /** Scene context tag for consistency checking. */
  sceneContext?: string
  /** Intended duration of this intent (ms). */
  duration: number
  traceId?: string
}

// ===========================================================================
// Validators — pure, never throw, mirror v7 style.
// ===========================================================================

/** Every v8 numeric ∈ [0,1] helper. */
function in01(n: number): boolean {
  return Number.isFinite(n) && n >= 0 && n <= 1
}

/** §6 traceability: ≥1 source each with a non-empty ref. */
function hasSources(sources: ContractSource[] | undefined): boolean {
  return Array.isArray(sources) && sources.length > 0 && sources.every(s => s.ref && s.ref.length > 0)
}

/** Enforce §47 invariants on an interest thread. Pure. */
export function validateInterestThread(t: InterestThread): { ok: true } | { ok: false, reason: string } {
  if (!t.subject || !t.subject.trim())
    return { ok: false, reason: 'InterestThread.subject must be a non-empty string' }
  if (!t.originEventIds || t.originEventIds.length === 0)
    return { ok: false, reason: 'InterestThread must have ≥1 origin event (v8 §47.1 history)' }
  for (const v of [t.intrinsicValue, t.identityRelevance, t.userRelevance, t.noveltyFrontier, t.progress]) {
    if (!in01(v))
      return { ok: false, reason: 'InterestThread value fields must be ∈ [0,1]' }
  }
  if (!Number.isFinite(t.attentionBudget.allocated) || t.attentionBudget.allocated < 0)
    return { ok: false, reason: 'InterestThread.attentionBudget.allocated must be a finite number ≥ 0' }
  if (!Number.isFinite(t.attentionBudget.spent) || t.attentionBudget.spent < 0)
    return { ok: false, reason: 'InterestThread.attentionBudget.spent must be a finite number ≥ 0' }
  if (t.attentionBudget.spent > t.attentionBudget.allocated)
    return { ok: false, reason: 'InterestThread.attentionBudget.spent must not exceed allocated' }
  const STATUSES = ['latent', 'active', 'incubating', 'satisfied', 'abandoned']
  if (!STATUSES.includes(t.status))
    return { ok: false, reason: `InterestThread.status must be one of ${STATUSES.join('|')}` }
  if (t.status === 'abandoned' && !t.abandonedReason)
    return { ok: false, reason: 'InterestThread abandoned threads must record abandonedReason (v8 §47.2)' }
  if (!Number.isFinite(t.lastReflectedAt))
    return { ok: false, reason: 'InterestThread.lastReflectedAt must be a finite timestamp' }
  return { ok: true }
}

/** Enforce §48 invariants on a learning quest. Pure. */
export function validateLearningQuest(q: LearningQuest): { ok: true } | { ok: false, reason: string } {
  if (!q.interestThreadRef || !q.interestThreadRef.trim())
    return { ok: false, reason: 'LearningQuest must bind to an interest thread (interestThreadRef)' }
  if (!q.researchQuestion || !q.researchQuestion.trim())
    return { ok: false, reason: 'LearningQuest.researchQuestion must be a non-empty string' }
  if (!q.operationalDefinition || !q.operationalDefinition.trim())
    return { ok: false, reason: 'LearningQuest.operationalDefinition must be a non-empty string' }
  if (!in01(q.expectedInformationGain))
    return { ok: false, reason: 'LearningQuest.expectedInformationGain must be ∈ [0,1]' }
  if (!q.stopConditions || q.stopConditions.length === 0)
    return { ok: false, reason: 'LearningQuest must declare ≥1 stop condition (v8 §48.2 no endless browsing)' }
  if (!Number.isFinite(q.resourceBudget.allocated) || q.resourceBudget.allocated < 0)
    return { ok: false, reason: 'LearningQuest.resourceBudget.allocated must be a finite number ≥ 0' }
  if (!Number.isFinite(q.resourceBudget.spent) || q.resourceBudget.spent < 0)
    return { ok: false, reason: 'LearningQuest.resourceBudget.spent must be a finite number ≥ 0' }
  if (q.resourceBudget.spent > q.resourceBudget.allocated)
    return { ok: false, reason: 'LearningQuest.resourceBudget.spent must not exceed allocated' }
  if (!q.experimentManifestRef || !q.experimentManifestRef.trim())
    return { ok: false, reason: 'LearningQuest must reference an ExperimentManifest (experimentManifestRef)' }
  return { ok: true }
}

/** Enforce §48.5 invariants on a source record. Pure. */
export function validateSourceRecord(s: SourceRecord): { ok: true } | { ok: false, reason: string } {
  if (!s.locator || !s.locator.trim())
    return { ok: false, reason: 'SourceRecord.locator must be a non-empty string' }
  if (!s.sourceType || !s.sourceType.trim())
    return { ok: false, reason: 'SourceRecord.sourceType must be a non-empty string' }
  const q = s.quality
  if (![q.reliability, q.independence, q.directness, q.recency, q.reproducibility].every(in01))
    return { ok: false, reason: 'SourceRecord.quality dimensions must all be ∈ [0,1]' }
  if (!s.contentHash || !s.contentHash.trim())
    return { ok: false, reason: 'SourceRecord.contentHash must be a non-empty string (dedup reposts)' }
  if (!Number.isFinite(s.fetchedAt))
    return { ok: false, reason: 'SourceRecord.fetchedAt must be a finite timestamp' }
  return { ok: true }
}

/** Enforce §48.6 invariants on a claim map. Pure. */
export function validateClaimMap(m: ClaimMap): { ok: true } | { ok: false, reason: string } {
  if (!m.questRef || !m.questRef.trim())
    return { ok: false, reason: 'ClaimMap must bind to a quest (questRef)' }
  const STATUSES = ['observed', 'source_statement', 'inference', 'hypothesis', 'value_judgment', 'unknown']
  for (const c of m.claims) {
    if (!c.proposition || !c.proposition.trim())
      return { ok: false, reason: 'ClaimMap claim must have a non-empty proposition' }
    if (!STATUSES.includes(c.epistemicStatus))
      return { ok: false, reason: `ClaimMap claim.epistemicStatus must be one of ${STATUSES.join('|')}` }
    if (c.supportSourceRefs.length === 0)
      return { ok: false, reason: 'ClaimMap claim must have ≥1 support source (v7 §6)' }
    if (!in01(c.confidence))
      return { ok: false, reason: 'ClaimMap claim.confidence must be ∈ [0,1]' }
  }
  return { ok: true }
}

/** Enforce §48.6 invariants on a knowledge artefact. Pure. */
export function validateKnowledgeArtifact(a: KnowledgeArtifact): { ok: true } | { ok: false, reason: string } {
  const KINDS = ['claim_map', 'concept_map', 'causal_model', 'procedure', 'comparison_matrix', 'open_question_set', 'learning_note', 'shareable_story']
  if (!KINDS.includes(a.kind))
    return { ok: false, reason: `KnowledgeArtifact.kind must be one of ${KINDS.join('|')}` }
  if (!a.questRef || !a.questRef.trim())
    return { ok: false, reason: 'KnowledgeArtifact must bind to a quest (questRef)' }
  if (!a.evidenceGraphRef || !a.evidenceGraphRef.trim())
    return { ok: false, reason: 'KnowledgeArtifact must reference the evidence graph (summary ≠ source)' }
  if (!hasSources(a.sources))
    return { ok: false, reason: 'KnowledgeArtifact must carry ≥1 source (v7 §6)' }
  return { ok: true }
}

/** Enforce §49.2 invariants on an association path. Pure. */
export function validateAssociationPath(p: AssociationPath): { ok: true } | { ok: false, reason: string } {
  const KINDS = ['semantic', 'causal', 'temporal', 'structural', 'autobiographical', 'embodied']
  if (!KINDS.includes(p.kind))
    return { ok: false, reason: `AssociationPath.kind must be one of ${KINDS.join('|')}` }
  if (!p.fromConcept || !p.fromConcept.trim())
    return { ok: false, reason: 'AssociationPath.fromConcept must be a non-empty string' }
  if (!p.toConcept || !p.toConcept.trim())
    return { ok: false, reason: 'AssociationPath.toConcept must be a non-empty string' }
  if (!p.path || p.path.length === 0)
    return { ok: false, reason: 'AssociationPath must keep ≥1 reasoning step (v8 §49.2 no pathless association)' }
  if (!Number.isFinite(p.score))
    return { ok: false, reason: 'AssociationPath.score must be a finite number' }
  return { ok: true }
}

/** Enforce §49.3 invariants on a transfer record. Pure. */
export function validateTransferRecord(r: TransferRecord): { ok: true } | { ok: false, reason: string } {
  const TIERS = ['T0', 'T1', 'T2', 'T3', 'T4']
  if (!TIERS.includes(r.tier))
    return { ok: false, reason: `TransferRecord.tier must be one of ${TIERS.join('|')}` }
  if (!r.sourceDomain || !r.sourceDomain.trim())
    return { ok: false, reason: 'TransferRecord.sourceDomain must be a non-empty string' }
  if (!r.targetDomain || !r.targetDomain.trim())
    return { ok: false, reason: 'TransferRecord.targetDomain must be a non-empty string' }
  if (!in01(r.negativeTransferSignal))
    return { ok: false, reason: 'TransferRecord.negativeTransferSignal must be ∈ [0,1]' }
  // T2+ structural/cross-domain/meta transfers must be validated (v8 §49.3).
  if ((r.tier === 'T2' || r.tier === 'T3' || r.tier === 'T4') && !r.validated)
    return { ok: false, reason: 'TransferRecord tier T2+ must be validated (v8 §49.3)' }
  return { ok: true }
}

/** Enforce §50.3 invariants on a life journal entry. Pure. */
export function validateLifeJournalEntry(e: LifeJournalEntry): { ok: true } | { ok: false, reason: string } {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(e.date))
    return { ok: false, reason: 'LifeJournalEntry.date must be ISO YYYY-MM-DD' }
  const POLICIES = ['private', 'diary_only', 'shareable']
  if (!POLICIES.includes(e.sharePolicy))
    return { ok: false, reason: `LifeJournalEntry.sharePolicy must be one of ${POLICIES.join('|')}` }
  if (!Number.isFinite(e.createdAt))
    return { ok: false, reason: 'LifeJournalEntry.createdAt must be a finite timestamp' }
  return { ok: true }
}

/** Enforce §50.1 invariants on a share candidate. Pure. */
export function validateShareCandidate(c: ShareCandidate): { ok: true } | { ok: false, reason: string } {
  if (!c.contentRef || !c.contentRef.trim())
    return { ok: false, reason: 'ShareCandidate.contentRef must be a non-empty string' }
  const u = c.utility
  if (![u.relevance, u.novelty, u.relationalValue, u.timeliness, u.uncertainty, u.interruption, u.privacyRisk, u.repetition].every(in01))
    return { ok: false, reason: 'ShareCandidate.utility components must all be ∈ [0,1]' }
  if (!Number.isFinite(c.score))
    return { ok: false, reason: 'ShareCandidate.score must be a finite number' }
  const CHANNELS = ['diary', 'next_chat', 'light_hint', 'full_share']
  if (!CHANNELS.includes(c.channel))
    return { ok: false, reason: `ShareCandidate.channel must be one of ${CHANNELS.join('|')}` }
  if (!Number.isFinite(c.decidedAt))
    return { ok: false, reason: 'ShareCandidate.decidedAt must be a finite timestamp' }
  return { ok: true }
}

/** Enforce §51.5 invariants on an evolution proposal. Pure. */
export function validateEvolutionProposal(p: EvolutionProposal): { ok: true } | { ok: false, reason: string } {
  const GRADES = ['E0', 'E1', 'E2', 'E3', 'E4', 'E5']
  if (!GRADES.includes(p.grade))
    return { ok: false, reason: `EvolutionProposal.grade must be one of ${GRADES.join('|')}` }
  if (!p.baselineVersion || !p.baselineVersion.trim())
    return { ok: false, reason: 'EvolutionProposal.baselineVersion must be a non-empty string' }
  if (!p.changeSpec || !p.changeSpec.trim())
    return { ok: false, reason: 'EvolutionProposal.changeSpec must be a non-empty string' }
  if (!p.sourceDiff || !p.sourceDiff.trim())
    return { ok: false, reason: 'EvolutionProposal.sourceDiff must be a non-empty string' }
  if (!p.rollbackPlan || !p.rollbackPlan.trim())
    return { ok: false, reason: 'EvolutionProposal must carry a rollback plan (v8 §51.3 recoverability)' }
  if (!p.tests || p.tests.length === 0)
    return { ok: false, reason: 'EvolutionProposal must include ≥1 test (v8 §51.3)' }
  if (!p.signature || !p.signature.trim())
    return { ok: false, reason: 'EvolutionProposal.signature must be a non-empty string' }
  if (!p.generatedBy || !p.generatedBy.trim())
    return { ok: false, reason: 'EvolutionProposal.generatedBy must be a non-empty string' }
  return { ok: true }
}

/** Enforce §51.3 invariants on an evaluation evidence pack. Pure. */
export function validateEvaluationEvidencePack(p: EvaluationEvidencePack): { ok: true } | { ok: false, reason: string } {
  if (!p.proposalRef || !p.proposalRef.trim())
    return { ok: false, reason: 'EvaluationEvidencePack must bind to a proposal (proposalRef)' }
  if (!Number.isFinite(p.unitContractPropertyTests.total) || p.unitContractPropertyTests.total < 0)
    return { ok: false, reason: 'EvaluationEvidencePack.unitContractPropertyTests.total must be ≥ 0' }
  if (!Number.isFinite(p.unitContractPropertyTests.failed) || p.unitContractPropertyTests.failed < 0)
    return { ok: false, reason: 'EvaluationEvidencePack.unitContractPropertyTests.failed must be ≥ 0' }
  if (p.unitContractPropertyTests.failed > p.unitContractPropertyTests.total)
    return { ok: false, reason: 'EvaluationEvidencePack failed tests must not exceed total' }
  if (p.unitContractPropertyTests.failed > 0 && p.unitContractPropertyTests.passed)
    return { ok: false, reason: 'EvaluationEvidencePack cannot pass core gate with failing tests' }
  return { ok: true }
}

/** Enforce §51 invariants on a signed release. Pure. */
export function validateSignedRelease(r: SignedRelease): { ok: true } | { ok: false, reason: string } {
  if (!r.version || !r.version.trim())
    return { ok: false, reason: 'SignedRelease.version must be a non-empty string' }
  if (!r.proposalRef || !r.proposalRef.trim())
    return { ok: false, reason: 'SignedRelease must bind to a proposal (proposalRef)' }
  if (!r.evidencePackRef || !r.evidencePackRef.trim())
    return { ok: false, reason: 'SignedRelease must bind to an evidence pack (evidencePackRef)' }
  if (!r.approvedBy || !r.approvedBy.trim())
    return { ok: false, reason: 'SignedRelease.approvedBy must be a non-empty string' }
  if (!r.signature || !r.signature.trim())
    return { ok: false, reason: 'SignedRelease.signature must be a non-empty string' }
  if (!in01(r.canaryRatio))
    return { ok: false, reason: 'SignedRelease.canaryRatio must be ∈ [0,1]' }
  if (r.rollbackAvailable !== true)
    return { ok: false, reason: 'SignedRelease must keep rollback available (v8 §51.3 keep-or-rollback)' }
  if (!Number.isFinite(r.signedAt))
    return { ok: false, reason: 'SignedRelease.signedAt must be a finite timestamp' }
  return { ok: true }
}

/** Enforce §52.3 invariants on a performance intent. Pure. */
export function validatePerformanceIntent(i: PerformanceIntent): { ok: true } | { ok: false, reason: string } {
  if (!i.personaSnapshotRef || !i.personaSnapshotRef.trim())
    return { ok: false, reason: 'PerformanceIntent must reference a persona snapshot (personaSnapshotRef, v8 §52.5)' }
  const e = i.expression
  if (!Number.isFinite(e.valence) || e.valence < -1 || e.valence > 1)
    return { ok: false, reason: 'PerformanceIntent.expression.valence must be ∈ [−1,1]' }
  const others = [e.arousal, e.dominance, e.intimacy, e.certainty, e.curiosity, e.playfulness, e.reflection, e.urgency]
  if (!others.every(in01))
    return { ok: false, reason: 'PerformanceIntent.expression components (besides valence) must be ∈ [0,1]' }
  if (!Number.isFinite(i.timeMarked))
    return { ok: false, reason: 'PerformanceIntent.timeMarked must be a finite timestamp' }
  if (!Number.isFinite(i.duration) || i.duration < 0)
    return { ok: false, reason: 'PerformanceIntent.duration must be a finite number ≥ 0' }
  return { ok: true }
}
