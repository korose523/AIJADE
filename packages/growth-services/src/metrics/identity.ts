/**
 * §5.4 (新增) — Identity / persona-constitution metrics.
 *
 * These complement the six memory metrics so that the CDI (identity-constraint)
 * ablation becomes falsifiable. The original pilot could only watch CDI erosions
 * on Growth Coherence, which is itself entangled with DGM; with these metrics the
 * CDI treatment has a clean, dedicated target.
 *
 * All three are pure functions over simple counts derived from the *genuinely
 * committed* memory set (produced by `PolicyStorage`), never from a config flag.
 * Invariants: no global state, no `Date.now()`, no `Math.random()`.
 */

import type { MemoryMeta } from '../pilot/memory-policies'

import { CORE_PERSONA_ROLES, DESTABILIZING_ROLES } from '../pilot/memory-policies'

/** Raw counts needed to compute the identity metrics. */
export interface IdentityCounts {
  /** Total committed memory entries. */
  committedTotal: number
  /** Committed entries whose role is identity-destabilising (high-emotion, low-fact). */
  destabilizing: number
  /** Committed entries belonging to the persona core (constitution / role layer). */
  corePersona: number
  /** Committed rare-skill (low-frequency, high-value) entries. */
  retainedSkills: number
  /** Total rare-skill statements the dataset ever presented. */
  totalSkills: number
}

/** Derive the counts from the committed memory set. Pure. */
export function countIdentity(committed: Map<string, MemoryMeta>): IdentityCounts {
  let destabilizing = 0
  let corePersona = 0
  let retainedSkills = 0
  for (const m of committed.values()) {
    if (DESTABILIZING_ROLES.has(m.role))
      destabilizing++
    if (CORE_PERSONA_ROLES.has(m.role))
      corePersona++
    if (m.role === 'lowfreq_highvalue')
      retainedSkills++
  }
  return {
    committedTotal: committed.size,
    destabilizing,
    corePersona,
    retainedSkills,
    totalSkills: 0, // filled by the caller (dataset total, not derivable from the set)
  }
}

/**
 * Identity Drift (ID) — 身份漂移度.
 *
 * 公式: ID = destabilizing / max(1, committedTotal).
 * 口径: 已固化记忆中"越界漂移"内容（高情绪低事实）所占比例；比例越高，人格越被
 *       噪声/情绪化内容侵蚀。合法演化（如 evidence-backed 的偏好更新、双图保留的
 *       矛盾证据）不计入此处，因此本指标可区分"受约束的合法演化"与"越界漂移"。
 * 边界: committedTotal = 0 → 0。
 */
export function identityDrift(c: IdentityCounts): number {
  if (c.committedTotal <= 0)
    return 0
  return c.destabilizing / c.committedTotal
}

/**
 * Core Stability (CS) — 人格核心稳定度.
 *
 * 公式: CS = max(0, 1 − destabilizing / max(1, corePersona)).
 * 口径: 宪法层/角色层核心人格在记忆中的"未受漂移污染"比例。分母取已提交的核心人格
 *       条目数，分子为其中被漂移内容相对稀释的程度。CDI 开启时漂移写入被拦截 → CS=1；
 *       CDI 关闭时漂移内容进入 → CS<1。与 Identity Drift 分母不同，二者为互补但独立的
 *       两个口径。
 * 边界: corePersona = 0 → 1（无核心人格条目时不做稀释判定）。
 */
export function coreStability(c: IdentityCounts): number {
  if (c.corePersona <= 0)
    return 1
  return Math.max(0, 1 - c.destabilizing / c.corePersona)
}

/**
 * Skill Retention (SR) — 技能/迁移留存度 (可选量化项).
 *
 * 公式: SR = retainedSkills / max(1, totalSkills).
 * 口径: 低频高价值（罕见但可复用的技能/知识）在最终记忆中的留存比例。该指标可区分
 *       会过早淘汰罕见技能的窗口/预算策略（如滑动窗口丢弃早期罕见技能）与能跨时间
 *       保留它们的策略（全写/重要性/HAC）。是"迁移增益"的可量化近似。
 * 边界: totalSkills = 0 → 0。
 */
export function skillRetention(c: IdentityCounts): number {
  if (c.totalSkills <= 0)
    return 0
  return c.retainedSkills / c.totalSkills
}
