/**
 * v6 PGC 测试：四维内生状态 + 写入门控 + 检索门控。
 *
 * 这些测试刻意"能真实失败"——尤其是可达性测试，它锁定"第 4 份参数可用"这件事，
 * 防止将来有人把参数改回第 1 份（第 1 份四种 τ 的 w 上限全部 < commit 阈值，
 * 构造性零，任何写入实验效应都不可能被检出）。
 */

import type { Belief } from './belief'
import type { MemoryKind, PgcCandidateWrite, PgcReadContext, PgcV6Params } from './pgc'
import type { PgcState4, Tau } from './pgc-state'

import { describe, expect, it } from 'vitest'

import { applyV6Decision, computeV6CommitmentWeight, computeV6WMaxBounds, contradictionLevelFromSeverity, decideCandidate, DEFAULT_PGC_POLICY_V1, deriveV6CommitVerdict, displayLabelForMemoryKind, PGC_V6_PARAMS_CASE4, PGC_V6_TAU_CASE_ID, TAU_BY_MEMORY_KIND, TAU_DISPLAY_LABEL } from './pgc'
import { gateRetrieval, RETRIEVAL_NOISE } from './pgc-retrieval'
import { createPgcStateIntegrator, DEFAULT_PGC_STATE_SPEC, evaluateStimulus } from './pgc-state'

// ---------------------------------------------------------------------------
// 共享构造
// ---------------------------------------------------------------------------

function baseContext(over: Partial<PgcReadContext> = {}): PgcReadContext {
  return { now: 1_700_000_000_000, last_n_events: [], evidence_records: [], beliefs: [], ...over }
}

const withEvidence: PgcCandidateWrite = {
  memory_write_id: 'mw_1',
  memory_kind: 'long_term',
  candidate_payload: { text: 'the user prefers tea' },
  evidence_ids: ['e1', 'e2', 'e3'],
  proposed_intensity: 1.0,
}

/** 一个 accepted 信念，其 counter-logit 占主导 ⇒ 矛盾严重度达到 high。 */
function highSeverityBelief(): Belief {
  return {
    id: 'b_high',
    proposition: 'user likes coffee',
    scope: 'global',
    confidence: 0.9,
    logit: 2,
    evidenceIds: ['claim_x'],
    counterEvidenceIds: [],
    validFrom: 1,
    validTo: undefined,
    status: 'accepted',
    owner: 'world',
    createdAt: 1,
    updatedAt: 1,
    supportLogit: 1,
    counterLogit: 2, // => severity = 2/3 ≈ 0.667 ≥ 0.66 ⇒ high
  }
}

/** 状态全开（a=c=d=f=... 但 f=0）：最大化 dot，w 应达到 commit。 */
const STATE_ALL_ON: PgcState4 = { a: 1, c: 1, d: 1, f: 0 }
const ZERO_STATE: PgcState4 = { a: 0, c: 0, d: 0, f: 0 }

// ===========================================================================
// 1) 可达性测试（最重要）：第 4 份参数下四种 τ 都能 commit
// ===========================================================================

describe('v6 — 可达性（锁定第 4 份参数可用）', () => {
  const kinds: MemoryKind[] = ['episodic', 'persona', 'skill', 'long_term', 'knowledge_card']

  it('五种 memory_kind 在状态全开时 w 都应 ≥ commit 阈值并产出 commit', () => {
    for (const kind of kinds) {
      const cand: PgcCandidateWrite = { ...withEvidence, memory_kind: kind }
      const ctx = baseContext({ pgc_v6_state: STATE_ALL_ON })
      const r = decideCandidate(cand, ctx, DEFAULT_PGC_POLICY_V1)
      expect(r.pgc_state_snapshot.v6, `kind=${kind} 应有 v6 快照`).toBeDefined()
      expect(r.pgc_state_snapshot.v6!.w).toBeGreaterThanOrEqual(0.55)
      expect(r.decision, `kind=${kind} 在状态全开时应当 commit`).toBe('commit')
    }
  })

  it('computeV6CommitmentWeight 对四种 τ 的 w 上限都为 1.0（区别于第 1 份的构造性零）', () => {
    const taus: Tau[] = ['episodic', 'affective', 'procedural', 'semantic']
    for (const tau of taus) {
      // 找任意一个映射到该 τ 的 kind
      const kind = (Object.keys(TAU_BY_MEMORY_KIND) as MemoryKind[]).find(k => TAU_BY_MEMORY_KIND[k] === tau)!
      const { w } = computeV6CommitmentWeight(kind, STATE_ALL_ON)
      expect(w).toBe(1.0)
    }
  })
})

