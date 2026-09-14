import type { ForgettingConfig, GatingCoefficients } from './types'

import { gateFromCoefficients } from './plasticity'

/**
 * 两阶段可审计遗忘（v3 §5 / v4 §7.4）。
 *
 * v3 §5 原文：
 *   阶段一 软遗忘：strength ← strength × exp(-Δt × base_decay × decay_multiplier)
 *                  strength < θ_low → 降级 tier，不删除
 *   阶段二 硬遗忘：冷层驻留超 T 且 access_count == 0 → 进入删除候选队列
 *                  候选可预览、可按 ID 保留、删除留审计记录
 *   **永不静默删除。** 这既是工程要求，也是「可审计遗忘」这一差异化卖点的兑现。
 *
 * 与 v3 §5 的「三级驻留（热 ctx / 温 pgvector / 冷 归档）」对应。
 */

export type MemoryTier = 'hot' | 'warm' | 'cold'

export interface ForgettingThresholds {
  /** strength 低于此值 → 降一级（软遗忘），不删除 */
  demoteBelow: number
  /** strength 高于此值 → 视为热层 */
  hotAbove: number
  /** 冷层驻留超过这么多天且 accessCount==0 → 成为删除候选 */
  coldDwellDays: number
}

export const DEFAULT_THRESHOLDS: ForgettingThresholds = {
  demoteBelow: 0.25,
  hotAbove: 0.6,
  coldDwellDays: 30,
}

const DAY_MS = 86_400_000

/** strength → tier。注意：只看强度，与是否被访问无关。 */
export function tierOf(strength: number, t: ForgettingThresholds = DEFAULT_THRESHOLDS): MemoryTier {
  if (strength >= t.hotAbove)
    return 'hot'
  if (strength >= t.demoteBelow)
    return 'warm'
  return 'cold'
}

const TIER_ORDER: Record<MemoryTier, number> = { hot: 0, warm: 1, cold: 2 }

export interface SweepInput {
  id: string
  createdAt: number
  lastAccessedAt: number
  accessCount: number
  baseStrength: number
  durability: number
  tier?: MemoryTier
}

export interface SweepResult {
  id: string
  /** 衰减后的 strength */
  strength: number
  tier: MemoryTier
  /** 本次是否发生降级 */
  demoted: boolean
  /** 阶段二：进入删除候选队列（仅候选，绝不就地删除） */
  deletionCandidate: boolean
  reason?: string
}

/**
 * 对单条记忆跑一次遗忘扫描。
 *
 * - strength 由既有幂律衰减给出（forgetting.ts），并用 gate.decayMultiplier 调制；
 * - tier 只降不升（访问会提升 strength，从而在下一次扫描时自然回温，
 *   但同一次扫描内不做晋升，避免扫描顺序影响结果）；
 * - 只有当 tier==cold 且 accessCount==0 且冷层驻留 ≥ coldDwellDays 才成为候选。
 */
export function sweepForgetting(
  item: SweepInput,
  now: number,
  f: ForgettingConfig,
  g: GatingCoefficients,
  currentCortisol: number,
  decayMultiplier: number,
  t: ForgettingThresholds = DEFAULT_THRESHOLDS,
): SweepResult {
  // 阶段一：软遗忘（指数衰减，v3 §5）
  const dtDays = Math.max(0, now - item.createdAt) / DAY_MS
  const spacing = (1 + item.accessCount) ** f.spacingBeta
  const decayed = (item.baseStrength * item.durability * spacing)
    * Math.exp(-dtDays * f.baseDecay * decayMultiplier)
  const strength = Math.max(0, decayed)

  const prevTier: MemoryTier = item.tier ?? tierOf(strength, t)
  const nextTier = tierOf(strength, t)
  // 只降不升
  const tier: MemoryTier = TIER_ORDER[nextTier] > TIER_ORDER[prevTier] ? nextTier : prevTier
  const demoted = TIER_ORDER[tier] > TIER_ORDER[prevTier]

  // 阶段二：硬遗忘候选判定
  const dwellDays = (now - item.lastAccessedAt) / DAY_MS
  let deletionCandidate = false
  let reason: string | undefined
  if (tier === 'cold' && item.accessCount === 0 && dwellDays >= t.coldDwellDays) {
    deletionCandidate = true
    reason = `cold tier, accessCount=0, dwell=${dwellDays.toFixed(1)}d >= ${t.coldDwellDays}d`
  }

  // currentCortisol 参与既有幂律口径的一致性（调用方已用 gate 调制 decayMultiplier）
  void currentCortisol
  void g

  return { id: item.id, strength, tier, demoted, deletionCandidate, reason }
}

/** 方便调用方：直接从 gate 取 decayMultiplier。 */
export function sweepWithGate(
  item: SweepInput,
  now: number,
  f: ForgettingConfig,
  g: GatingCoefficients,
  state: Parameters<typeof gateFromCoefficients>[1],
  t: ForgettingThresholds = DEFAULT_THRESHOLDS,
): SweepResult {
  const gate = gateFromCoefficients(g, state)
  return sweepForgetting(item, now, f, g, state.cortisol, gate.decayMultiplier, t)
}

export interface DeletionLedgerEntry {
  id: string
  queuedAt: number
  reason: string
  /** 审计：是哪一套门控做出的决定（v4 §5.5 gate_snapshot） */
  gateSnapshot: { decayMultiplier: number, retrievalNoise: number }
  resolvedAt?: number
  resolution?: 'deleted' | 'retained'
}

/**
 * 删除台账。**唯一**允许删除的路径是 `commit()`，且每次删除都留痕。
 * 队列中的条目可被 `retain()` 按 ID 保留（v3 §5：候选可预览、可按 ID 保留）。
 */
export class DeletionLedger {
  private readonly entries: DeletionLedgerEntry[] = []

  /** 入队（阶段二）。不删除任何东西。 */
  enqueue(
    id: string,
    reason: string,
    now: number,
    gate: { decayMultiplier: number, retrievalNoise: number },
  ): void {
    if (this.entries.some(e => e.id === id && e.resolution === undefined))
      return
    this.entries.push({
      id,
      queuedAt: now,
      reason,
      gateSnapshot: { decayMultiplier: gate.decayMultiplier, retrievalNoise: gate.retrievalNoise },
    })
  }

  /** 按 ID 保留（撤销候选）。 */
  retain(id: string, now: number): boolean {
    const e = this.entries.find(x => x.id === id && x.resolution === undefined)
    if (!e)
      return false
    e.resolution = 'retained'
    e.resolvedAt = now
    return true
  }

  /** 真正删除。这是唯一会「消失」的路径，且必然留审计记录。 */
  commit(id: string, now: number): boolean {
    const e = this.entries.find(x => x.id === id && x.resolution === undefined)
    if (!e)
      return false
    e.resolution = 'deleted'
    e.resolvedAt = now
    return true
  }

  pending(): DeletionLedgerEntry[] {
    return this.entries.filter(e => e.resolution === undefined)
  }

  all(): readonly DeletionLedgerEntry[] {
    return this.entries
  }
}
