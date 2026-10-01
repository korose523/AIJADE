import type { Belief, BeliefOwner, BeliefRejection, BeliefRevision, EvidenceEntry } from './belief'
import type { IteEstimate, ReplayBundle, ReplayRun } from './cbr'
import type { Distiller } from './consolidation'
import type { Appraisal, FeedbackEvent, StateSnapshot } from './contracts'
import type { EndogenousState, UtilityFeatures, WriteConstraints, WriteDecision } from './hac'
import type { IdentityCandidate, IdentityEvidence, IdentityLayer, IdentitySource, IdentityState, IdentityVersion } from './identity'
import type { InterventionPlan, RegisteredIntervention, ResolvedIntervention } from './intervention'
import type { LexicalIndex } from './sim'
import type {
  AffectiveSnapshot,
  BeliefConfig,
  CandidateKind,
  Episode,
  MemoryConfig,
  PhysiologicalStateV3,
  PresentationModulation,
  ProceduralMemory,
  RetrievalWeights,
  ScoredCandidate,
  SemanticFact,
  StorageAdapter,
  StoreSnapshotV1,
  ValidTime,
  WorkingMemory,
} from './types'

import { applyRevision, createBelief, retract } from './belief'
import { estimateITE, pairReplays, ReplayLog } from './cbr'
import { LexicalDistiller } from './consolidation'
import { retrievalStrength } from './forgetting'
import { durability as durabilityOf } from './gating'
import { HacController, mulberry32 } from './hac'
import { DEFAULT_CDI_CONFIG, feedbackToIdentityCandidate, IdentityController, snapshotToIdentityEvidence } from './identity'
import { DEFAULT_SWITCHES, bypassOf as interventionBypassOf, isEnabled as interventionIsEnabled, registerIntervention, resolveIntervention } from './intervention'
import { applyRetrievalNoise, deriveGateFromContent, derivePresentationModulation } from './plasticity'
import { collapseDuplicateContent, detectConflict, jaccard, scoreCandidate, scoreCandidatesStandardized } from './retrieval'
import { predictSalienceV2, SALIENCE_FEATURES, salienceFeatureVector } from './salience'
import { buildLexicalIndex, tokenize } from './sim'
import { DEFAULT_BELIEF_CONFIG, DEFAULT_MEMORY_CONFIG, isRetrievableStatus, NEUTRAL_AFFECT, NEUTRAL_PHYSIOLOGY_V3 } from './types'

/** Content salience above this is treated as a "salient" memory worth keeping. */
const SALIENCE_THRESHOLD = 0.5

/**
 * How many top-ranked candidates are scanned for R-conflicts (see `retrieve`).
 *
 * Deliberately a **constant**, not `topK`: the penalty a candidate receives must
 * not depend on how many the caller asked for, otherwise `retrieve(q, 4)` is not
 * a prefix of `retrieve(q, 8)` and recall@1/2/4/8 are not comparable. It is also
 * bounded because pairwise conflict detection is O(n²) — scanning the whole pool
 * (~12k candidates on LoCoMo) is not affordable, and is not needed: conflicts
 * only matter near the retrieval cutoff.
 */
const CONFLICT_RERANK_POOL = 150

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

function sigmoid(z: number): number {
  return 1 / (1 + Math.exp(-z))
}

/** A memory is retrievable only while `now` is inside its validity window. */
function inValidWindow(v: ValidTime, now: number): boolean {
  if (v.validFrom !== undefined && now < v.validFrom)
    return false
  if (v.validUntil !== undefined && now > v.validUntil)
    return false
  return true
}

export interface EncodeInput {
  id: string
  content: string
  createdAt: number
  context: Episode['context']
  baseStrength?: number
  /** Optional affect snapshot at encoding; defaults to neutral. */
  affect?: AffectiveSnapshot
  /**
   * 实验专用：**覆盖**该条记忆的显著性，跳过 `predictSalienceV2`。
   *
   * 存在的唯一理由是让「oracle 显著性 vs 预测显著性」（以及打乱显著性）这两类对照
   * 能走**完全相同**的 encode / consolidate / retrieve 路径 —— 否则差异可能来自
   * 预测器调用本身，而不是显著性取值。生产路径不传此字段，行为与从前逐位相同。
   *
   * 取值会被 clamp 到 [0,1]。`undefined` 表示"用预测器"。
   */
  salienceOverride?: number
}

interface RetrievalItem {
  kind: CandidateKind
  id: string
  content: string
  createdAt: number
  accessCount: number
  baseStrength: number
  durability: number
  salience: number
  socialSalience: number
  novelty: number
  contextTags: string[]
  affect: AffectiveSnapshot
}

interface ScoredInternal extends ScoredCandidate {
  createdAt: number
  durability: number
}