// ===========================================================================
// 2) 状态演化确定性
// ===========================================================================

describe('v6 — 状态演化确定性', () => {
  const stimulusSeq: PgcState4[] = [
    { a: 0.9, c: 0.2, d: 0.5, f: 0.1 },
    { a: 0.3, c: 0.8, d: 0.1, f: 0.4 },
    { a: 0.0, c: 0.1, d: 0.9, f: 0.7 },
    { a: 0.6, c: 0.5, d: 0.2, f: 0.2 },
  ]

  it('相同初值 + 相同刺激序列 ⇒ 完全相同的 s 轨迹', () => {
    const a = createPgcStateIntegrator()
    const b = createPgcStateIntegrator()
    for (const u of stimulusSeq) {
      const sa = a.step(u)
      const sb = b.step(u)
      expect(sb).toEqual(sa)
    }
  })

  it('evaluateStimulus 是纯函数（相同输入 ⇒ 相同输出）', () => {
    const f1 = evaluateStimulus({ stim_arousal_score: 0.8, stim_strain_score: 0.3 })
    const f2 = evaluateStimulus({ stim_arousal_score: 0.8, stim_strain_score: 0.3 })
    expect(f2).toEqual(f1)
  })
})

// ===========================================================================
// 3) 状态有界
// ===========================================================================

describe('v6 — 状态有界 [0,1]', () => {
  it('任意极端刺激下 s 始终 ∈ [0,1]', () => {
    const integ = createPgcStateIntegrator()
    const extremes: PgcState4[] = [
      { a: 1, c: 1, d: 1, f: 1 },
      { a: 1, c: 0, d: 1, f: 0 },
      { a: 0, c: 1, d: 0, f: 1 },
      { a: 1, c: 1, d: 0, f: 0 },
    ]
    for (let i = 0; i < 50; i++) {
      const s = integ.step(extremes[i % extremes.length])
      for (const v of [s.a, s.c, s.d, s.f]) {
        expect(v).toBeGreaterThanOrEqual(0)
        expect(v).toBeLessThanOrEqual(1)
      }
    }
  })

  it('evaluateStimulus 输出始终 ∈ [0,1]', () => {
    const s = evaluateStimulus({ stim_arousal_score: 999, stim_fatigue_score: -50, idle_and_overload_score: 5 })
    for (const v of [s.a, s.c, s.d, s.f]) {
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThanOrEqual(1)
    }
  })
})

// ===========================================================================
// 4) 疲劳压制：f 升高 ⇒ w 单调下降
// ===========================================================================

describe('v6 — 疲劳压制（f 升高 ⇒ w 单调下降）', () => {
  it('episodic：固定 a=c=d=1，f 从 0 升到 0.9 时 w 非增', () => {
    const fs = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    let prev = Number.POSITIVE_INFINITY
    for (const f of fs) {
      const { w } = computeV6CommitmentWeight('episodic', { a: 1, c: 1, d: 1, f })
      expect(w).toBeLessThanOrEqual(prev)
      prev = w
    }
  })

  it('semantic：同样单调下降', () => {
    const fs = [0, 0.3, 0.6, 0.9]
    let prev = Number.POSITIVE_INFINITY
    for (const f of fs) {
      const { w } = computeV6CommitmentWeight('long_term', { a: 1, c: 1, d: 1, f })
      expect(w).toBeLessThanOrEqual(prev)
      prev = w
    }
  })
})

