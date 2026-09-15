/**
 * v6 PGC 测试：四维内生状态 + 写入门控 + 检索门控。
 *
 * 这些测试刻意"能真实失败"——尤其是可达性测试，它锁定"第 4 份参数可用"这件事，
 * 防止将来有人把参数改回第 1 份（第 1 份四种 τ 的 w 上限全部 < commit 阈值，
 * 构造性零，任何写入实验效应都不可能被检出）。
 */

import type { Belief } from './belief'
import type { MemoryKind, PgcCandidateWrite, PgcReadContext } from './pgc'
import type { PgcState4, Tau } from './pgc-state'

import { describe, expect, it } from 'vitest'

import {
  applyV6Decision,
  computeV6CommitmentWeight,
  contradictionLevelFromSeverity,
  decideCandidate,
  DEFAULT_PGC_POLICY_V1,
  TAU_BY_MEMORY_KIND,
} from './pgc'
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