/**
 * The biomimetic long-term memory store.
 *
 * The only thing that distinguishes two instances of this store is the
 * `gating` field of their config. Everything else (corpus, retrieval weights,
 * forgetting curve, distiller) is identical. That is the entire experiment:
 * build one with DEFAULT_GATING and one with NO_GATING, run the same queries,
 * and compare.
 *
 * v2 / P2: the gate is driven by **content salience** (`predictSalienceV2`),
 * not hormones. Hormones become a disable-able `PresentationModulation` that is
 * never used to score memories.
 */

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export class BioticMemory {
  readonly episodes: Episode[] = []
  readonly facts: SemanticFact[] = []
  readonly procedural: ProceduralMemory[] = []
  readonly working: WorkingMemory[] = []
  /** v7 §10.2 — the belief graph (separate from the episodic evidence graph). */
  readonly beliefs: Belief[] = []
  /** v7 §25 contract #5 — every belief change is an auditable transaction. */
  readonly beliefRevisions: BeliefRevision[] = []
  /** Rejected candidates, recorded so source-traceability is measurable (§6). */
  readonly beliefRejections: BeliefRejection[] = []
  /** v7 §9 HAC controller — constructed only when `config.hac.enabled` (opt-in). */
  private hac?: HacController
  /** Monotonic seed for per-retrieval HAC degradation noise (reproducible). */
  private hacCall = 0
  /** v7 §11 CDI controller — constructed only when the closed loop is enabled (opt-in). */
  private identity?: IdentityController
  /** Latest HAC StateSnapshot, stashed so it can be bridged into CDI as evidence. */
  private lastHacSnapshot?: StateSnapshot
  config: MemoryConfig
  private nowMs: number
  private mood: PhysiologicalStateV3 = NEUTRAL_PHYSIOLOGY_V3
  private lastPresentation: PresentationModulation = { warmth: 0.5, verbosity: 0.5, hesitation: 0, energy: 0.5 }
  private index?: LexicalIndex
  /** v7 §26 — opt-in persistence adapter (undefined ⇒ fully in-memory, no I/O). */
  private storage?: StorageAdapter
  /** v7 §38 已解析干预（仅当干预 API 接入时构造）。描述「这次跑的是哪套配置」。 */
  private resolvedIntervention?: ResolvedIntervention
  /** v7 §12 CBR 回放日志（仅当 CBR 接入时构造）。 */
  private replayLog?: ReplayLog

  constructor(config: MemoryConfig = DEFAULT_MEMORY_CONFIG, now = Date.now()) {
    this.config = config
    this.nowMs = now
    // HAC is strictly opt-in: a controller exists only when explicitly enabled,
    // so the existing content-salience gating ablation (H2/H5) is never perturbed.
    this.hac = config.hac?.enabled ? new HacController(config.hac) : undefined
    // v7 §11 CDI is part of the same closed loop: it is constructed only when the
    // loop is enabled, so identity development can never perturb the baseline memory
    // dynamics (and CDI never touches durability/salience — the H2c guard holds).
    this.identity = config.hac?.enabled ? new IdentityController(config.cdi ?? DEFAULT_CDI_CONFIG) : undefined
    // v7 §38 — 干预 API 同样 opt-in：仅当显式 enabled 才解析并持有干预配置，
    // 默认不持有，故记忆 baseline 动力学永不被扰动（H2c 兼容护盾）。
    this.resolvedIntervention = config.intervention?.enabled
      ? (config.intervention.plan ? resolveIntervention(config.intervention.plan, config.intervention.seed ?? 0) : undefined)
      : undefined
    // v7 §12 CBR 研究内核 opt-in：仅当 enabled 才构造回放日志（独立解耦，P8/§43）。
    this.replayLog = config.cbr?.enabled ? new ReplayLog() : undefined
    // v7 §26 — opt-in storage tiering. If an adapter is configured, rehydrate any
    // persisted snapshot at construction time so a fresh instance resumes exactly
    // where a previous one left off (the falsifiable core of the storage layer).
    // hydrate() below restores the persisted intervention/CBR state when present.
    this.storage = config.storage
    const restored = this.storage?.load()
    if (restored)
      this.hydrate(restored)
  }

  setNow(ms: number): void {
    this.nowMs = ms
    this.index = undefined
  }

  /** Set the layered L3 state (presentation only — never gates memory). */
  setMood(state: PhysiologicalStateV3): void {
    this.mood = state
  }

  /** Last computed presentation modulation (for inspection; not used in scoring). */
  lastPresentationModulation(): PresentationModulation {
    return this.lastPresentation
  }

  now(): number {
    return this.nowMs
  }

  /** Social-salience proxy: second-person "you/your" or person-name density / length. */
  private deriveSocialSalience(content: string): number {
    const tokens = tokenize(content)
    const you = tokens.filter(t => t === 'you' || t === 'your' || t === 'yours' || t === 'yourself').length
    const names = content
      .split(/\s+/)
      .filter(w => /^[A-Z][a-z]+$/.test(w.replace(/[^A-Z]/gi, '')))
      .length
    const len = Math.max(8, tokens.length)
    return Math.min(1, (you + names) / len)
  }

  /**
   * Encode one episode. Durability is computed here from the **content salience**
   * (sigmoid of the v2 predictor score) under the gating config. Under NO_GATING
   * everything is exactly 1.
   */
  encode(input: EncodeInput): Episode {
    const ctx = { priors: [] as string[], idf: new Map<string, number>(), nDocs: 1 }
    // 显著性来源：实验注入（oracle / 打乱）优先，否则走 v2 预测器。
    const salience = input.salienceOverride !== undefined
      ? clamp01(input.salienceOverride)
      : clamp01(sigmoid(predictSalienceV2(input.content, ctx).score))
    const socialSalience = this.deriveSocialSalience(input.content)
    const novIdx = SALIENCE_FEATURES.findIndex(f => f.name === 'noveltyIdf')
    const novFeat = novIdx >= 0 ? salienceFeatureVector(input.content, ctx)[novIdx] : 0.5
    const novelty = clamp01(novFeat)
    const durability = durabilityOf({ salience, socialSalience, novelty }, this.config.gating)
    const ep: Episode = {
      id: input.id,
      content: input.content,
      createdAt: input.createdAt,
      lastAccessedAt: input.createdAt,
      accessCount: 0,
      baseStrength: input.baseStrength ?? 1,
      durability,
      encoding: { salience, socialSalience, novelty, affect: input.affect ?? NEUTRAL_AFFECT },
      context: input.context,
      consolidated: false,
      memoryType: 'episodic',
      status: 'active',
      validTime: {},
    }
    this.episodes.push(ep)
    this.index = undefined
    this.flush()
    return ep
  }

  /** Encode a procedural (how-to / skill) memory. */
  encodeProcedural(
    content: string,
    opts: Partial<Omit<ProceduralMemory, 'memoryType' | 'status' | 'validTime' | 'content'>> & {
      id?: string
      createdAt?: number
      validTime?: ValidTime
      status?: ProceduralMemory['status']
    } = {},
  ): ProceduralMemory {
    const m: ProceduralMemory = {
      id: opts.id ?? `proc_${this.procedural.length}_${this.nowMs}`,
      content,
      derivedFrom: opts.derivedFrom,
      createdAt: opts.createdAt ?? this.nowMs,
      lastAccessedAt: opts.createdAt ?? this.nowMs,
      accessCount: 0,
      baseStrength: opts.baseStrength ?? 1,
      durability: opts.durability ?? 1,
      contextTags: opts.contextTags ?? [],
      validTime: opts.validTime ?? {},
      status: opts.status ?? 'active',
      memoryType: 'procedural',
      confidence: opts.confidence ?? 1,
    }
    this.procedural.push(m)
    this.index = undefined
    this.flush()
    return m
  }

  /** Encode a working-memory (short-term active buffer) entry. */
  encodeWorking(
    content: string,
    opts: Partial<Omit<WorkingMemory, 'memoryType' | 'status' | 'validTime' | 'content'>> & {
      id?: string
      createdAt?: number
      validTime?: ValidTime
      status?: WorkingMemory['status']
    } = {},
  ): WorkingMemory {
    const m: WorkingMemory = {
      id: opts.id ?? `work_${this.working.length}_${this.nowMs}`,
      content,
      createdAt: opts.createdAt ?? this.nowMs,
      lastAccessedAt: opts.createdAt ?? this.nowMs,
      accessCount: 0,
      baseStrength: opts.baseStrength ?? 1,
      durability: opts.durability ?? 1,
      contextTags: opts.contextTags ?? [],
      validTime: opts.validTime ?? {},
      status: opts.status ?? 'active',
      memoryType: 'working',
    }
    this.working.push(m)
    this.index = undefined
    this.flush()
    return m
  }

  // ---------- v7 §10.2 belief graph ----------

  private beliefConfig(): BeliefConfig {
    return this.config.belief ?? DEFAULT_BELIEF_CONFIG
  }

  /**
   * Propose a belief. Hard rule (v7 §6): a candidate with **no source** must not
   * enter the belief graph. Rejections are recorded rather than thrown, so that
   * source-traceability stays measurable.
   */
  proposeBelief(input: {
    id?: string
    proposition: string
    scope?: string
    owner?: BeliefOwner
    evidenceIds: string[]
    validFrom?: number
    validTo?: number
    actor?: string
  }): { ok: true, belief: Belief } | { ok: false, reason: string } {
    const now = this.nowMs
    if (input.evidenceIds.length === 0) {
      this.beliefRejections.push({
        proposition: input.proposition,
        reason: 'no source: v7 §6 forbids sourceless entries in the belief graph',
        at: now,
        actor: input.actor ?? 'agent',
      })
      this.flush()
      return { ok: false, reason: 'no source: a belief requires at least one evidence id' }
    }
    const belief = createBelief(
      {
        id: input.id ?? `belief_${this.beliefs.length}_${now}`,
        proposition: input.proposition,
        scope: input.scope,
        owner: input.owner,
        evidenceIds: input.evidenceIds,
        at: now,
        validFrom: input.validFrom,
        validTo: input.validTo,
      },
      this.beliefConfig(),
    )
    this.beliefs.push(belief)
    this.flush()
    return { ok: true, belief }
  }

  /** Apply an evidence transaction (v7 §10.2); counter-evidence is subtracted. */
  reviseBelief(
    beliefId: string,
    input: {
      evidence?: EvidenceEntry[]
      counterEvidence?: EvidenceEntry[]
      actor?: string
      rationale?: string
    },
  ): { ok: true, belief: Belief, revision: BeliefRevision } | { ok: false, reason: string } {
    const idx = this.beliefs.findIndex(b => b.id === beliefId)
    if (idx < 0)
      return { ok: false, reason: `belief not found: ${beliefId}` }
    const { belief, revision } = applyRevision(
      this.beliefs[idx],
      {
        id: `rev_${this.beliefRevisions.length}_${beliefId}`,
        at: this.nowMs,
        evidence: input.evidence,
        counterEvidence: input.counterEvidence,
        actor: input.actor ?? 'agent',
        rationale: input.rationale,
      },
      this.beliefConfig(),
    )
    this.beliefs[idx] = belief
    this.beliefRevisions.push(revision)
    this.flush()
    return { ok: true, belief, revision }
  }

  /** Explicit retraction — never a silent overwrite (v7 §10.4). */
  retractBelief(
    beliefId: string,
    reason: string,
    actor = 'user',
  ): { ok: true, belief: Belief, revision: BeliefRevision } | { ok: false, reason: string } {
    const idx = this.beliefs.findIndex(b => b.id === beliefId)
    if (idx < 0)
      return { ok: false, reason: `belief not found: ${beliefId}` }
    const { belief, revision } = retract(this.beliefs[idx], {
      id: `rev_${this.beliefRevisions.length}_${beliefId}`,
      at: this.nowMs,
      actor,
      reason,
    })
    this.beliefs[idx] = belief
    this.beliefRevisions.push(revision)
    this.flush()
    return { ok: true, belief, revision }
  }

  /** Beliefs usable right now: not retracted and inside their validity window. */
  activeBeliefs(owner?: BeliefOwner): Belief[] {
    const now = this.nowMs
    return this.beliefs.filter(b =>
      b.status !== 'retracted'
      && (owner === undefined || b.owner === owner)
      && (b.validTo === undefined || now <= b.validTo))
  }

  // ---------- v7 §9 HAC (opt-in) ----------

  /** Advance the HAC endogenous state from a stimulus + action/feedback pair. */
  stepHac(stimulus: EndogenousState, action: EndogenousState): void {
    if (!this.hac)
      return
    this.hac.step(stimulus, action, mulberry32((this.nowMs + this.hacCall) >>> 0))
    this.hacCall++
    this.flush()
  }

  /** Current HAC endogenous state, or undefined when HAC is disabled. */
  hacState(): EndogenousState | undefined {
    return this.hac?.state
  }

  /**
   * HAC write decision for a candidate memory (§9.3). Returns undefined when HAC
   * is disabled so callers fall back to the content-salience path.
   */
  hacWriteDecision(f: UtilityFeatures, constraints: WriteConstraints): WriteDecision | undefined {
    return this.hac?.decide(f, constraints)
  }

  /**
   * Advance HAC z_t from a §25 `Appraisal` (#2) — the appraisal→z_t loop-closing
   * path (§9.1). Opt-in: a no-op when HAC is disabled. The appraisal drives the
   * state only through the stimulus channel; it never touches durability/salience
   * (H2c guard preserved).
   */
  stepHacAppraisal(appraisal: Appraisal): void {
    if (!this.hac)
      return
    this.hac.stepAppraisal(appraisal, mulberry32((this.nowMs + this.hacCall) >>> 0))
    this.hacCall++
    // Stash a frozen snapshot so the HAC→CDI bridge (cdiObserveHac) can feed the
    // endogenous state into identity development as *evidence* — never as a write.
    this.lastHacSnapshot = this.hac.snapshot('hac', this.nowMs, appraisal.agentId, appraisal.userScope)
    this.flush()
  }

  /**
   * Produce a frozen, content-addressed `StateSnapshot` (#3) of the current HAC
   * state, or undefined when HAC is disabled. This is the HAC→identity loop output:
   * the snapshot can be fed into the CDI evidence window without HAC ever writing
   * memory (§25 #3 / §11).
   */
  hacSnapshot(takenAt?: number, agentId = '', userScope = ''): StateSnapshot | undefined {
    if (!this.hac)
      return undefined
    return this.hac.snapshot('hac', takenAt ?? this.nowMs, agentId, userScope)
  }

  // ---------- v7 §11 CDI product surface (opt-in, part of the HAC+CDI loop) ----------

  /**
   * Build a §25 #6 `IdentityCandidate` from a §25 #14 `FeedbackEvent` WITHOUT
   * committing it, for shadow evaluation (§11.3) before any identity change is
   * signed. Opt-in: returns undefined when the closed loop is disabled.
   */
  cdiProposalFromFeedback(
    feedback: FeedbackEvent,
    opts: { episodeId: string, layer: IdentityLayer, paramKey: string, deltaValue: number, proposedBy?: IdentitySource, explicitUpgrade?: boolean, justification?: string, traceable?: boolean },
  ): IdentityCandidate | undefined {
    if (!this.identity)
      return undefined
    return feedbackToIdentityCandidate(feedback, opts)
  }

  /**
   * Apply a §25 #6 `IdentityCandidate` derived from a §25 #14 `FeedbackEvent`
   * (§11.3): the candidate is validated + solved against the §11.2 bounds and, if
   * admissible, committed as a signed version. Opt-in: returns undefined when the
   * closed loop is disabled. CDI NEVER touches memory durability/salience — it is
   * its own module, so the H2c guard holds structurally.
   */
  cdiFromFeedback(
    feedback: FeedbackEvent,
    opts: { episodeId: string, layer: IdentityLayer, paramKey: string, deltaValue: number, proposedBy?: IdentitySource, explicitUpgrade?: boolean, justification?: string, traceable?: boolean },
  ): { ok: true, version: IdentityVersion } | { ok: false, stage: string, reason: string } | undefined {
    if (!this.identity)
      return undefined
    const candidate = feedbackToIdentityCandidate(feedback, opts)
    const result = this.identity.apply(candidate, opts.proposedBy ?? candidate.proposedBy)
    // identity changed → persist behind the opt-in adapter (mirrors stepHacAppraisal).
    this.flush()
    return result
  }

  /** Current CDI identity state, or undefined when the closed loop is disabled. */
  cdiState(): IdentityState | undefined {
    return this.identity?.state
  }

  /** Signed identity version history, or undefined when the closed loop is disabled. */
  cdiVersions(): IdentityVersion[] | undefined {
    return this.identity?.history
  }

  /** Roll back to a prior signed identity version (§11.3). No-op when disabled. */
  cdiRollback(signature: string): IdentityVersion | undefined {
    if (!this.identity)
      return undefined
    const v = this.identity.rollbackTo(signature)
    this.flush()
    return v
  }

  /**
   * Bridge the latest HAC endogenous-state snapshot into the CDI evidence window as
   * an `observation` from the world (§11.3). HAC's closed-loop output informs
   * identity development *as evidence* — it never drives durability/salience, and
   * CDI never writes memory. Returns the produced evidence (or undefined when the
   * loop is disabled or no HAC snapshot has yet been taken).
   */
  cdiObserveHac(episodeId: string, traceable = true): IdentityEvidence | undefined {
    if (!this.identity || !this.lastHacSnapshot)
      return undefined
    return snapshotToIdentityEvidence(this.lastHacSnapshot, episodeId, traceable)
  }

  // ---------- v7 §38 统一干预 API（opt-in，H2c 兼容） ----------

  /**
   * v7 §38 — 登记并解析一份干预计划（基线或消融），使其成为本实例的「当前配置」。
   * 仅当干预 API 已接入（config.intervention.enabled）时可用；否则返回 undefined。
   *
   * 默认只解析并持有 resolved 配置（不写盘）；传入 `registryPath` 才把该干预
   * 落成一份 §38 `ExperimentManifest` 写入提交式 registry（可复现登记）。
   * 不改动任何记忆 durability/salience —— 干预 API 仅描述「这次跑的是哪套配置」（H2c）。
   */
  applyIntervention(
    plan: InterventionPlan,
    opts: { seed?: number, registryPath?: string, metrics?: string[] } = {},
  ): { resolved: ResolvedIntervention, registered?: RegisteredIntervention } | undefined {
    if (!this.config.intervention?.enabled)
      return undefined
    const seed = opts.seed ?? this.config.intervention.seed ?? 0
    const resolved = resolveIntervention(plan, seed)
    this.resolvedIntervention = resolved
    this.flush()
    if (opts.registryPath) {
      const registered = registerIntervention(plan, { seed, registryPath: opts.registryPath, metrics: opts.metrics })
      return { resolved, registered }
    }
    return { resolved }
  }

  /** v7 §38 — 当前已解析干预（未接入干预 API 时返回 undefined）。 */
  interventionResolved(): ResolvedIntervention | undefined {
    return this.resolvedIntervention
  }

  /**
   * v7 §38 — 查询某干预点在当前配置下是否启用。
   * 未接入干预 API（或尚未登记计划）时回退 `DEFAULT_SWITCHES`，未知点按「未启用」。
   */
  interventionEnabled(pointId: string): boolean {
    return this.resolvedIntervention
      ? interventionIsEnabled(this.resolvedIntervention, pointId)
      : (DEFAULT_SWITCHES[pointId] ?? false)
  }

  /** v7 §38 — 取某干预点的旁路实现标识；未旁路或已禁用干预 API 时为 undefined。 */
  interventionBypass(pointId: string): string | undefined {
    return this.resolvedIntervention ? interventionBypassOf(this.resolvedIntervention, pointId) : undefined
  }

  /** v7 §38 — 当前配置的确定性指纹；同一 (plan, seed) 必得同一指纹（可复现证明）。 */
  interventionFingerprint(): string | undefined {
    return this.resolvedIntervention?.fingerprint
  }

  // ---------- v7 §12 CBR 因果具身回放（opt-in，P8/§43 解耦） ----------

  /**
   * v7 §12 — 写入一条回放束（不可变、内容寻址校验）。仅当 CBR 接入时可用；
   * 否则返回 undefined。回放束是证据，不是缓存 —— 重复 bundleId 被拒（append-only）。
   */
  cbrLogBundle(b: ReplayBundle): { ok: true } | { ok: false, reason: string } | undefined {
    if (!this.replayLog)
      return undefined
    const r = this.replayLog.add(b)
    if (r.ok)
      this.flush()
    return r
  }

  /** v7 §12 — 取回一条已登录的回放束；未接入 CBR 时返回 undefined。 */
  cbrGetBundle(bundleId: string): ReplayBundle | undefined {
    return this.replayLog?.get(bundleId)
  }

  /** v7 §12 — 当前全部已登录回放束；未接入 CBR 时返回空数组。 */
  cbrBundles(): ReplayBundle[] {
    return this.replayLog?.all() ?? []
  }

  /**
   * v7 §12 — 在已登录回放束上做**配对** ITE 估计：
   * 同一事件束在 treated(gate=1) 与 control(gate=0) 下各跑一遍，配对差即 ITE。
   *
   * 回放束本身只承载「这次交互是什么」，其结果 Y 由调用方（把束投入策略/模型）
   * 产出，故本方法收 `bundleId → outcome` 映射而非凭空捏造 outcome。
   * 仅当 CBR 接入时可用；未接入返回 undefined。不改动记忆 durability/salience（H2c）。
   */
  cbrEstimateITE(
    treatedOutcomes: Record<string, number>,
    controlOutcomes: Record<string, number>,
  ): IteEstimate | undefined {
    if (!this.replayLog)
      return undefined
    const byId = new Map(this.replayLog.all().map(b => [b.bundleId, b]))
    const toRuns = (map: Record<string, number>): ReplayRun[] => Object.keys(map)
      .map(id => byId.get(id))
      .filter((b): b is ReplayBundle => !!b)
      .map(b => ({ bundle: b, outcome: map[b.bundleId] }))
    const treated = toRuns(treatedOutcomes)
    const control = toRuns(controlOutcomes)
    const { pairs } = pairReplays(treated, control)
    return estimateITE(pairs)
  }

  // ---------- v7 §26 storage tiering (opt-in) ----------

  /**
   * Capture a serializable snapshot of all in-memory state. The HAC endogenous
   * state is included only when HAC is enabled. Pure read — never touches
   * durability/salience, and never serialises the adapter itself.
   */
  toSnapshot(): StoreSnapshotV1 {
    const savedConfig = clone(this.config)
    // The adapter is not serializable; strip it. The rehydrating instance supplies
    // its own adapter via the constructor, so it must not be carried in the snapshot.
    delete (savedConfig as { storage?: unknown }).storage
    return {
      schema: 'aijade.store_snapshot@1',
      config: savedConfig,
      collections: {
        episodes: clone(this.episodes),
        facts: clone(this.facts),
        procedural: clone(this.procedural),
        working: clone(this.working),
        beliefs: clone(this.beliefs),
        beliefRevisions: clone(this.beliefRevisions),
        beliefRejections: clone(this.beliefRejections),
      },
      hac: this.hac ? { z: this.hac.state, call: this.hacCall } : undefined,
      cdi: this.identity ? { state: this.identity.state, versions: this.identity.history } : undefined,
      intervention: this.resolvedIntervention ? { resolved: this.resolvedIntervention } : undefined,
      cbr: this.replayLog ? { bundles: this.replayLog.all() } : undefined,
    }
  }

  /** Persist the current state through the configured adapter (no-op when none). */
  save(): void {
    this.storage?.persist(this.toSnapshot())
  }

  /** Internal: flush current state to the adapter after any durable mutation. */
  private flush(): void {
    this.storage?.persist(this.toSnapshot())
  }

  /**
   * Rehydrate all collections + HAC state from a snapshot (v7 §26). Arrays are
   * mutated in place (the fields are `readonly` bindings but mutable contents), so
   * callers observe the restored state immediately. Never decides retention —
   * it only *carries* what was persisted.
   */
  private hydrate(s: StoreSnapshotV1): void {
    this.episodes.length = 0
    this.episodes.push(...s.collections.episodes)
    this.facts.length = 0
    this.facts.push(...s.collections.facts)
    this.procedural.length = 0
    this.procedural.push(...s.collections.procedural)
    this.working.length = 0
    this.working.push(...s.collections.working)
    this.beliefs.length = 0
    this.beliefs.push(...s.collections.beliefs)
    this.beliefRevisions.length = 0
    this.beliefRevisions.push(...s.collections.beliefRevisions)
    this.beliefRejections.length = 0
    this.beliefRejections.push(...s.collections.beliefRejections)
    if (s.hac && this.config.hac?.enabled) {
      this.hac = new HacController(this.config.hac, s.hac.z)
      this.hacCall = s.hac.call
    }
    else {
      this.hacCall = s.hac?.call ?? 0
    }
    if (s.cdi && this.config.hac?.enabled) {
      this.identity = new IdentityController(this.config.cdi ?? DEFAULT_CDI_CONFIG, s.cdi.state, undefined, s.cdi.versions)
    }
    if (s.intervention && this.config.intervention?.enabled) {
      this.resolvedIntervention = s.intervention.resolved
    }
    if (s.cbr && this.config.cbr?.enabled && this.replayLog) {
      for (const b of s.cbr.bundles)
        this.replayLog.add(b)
    }
    this.index = undefined
  }

  /** Score a single stored memory under a query — reuses the retrieval scoring. */
  scoreCandidateById(query: string, id: string): ScoredCandidate | null {
    return this.retrieve(query, 9999, false).find(c => c.id === id) ?? null
  }

  /**
   * Distill episodes into semantic facts.
   *
   * Consolidation is *selective* when content gating is active; the rest are
   * pruned (marked forgotten). This is the interference-driven forgetting that
   * protects capacity for what matters. Under NO_GATING every coefficient is 0,
   * so `selective` is false and the branch degenerates to "distill everything" —
   * nothing is pruned.
   *
   * **保留策略（两种，实验可切换）**
   * - `absolute`（默认，历史行为）：保留 `salience > SALIENCE_THRESHOLD`（0.5）。
   *   缺陷：`salience = sigmoid(predictorScore)` 以 0.5 为中心，判定退化为
   *   "预测器分数 > 0"。实测 `predictSalienceV2` 的分数几乎恒为正，
   *   于是该通道几乎**永不触发**（LoCoMo 全量仅剪 4/5882）——
   *   一个整机制被一个未校准的常数关掉了。见 `eval/diag-oracle-vs-predicted-salience.ts`。
   * - `quantile`（`opts.keepFraction` 给定时启用）：按 salience **排名**保留前
   *   `keepFraction` 比例。把"保留多少"从预测器的输出尺度里解放出来，
   *   使压缩率可**显式指定**（与 H5 的存储预算设定同源）。
   */
  async consolidate(
    distiller: Distiller = new LexicalDistiller(),
    opts: { selective?: boolean, keepFraction?: number } = {},
  ): Promise<{ facts: SemanticFact[], consumed: string[], skipped: { episodeIds: string[], reason: string }[] }> {
    const pending = this.episodes.filter(e => !e.consolidated && !e.forgotten)
    if (pending.length < this.config.consolidateThreshold)
      return { facts: [], consumed: [], skipped: [] }
    const g = this.config.gating
    // opts.selective 可**显式**覆盖选择性剪枝，用于把"剪枝"与"检索期重加权"
    // 这两个混在 DEFAULT_GATING 里的维度解耦（见 eval/diag-oracle-vs-predicted-salience.ts）。
    const selective = opts.selective ?? (g.kSalience !== 0 || g.kSocial !== 0)

    let keepIds: Set<string> | null = null
    if (selective) {
      if (opts.keepFraction !== undefined) {
        const k = Math.max(1, Math.min(pending.length, Math.round(pending.length * clamp01(opts.keepFraction))))
        const ranked = [...pending].sort((a, b) => b.encoding.salience - a.encoding.salience).slice(0, k)
        keepIds = new Set(ranked.map(e => e.id))
      }
      else {
        keepIds = new Set(pending.filter(e => e.encoding.salience > SALIENCE_THRESHOLD).map(e => e.id))
      }
    }

    // 保持 pending 的原始顺序，使 fact id 与既有一致（排名只决定"留谁"，不决定顺序）。
    const selected = keepIds ? pending.filter(e => keepIds.has(e.id)) : pending
    const facts = await distiller.distill(selected)
    this.facts.push(...facts)
    for (const e of selected) e.consolidated = true
    const pruned = keepIds ? pending.filter(e => !keepIds.has(e.id)) : []
    for (const e of pruned) e.forgotten = true
    this.index = undefined
    this.flush()
    return {
      facts,
      consumed: selected.map(e => e.id),
      skipped: pruned.map(e => ({
        episodeIds: [e.id],
        reason: keepIds && opts.keepFraction !== undefined
          ? `outranked under quantile retention (keepFraction=${opts.keepFraction})`
          : 'not selected by content-salience gating (pruned)',
      })),
    }
  }

  private ensureIndex(): LexicalIndex {
    if (!this.index) {
      const docs = [
        ...this.episodes.filter(e => !e.forgotten).map(e => ({ id: e.id, text: e.content })),
        ...this.facts.map(f => ({ id: f.id, text: f.content })),
        ...this.procedural.map(p => ({ id: p.id, text: p.content })),
        ...this.working.map(w => ({ id: w.id, text: w.content })),
      ]
      this.index = buildLexicalIndex(docs)
      for (const e of this.episodes) e.embedding = Array.from(this.index.denseVec(e.id))
      for (const f of this.facts) f.embedding = Array.from(this.index.denseVec(f.id))
    }
    return this.index
  }

  private toRetrievalItem(
    kind: CandidateKind,
    id: string,
    content: string,
    createdAt: number,
    accessCount: number,
    baseStrength: number,
    durability: number,
    salience: number,
    socialSalience: number,
    novelty: number,
    contextTags: string[],
    affect: AffectiveSnapshot,
  ): RetrievalItem {
    return { kind, id, content, createdAt, accessCount, baseStrength, durability, salience, socialSalience, novelty, contextTags, affect }
  }

  /** Retrieve the top-K scored candidates for a query, with content-salience gating + R-conflict penalty. */
  retrieve(query: string, topK = 10, bump = true, weights?: Partial<RetrievalWeights>): ScoredCandidate[] {
    const idx = this.ensureIndex()
    const qVec = idx.querySparse(query)
    const queryTags = tokenize(query)
    const f = this.config.forgetting
    const g = this.config.gating
    // Optional per-call weight override (J5 §X): lets an eval re-score the SAME
    // candidates under corrected weights without mutating the store config.
    // Default (undefined) ⇒ zero behaviour change.
    const w = weights ? { ...this.config.weights, ...weights } : this.config.weights
    const conflictPenalty = this.config.conflictPenalty ?? 0.5
    // Read defensively (`??`) so snapshot configs written before these fields
    // existed still rehydrate: absent means "corrected behaviour", which is what
    // a store constructed today would have.
    const scoreMode = this.config.retrievalScoreMode ?? 'standardized'
    const dedupeByContentEnabled = this.config.dedupeByContent ?? true
    const now = this.nowMs

    // v2 / P2：记忆门控由内容显著性驱动（deriveGateFromContent），不再由 this.mood。
    // 若表达层启用，计算 PresentationModulation 供审计，但**绝不**改变检索分数。
    if (this.config.physiology.enabled)
      this.lastPresentation = derivePresentationModulation(this.mood, true)

    const items: RetrievalItem[] = [
      ...this.episodes
        .filter(e => !e.forgotten && isRetrievableStatus(e.status) && inValidWindow(e.validTime, now))
        .map<RetrievalItem>(e => this.toRetrievalItem(
          'episode',
          e.id,
          e.content,
          e.createdAt,
          e.accessCount,
          e.baseStrength,
          e.durability,
          e.encoding.salience,
          e.encoding.socialSalience,
          e.encoding.novelty,
          e.context.tags,
          e.encoding.affect,
        )),
      ...this.facts
        .filter(fc => isRetrievableStatus(fc.status) && inValidWindow(fc.validTime, now))
        .map<RetrievalItem>(fc => this.toRetrievalItem(
          'fact',
          fc.id,
          fc.content,
          fc.createdAt,
          fc.accessCount,
          fc.baseStrength,
          fc.durability,
          fc.salience,
          0.5,
          0.5,
          fc.contextTags,
          fc.affect,
        )),
      ...this.procedural
        .filter(p => isRetrievableStatus(p.status) && inValidWindow(p.validTime, now))
        .map<RetrievalItem>(p => this.toRetrievalItem(
          'procedural',
          p.id,
          p.content,
          p.createdAt,
          p.accessCount,
          p.baseStrength,
          p.durability,
          0.5,
          0.5,
          0.5,
          p.contextTags,
          NEUTRAL_AFFECT,
        )),
      ...this.working
        .filter(wm => isRetrievableStatus(wm.status) && inValidWindow(wm.validTime, now))
        .map<RetrievalItem>(wm => this.toRetrievalItem(
          'working',
          wm.id,
          wm.content,
          wm.createdAt,
          wm.accessCount,
          wm.baseStrength,
          wm.durability,
          0.5,
          0.5,
          0.5,
          wm.contextTags,
          NEUTRAL_AFFECT,
        )),
    ]

    // ── Content deduplication ─────────────────────────────────────────────
    // `LexicalDistiller` emits one fact per episode with byte-identical content,
    // so without this every piece of evidence occupies two ranks and every
    // recall@K is really recall@K/2. See `collapseDuplicateContent`.
    const dedup = dedupeByContentEnabled
      ? collapseDuplicateContent(items)
      : { kept: items, absorbed: new Map<string, string[]>() }
    const ranked = dedup.kept

    // ── Component extraction (pool-wide, hence K-independent) ─────────────
    const rows = ranked.map(it => ({
      similarity: idx.cosine(qVec, it.id),
      strengthRaw: retrievalStrength(
        { createdAt: it.createdAt, accessCount: it.accessCount, baseStrength: it.baseStrength, durability: it.durability },
        now,
        f,
        g,
        it.salience,
      ),
      // affect term is presentation-only — 0 so it never biases the memory score.
      affect: 0,
      recency: 1 / (1 + Math.max(0, now - it.createdAt) / f.ageScaleMs),
      context: jaccard(queryTags, it.contextTags),
    }))
    // `'standardized'` z-scores each component across this pool; the weights are
    // untouched. `'additive'` is the legacy raw sum, kept for reproduction.
    const standardized = scoreMode === 'standardized'
      ? scoreCandidatesStandardized(rows, w)
      : null

    const scored: ScoredInternal[] = ranked.map((it, i) => {
      const gate = deriveGateFromContent({ salience: it.salience, socialSalience: it.socialSalience, novelty: it.novelty })
      let base: number
      let parts: ScoredCandidate['parts']
      if (standardized) {
        base = standardized[i].score
        parts = { ...standardized[i].rawParts, z: standardized[i].z }
      }
      else {
        const legacy = scoreCandidate(rows[i].similarity, rows[i].strengthRaw, rows[i].recency, rows[i].context, rows[i].affect, w)
        base = legacy.score
        parts = legacy.parts
      }
      const absorbedIds = dedup.absorbed.get(it.id)
      if (absorbedIds)
        parts = { ...parts, deduplicatedIds: absorbedIds }
      let noisy = applyRetrievalNoise(base, it.id, gate.retrievalNoise)
      if (this.hac) {
        // v7 §9.5 — cognitive-load-driven retrieval degradation: a *cost* that
        // grows with load c_t, making HAC falsifiable (not a gain knob).
        const xi = this.hac.degradation(mulberry32((this.nowMs + this.hacCall) >>> 0))
        noisy += xi
        this.hacCall++
      }
      return {
        kind: it.kind,
        id: it.id,
        content: it.content,
        score: noisy,
        parts: { ...parts, noise: gate.retrievalNoise },
        createdAt: it.createdAt,
        durability: it.durability,
      }
    })

    // R-conflict penalty (spec §3): detect pairs sharing a key entity with
    // opposing polarity; penalise the OLDER + lower-durability loser.
    // "冲突时以新近 + 高巩固强度者为准，保留旧版本供审计" —— 双份都留在 store，只罚分。
    //
    // The scanned head is a *constant* under the corrected scoring, so the
    // penalty a candidate receives cannot depend on `topK`. `'additive'` keeps
    // the legacy K-dependent head purely so pre-fix numbers reproduce exactly.
    const penaltyHead = standardized ? CONFLICT_RERANK_POOL : topK
    scored.sort((a, b) => b.score - a.score)
    const top = scored.slice(0, penaltyHead)
    for (let i = 0; i < top.length; i++) {
      for (let j = i + 1; j < top.length; j++) {
        if (!detectConflict(top[i].content, top[j].content))
          continue
        const [winner, loser] = pickConflictWinnerLoser(top[i], top[j])
        void winner
        loser.score *= conflictPenalty
        loser.parts.conflict = true
      }
    }
    scored.sort((a, b) => b.score - a.score)
    const finalTop = scored.slice(0, topK)
    if (bump) {
      for (const c of finalTop) {
        const target
          = this.episodes.find(e => e.id === c.id)
            ?? this.facts.find(fc => fc.id === c.id)
            ?? this.procedural.find(p => p.id === c.id)
            ?? this.working.find(wm => wm.id === c.id)
        if (target) {
          target.accessCount++
          target.lastAccessedAt = now
        }
      }
    }
    // strip internal meta before returning
    return finalTop.map(({ kind, id, content, score, parts }) => ({ kind, id, content, score, parts }))
  }
}

/**
 * Decide conflict winner/loser: newer + higher-durability wins. The loser is the
 * older and/or lower-durability candidate (penalised, but kept for audit).
 */
function pickConflictWinnerLoser(a: ScoredInternal, b: ScoredInternal): [ScoredInternal, ScoredInternal] {
  if (a.createdAt !== b.createdAt)
    return a.createdAt > b.createdAt ? [a, b] : [b, a]
  if (a.durability !== b.durability)
    return a.durability > b.durability ? [a, b] : [b, a]
  return [a, b]
}