// ===========================================================================
// 5) 门控顺序：high 矛盾优先于 commit（即使 w=1）
// ===========================================================================

describe('v6 — 门控顺序', () => {
  it('applyV6Decision：w=1 且 high 矛盾 ⇒ reject（而非 commit）', () => {
    const r = applyV6Decision(1.0, ZERO_STATE, 'high')
    expect(r.decision).toBe('reject')
    expect(r.reason_codes).toContain('contradiction_detected')
  })

  it('集成：状态全开(w=1) 但命中 high 严重度信念 ⇒ 仍 reject', () => {
    const cand: PgcCandidateWrite = {
      ...withEvidence,
      memory_kind: 'long_term',
      claim_ids: ['claim_x'],
    }
    const ctx = baseContext({ pgc_v6_state: STATE_ALL_ON, beliefs: [highSeverityBelief()] })
    const r = decideCandidate(cand, ctx, DEFAULT_PGC_POLICY_V1)
    expect(contradictionLevelFromSeverity(2 / 3)).toBe('high')
    expect(r.decision).toBe('reject')
  })

  it('w=1 且无矛盾 ⇒ commit（对照：说明 reject 确由矛盾触发）', () => {
    const r = applyV6Decision(1.0, ZERO_STATE, 'low')
    expect(r.decision).toBe('commit')
  })
})

// ===========================================================================
// 6) defer：f > 0.70 且 w ≥ 0.45 ⇒ defer 而非 commit
// ===========================================================================

describe('v6 — defer 分支', () => {
  it('f=0.8 且 w=0.5 ⇒ defer（而非 commit）', () => {
    const r = applyV6Decision(0.5, { a: 0, c: 0, d: 0, f: 0.8 }, 'low')
    expect(r.decision).toBe('defer')
    expect(r.fatigue_deferred).toBe(true)
  })

  it('f=0.6（未超 0.70）且 w=0.5 ⇒ throttle（而非 defer/commit）', () => {
    const r = applyV6Decision(0.5, { a: 0, c: 0, d: 0, f: 0.6 }, 'low')
    expect(r.decision).toBe('throttle')
  })

  it('f=0.8 但 w=0.2（低于 defer 阈值）⇒ reject（非 defer）', () => {
    const r = applyV6Decision(0.2, { a: 0, c: 0, d: 0, f: 0.8 }, 'low')
    expect(r.decision).toBe('reject')
  })

  // 说明（不掩盖）：在给定 ρ0/κ 参数下，状态全开时 (1-κ·f) 在 f>0.70 已 ≤0.125，
  // 使 w_raw ≤ 0.19，永远到不了 defer 的 w≥0.45——该分支在真实公式下数学不可达，
  // 但分支逻辑本身正确，以上对决策分发函数用构造输入做了真实测试。
})

// ===========================================================================
// 7) 检索噪声可复现 + 8) σ 随 c_t 增大
// ===========================================================================

describe('v6 — 检索门控噪声', () => {
  const baseState: PgcState4 = { a: 0.5, c: 0.3, d: 0.4, f: 0.2 }

  it('同 seed 两次采样序列完全相同（可回放前提）', () => {
    const p = { memory_id: 'm1', query_id: 'q1', tau: 'semantic' as Tau, base_score: 0.7, state: baseState, seed: 12345 }
    const a = gateRetrieval(p)
    const b = gateRetrieval(p)
    expect(b.noise).toBe(a.noise)
    expect(b.gated_score).toBe(a.gated_score)
    expect(b.random_seed_recorded).toBe(true)
    expect(b.seed).toBe(12345)
  })

  it('不同 seed ⇒ 噪声不同', () => {
    const p1 = { memory_id: 'm1', query_id: 'q1', tau: 'semantic' as Tau, base_score: 0.7, state: baseState, seed: 1 }
    const p2 = { memory_id: 'm1', query_id: 'q1', tau: 'semantic' as Tau, base_score: 0.7, state: baseState, seed: 2 }
    const a = gateRetrieval(p1)
    const b = gateRetrieval(p2)
    expect(b.noise).not.toBe(a.noise)
  })

  it('σ 随 c_t 增大：c 高时噪声标准差更大', () => {
    const lowC: PgcState4 = { a: 0.5, c: 0.1, d: 0.4, f: 0.2 }
    const highC: PgcState4 = { a: 0.5, c: 0.9, d: 0.4, f: 0.2 }
    const a = gateRetrieval({ memory_id: 'm1', query_id: 'q1', tau: 'semantic', base_score: 0.7, state: lowC, seed: 7 })
    const b = gateRetrieval({ memory_id: 'm1', query_id: 'q1', tau: 'semantic', base_score: 0.7, state: highC, seed: 7 })
    expect(b.sigma).toBeGreaterThan(a.sigma)
    // 直接验证 σ 公式
    expect(a.sigma).toBeCloseTo(RETRIEVAL_NOISE.sigma0 + RETRIEVAL_NOISE.sigma1 * 0.1, 10)
    expect(b.sigma).toBeCloseTo(RETRIEVAL_NOISE.sigma0 + RETRIEVAL_NOISE.sigma1 * 0.9, 10)
  })
})

// ===========================================================================
// 9) τ 映射完整性（5 个 memory_kind 全部有映射，特别是 skill）
// ===========================================================================

describe('v6 — τ 映射完整性', () => {
  it('5 个 memory_kind 全部映射到合法 τ', () => {
    const kinds: MemoryKind[] = ['long_term', 'persona', 'skill', 'episodic', 'knowledge_card']
    const valid: Tau[] = ['episodic', 'affective', 'procedural', 'semantic']
    for (const k of kinds) {
      const tau = TAU_BY_MEMORY_KIND[k]
      expect(valid).toContain(tau)
    }
  })

  it('skill 必须被覆盖（作者原映射表漏掉了它）⇒ procedural', () => {
    expect(TAU_BY_MEMORY_KIND.skill).toBe('procedural')
  })

  it('persona ⇒ affective，knowledge_card ⇒ semantic', () => {
    expect(TAU_BY_MEMORY_KIND.persona).toBe('affective')
    expect(TAU_BY_MEMORY_KIND.knowledge_card).toBe('semantic')
  })
})

// ===========================================================================
// 10) 向后兼容：不传状态 ⇒ 行为与改动前一致（旧纯证据阈值策略）
// ===========================================================================

describe('v6 — 向后兼容（无状态走旧路径）', () => {
  it('不传 pgc_v6_state ⇒ 快照不含 v6，决策走旧证据阈值策略', () => {
    const noEv = decideCandidate({ ...withEvidence, evidence_ids: [] }, baseContext(), DEFAULT_PGC_POLICY_V1)
    expect(noEv.pgc_state_snapshot.v6).toBeUndefined()
    expect(noEv.decision).toBe('reject')

    const ok = decideCandidate(withEvidence, baseContext(), DEFAULT_PGC_POLICY_V1)
    expect(ok.pgc_state_snapshot.v6).toBeUndefined()
    expect(ok.decision).toBe('commit')
  })

  it('旧路径下矛盾仍被检出（与改动前一致）', () => {
    const cand: PgcCandidateWrite = { ...withEvidence, claim_ids: ['claim_x'] }
    const ctx = baseContext({ beliefs: [highSeverityBelief()] })
    const r = decideCandidate(cand, ctx, DEFAULT_PGC_POLICY_V1)
    expect(r.pgc_state_snapshot.v6).toBeUndefined()
    expect(r.decision).toBe('reject')
  })
})

// ===========================================================================
// 11) replay minimums：快照含 computed_w 与 pgc_policy_version
// ===========================================================================

describe('v6 — replay minimums', () => {
  it('v6 快照携带 w(computed_w) 与 pgc_policy_version', () => {
    const r = decideCandidate(withEvidence, baseContext({ pgc_v6_state: STATE_ALL_ON }), DEFAULT_PGC_POLICY_V1)
    expect(r.pgc_state_snapshot.pgc_policy_version).toBe('pgc_policy_v1')
    expect(r.pgc_state_snapshot.v6).toBeDefined()
    expect(typeof r.pgc_state_snapshot.v6!.w).toBe('number')
    expect(typeof r.pgc_state_snapshot.v6!.w_prime).toBe('number')
    expect(r.pgc_state_snapshot.v6!.tau).toBe('semantic')
  })
})

// ===========================================================================
// 12) 离线巩固触发
// ===========================================================================

describe('v6 — 离线巩固触发', () => {
  it('f > 0.72 且 idle > 300s ⇒ 触发并复位到基线', () => {
    const integ = createPgcStateIntegrator({ a: 0.5, c: 0.5, d: 0.5, f: 0.8 })
    const triggered = integ.maybeTriggerOfflineConsolidation(400)
    expect(triggered).toBe(true)
    expect(integ.state.f).toBe(DEFAULT_PGC_STATE_SPEC.s_star.f)
  })

  it('f 高但 idle 不足 ⇒ 不触发', () => {
    const integ = createPgcStateIntegrator({ a: 0.5, c: 0.5, d: 0.5, f: 0.8 })
    expect(integ.maybeTriggerOfflineConsolidation(100)).toBe(false)
  })

  it('idle 充足但 f 未超阈值 ⇒ 不触发', () => {
    const integ = createPgcStateIntegrator({ a: 0.5, c: 0.5, d: 0.5, f: 0.5 })
    expect(integ.maybeTriggerOfflineConsolidation(400)).toBe(false)
  })
})

// ===========================================================================
// 13) 闭式 w_max 上界（构造性零显式化）
// ===========================================================================

/** 第 1 份参数（构造性零）：只作测试 fixture，不进生产路径。 */
const PGC_V6_PARAMS_CASE1: PgcV6Params = {
  rho0_by_tau: { episodic: 0.22, affective: 0.26, procedural: 0.24, semantic: 0.20 },
  kappa: 0.85,
  alpha_by_tau: {
    episodic: { a: 0.95, c: -0.10, d: 0.05, f: 0 },
    affective: { a: 0.10, c: 0.95, d: 0, f: -0.05 },
    procedural: { a: 0, c: -0.05, d: 0.95, f: 0 },
    semantic: { a: 0.15, c: -0.05, d: 0, f: 0.05 },
  },
}

/** 暴力扫描（步长 0.02，四维）求 w_max，与闭式结果交叉验证。 */
function bruteForceWMax(params: PgcV6Params, tau: Tau): number {
  const rho0 = params.rho0_by_tau[tau]
  const al = params.alpha_by_tau[tau]
  const kappa = params.kappa
  let max = -Infinity
  for (let a = 0; a <= 1.0001; a += 0.02) {
    for (let c = 0; c <= 1.0001; c += 0.02) {
      for (let d = 0; d <= 1.0001; d += 0.02) {
        for (let f = 0; f <= 1.0001; f += 0.02) {
          const dot = al.a * a + al.c * c + al.d * d + al.f * f
          const w = rho0 * (1 + dot) * (1 - kappa * f)
          if (w > max)
            max = w
        }
      }
    }
  }
  return Math.min(1, Math.max(0, max))
}

/** 固定 f，暴力扫描 a/c/d 三维，校验「给定疲劳下的上界」是否真的成立。 */
function bruteForceWMaxAtF(params: PgcV6Params, tau: Tau, f: number): number {
  const rho0 = params.rho0_by_tau[tau]
  const al = params.alpha_by_tau[tau]
  const kappa = params.kappa
  let max = -Infinity
  for (let a = 0; a <= 1.0001; a += 0.02) {
    for (let c = 0; c <= 1.0001; c += 0.02) {
      for (let d = 0; d <= 1.0001; d += 0.02) {
        const w = rho0 * (1 + al.a * a + al.c * c + al.d * d + al.f * f) * (1 - kappa * f)
        if (w > max)
          max = w
      }
    }
  }
  return Math.min(1, Math.max(0, max))
}

// ===========================================================================
// w_max_at_f 必须在整个 f∈[0,1] 上都是上界（含 f > 1/κ 的负乘子区）
// ===========================================================================

describe('v6 — w_max_at_f 是全 f 区间上的上界', () => {
  const taus: Tau[] = ['episodic', 'affective', 'procedural', 'semantic']

  it('case4（κ=1.25 ⇒ 1/κ=0.8）在 f>0.8 的负乘子区仍不低估', () => {
    for (const tau of taus) {
      for (const f of [0, 0.5, 0.7, 0.8, 0.85, 0.9, 1.0]) {
        const { w_max_at_f } = computeV6WMaxBounds(tau, PGC_V6_PARAMS_CASE4, f)
        expect(w_max_at_f!).toBeGreaterThanOrEqual(bruteForceWMaxAtF(PGC_V6_PARAMS_CASE4, tau, f) - 1e-9)
      }
    }
  })

  it('case1 在全区间不低估', () => {
    for (const tau of taus) {
      for (const f of [0, 0.5, 0.7, 0.8, 0.9, 1.0]) {
        const { w_max_at_f } = computeV6WMaxBounds(tau, PGC_V6_PARAMS_CASE1, f)
        expect(w_max_at_f!).toBeGreaterThanOrEqual(bruteForceWMaxAtF(PGC_V6_PARAMS_CASE1, tau, f) - 1e-9)
      }
    }
  })

  // 回归锁：负乘子区若退回「恒取 Σmax」，下面会低估到 0（真上界 0.0199~0.0875）。
  // 该区间正是高疲劳诊断区，上界失效等于守卫自己失效且无人察觉。
  it('负乘子区（f > 1/κ）：只取 Σmax 会低估 —— 合成参数回归锁', () => {
    const synthetic: PgcV6Params = {
      rho0_by_tau: { episodic: 0.7, affective: 0.7, procedural: 0.7, semantic: 0.7 },
      kappa: 1.25,
      alpha_by_tau: {
        episodic: { a: -1.2, c: 0, d: 0, f: -0.3 },
        affective: { a: -1.2, c: 0, d: 0, f: -0.3 },
        procedural: { a: -1.2, c: 0, d: 0, f: -0.3 },
        semantic: { a: -1.2, c: 0, d: 0, f: -0.3 },
      },
    }
    for (const f of [0.85, 0.9, 1.0]) {
      const { w_max_at_f } = computeV6WMaxBounds('episodic', synthetic, f)
      const brute = bruteForceWMaxAtF(synthetic, 'episodic', f)
      expect(brute).toBeGreaterThan(0)
      expect(w_max_at_f!).toBeCloseTo(brute, 3)
    }
  })
})

describe('v6 — 闭式 w_max 与暴力扫描一致', () => {
  const cases: { name: string, params: PgcV6Params, expected: Record<Tau, number> }[] = [
    { name: 'case1', params: PGC_V6_PARAMS_CASE1, expected: { episodic: 0.44, affective: 0.533, procedural: 0.468, semantic: 0.23 } },
    { name: 'case4', params: PGC_V6_PARAMS_CASE4, expected: { episodic: 1.0, affective: 1.0, procedural: 1.0, semantic: 1.0 } },
  ]
  const taus: Tau[] = ['episodic', 'affective', 'procedural', 'semantic']

  for (const cs of cases) {
    for (const tau of taus) {
      it(`${cs.name} ${tau}: 闭式 w_max == 文档值(${cs.expected[tau]}) 且 == 暴力扫描`, () => {
        const { w_max_global } = computeV6WMaxBounds(tau, cs.params)
        expect(w_max_global).toBeCloseTo(cs.expected[tau], 4)
        expect(w_max_global).toBeCloseTo(bruteForceWMax(cs.params, tau), 6)
      })
    }
  }
})

// ===========================================================================
// 14) 构造性零锁死：基线 1 永远不可 commit
// ===========================================================================

describe('v6 — 基线 1 锁死（w_max_below_theta 必触发）', () => {
  const taus: Tau[] = ['episodic', 'affective', 'procedural', 'semantic']

  it('四种 τ 全部 commit_possible=false 且 commit_reason=w_max_below_theta', () => {
    for (const tau of taus) {
      const { w_max_global } = computeV6WMaxBounds(tau, PGC_V6_PARAMS_CASE1)
      expect(w_max_global).toBeLessThan(0.55)
      const { commit_possible, commit_reason } = deriveV6CommitVerdict({
        w_max_global,
        contradiction_level: 'low',
        evidence_sufficient: true,
        decision: 'commit',
        w: 1,
      })
      expect(commit_possible).toBe(false)
      expect(commit_reason).toBe('w_max_below_theta')
    }
  })
})

// ===========================================================================
// 15) 基线 4 可达 + f=0.70 的 defer 不可达（可观测）
// ===========================================================================

describe('v6 — 基线 4 可达性与 defer 不可达', () => {
  it('基线 4，f=0、a=c=d=1：commit_possible=true、commit_reason=committed', () => {
    const cand: PgcCandidateWrite = { ...withEvidence, memory_kind: 'long_term' }
    const ctx = baseContext({ pgc_v6_state: { a: 1, c: 1, d: 1, f: 0 } })
    const r = decideCandidate(cand, ctx, DEFAULT_PGC_POLICY_V1)
    expect(r.pgc_state_snapshot.v6!.commit_possible).toBe(true)
    expect(r.pgc_state_snapshot.v6!.commit_reason).toBe('committed')
  })

  it('基线 4，f=0.70，episodic 的 w_max_at_f ≈ 0.1628 且 < defer 门槛 0.45（defer 不可达）', () => {
    const { w_max_at_f } = computeV6WMaxBounds('episodic', PGC_V6_PARAMS_CASE4, 0.70)
    expect(w_max_at_f).not.toBeNull()
    expect(w_max_at_f!).toBeCloseTo(0.1628, 4)
    expect(w_max_at_f!).toBeLessThan(0.45)
  })

  it('tau_case_id === 4 被记录', () => {
    const cand: PgcCandidateWrite = { ...withEvidence, memory_kind: 'long_term' }
    const ctx = baseContext({ pgc_v6_state: { a: 1, c: 1, d: 1, f: 0 } })
    const r = decideCandidate(cand, ctx, DEFAULT_PGC_POLICY_V1)
    expect(r.pgc_state_snapshot.v6!.tau).toBe('semantic')
    expect(PGC_V6_TAU_CASE_ID).toBe(4)
  })
})

// ===========================================================================
// 16) τ 展示标签必须是派生，而不是第二张手写表
// ===========================================================================

describe('v6 — 展示标签由 TAU_BY_MEMORY_KIND 派生', () => {
  const allKinds = ['long_term', 'persona', 'skill', 'episodic', 'knowledge_card'] as const

  it('恒等于 RENAME[TAU_BY_MEMORY_KIND[kind]]（手写第二张表即失败）', () => {
    for (const kind of allKinds)
      expect(displayLabelForMemoryKind(kind)).toBe(TAU_DISPLAY_LABEL[TAU_BY_MEMORY_KIND[kind]])
  })

  it('5 个 memory_kind 压缩到 4 个标签，且 long_term 与 knowledge_card 同类', () => {
    const labels = allKinds.map(k => displayLabelForMemoryKind(k))
    expect(new Set(labels).size).toBe(4)
    // 这条多对一是 v1 的 4 值重定义会毁掉的关系，必须锁住
    expect(displayLabelForMemoryKind('long_term')).toBe('knowledge')
    expect(displayLabelForMemoryKind('knowledge_card')).toBe('knowledge')
  })

  it('展示标签与 τ 一一对应（4 个 τ ↔ 4 个标签）', () => {
    const taus = ['episodic', 'affective', 'procedural', 'semantic'] as const
    expect(Object.keys(TAU_DISPLAY_LABEL).sort()).toEqual([...taus].sort())
    expect(new Set(Object.values(TAU_DISPLAY_LABEL)).size).toBe(4)
  })
})
