import type { Belief } from './belief'
import type { PgcCandidateWrite, PgcReadContext } from './pgc'

import { describe, expect, it } from 'vitest'

import {
  decideCandidate,
  decidePgc,
  DEFAULT_PGC_POLICY_V1,
  NEUTRAL_PGC_POLICY,
  resolvePgcPolicy,
} from './pgc'
import { isNeutralGate } from './plasticity'

/** 一个 accepted 信念：claim_x 是其证据，且带较高 counter-logit 使矛盾严重度达到 0.5。 */
function acceptedBelief(): Belief {
  return {
    id: 'b_user_likes_coffee',
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
    counterLogit: 1,
  }
}

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

const noEvidence: PgcCandidateWrite = {
  memory_write_id: 'mw_0',
  memory_kind: 'long_term',
  candidate_payload: { text: 'unsupported claim' },
  evidence_ids: [],
  proposed_intensity: 1.0,
}

describe('pGC — 无证据写入', () => {
  it('evidence_ids 为空 ⇒ low_evidence + reject（默认策略 low_evidence_action=reject）', () => {
    const r = decideCandidate(noEvidence, baseContext(), DEFAULT_PGC_POLICY_V1)
    expect(r.reason_codes).toContain('low_evidence')
    expect(r.decision).toBe('reject')
  })

  it('evidence_ids 数量低于 min_evidence_count ⇒ reject', () => {
    const policy = { ...DEFAULT_PGC_POLICY_V1, min_evidence_count: 2 }
    const r = decideCandidate({ ...withEvidence, evidence_ids: ['e1'] }, baseContext(), policy)
    expect(r.reason_codes).toContain('low_evidence')
    expect(r.decision).toBe('reject')
  })
})

describe('pGC — 充分证据提交', () => {
  it('达到 sufficient_evidence_count 且无矛盾 ⇒ commit + sufficient_evidence', () => {
    const r = decideCandidate(withEvidence, baseContext(), DEFAULT_PGC_POLICY_V1)
    expect(r.decision).toBe('commit')
    expect(r.reason_codes).toContain('sufficient_evidence')
    expect(r.final_intensity).toBeGreaterThan(0)
  })

  it('final_intensity 落在策略界内（沿用有界精神）', () => {
    const r = decideCandidate({ ...withEvidence, proposed_intensity: 99 }, baseContext(), DEFAULT_PGC_POLICY_V1)
    expect(r.final_intensity).toBeLessThanOrEqual(DEFAULT_PGC_POLICY_V1.intensity_bounds.max)
    expect(r.final_intensity).toBeGreaterThanOrEqual(DEFAULT_PGC_POLICY_V1.intensity_bounds.min)
  })
})

describe('pGC — 矛盾检测', () => {
  it('候选 claim 命中 accepted 信念 ⇒ contradiction_detected + 高严重度 + reject', () => {
    const belief = acceptedBelief()
    const cand: PgcCandidateWrite = {
      memory_write_id: 'mw_c',
      memory_kind: 'long_term',
      candidate_payload: { text: 'user hates coffee' },
      evidence_ids: ['e1', 'e2', 'e3'],
      proposed_intensity: 1.0,
      claim_ids: ['claim_x'],
    }
    const ctx = baseContext({ beliefs: [belief] })
    const r = decideCandidate(cand, ctx, DEFAULT_PGC_POLICY_V1)
    expect(r.reason_codes).toContain('contradiction_detected')
    expect(r.decision).toBe('reject')
    const full = decidePgc({ session_id: 's', trace_id: 't', candidate_memory_writes: [cand], pgc_read_context: ctx, pgc_policy_version: 'pgc_policy_v1' })
    expect(full.contradiction_report.severity).toBe('high')
    expect(full.contradiction_report.conflicting_evidence_ids).toContain('claim_x')
  })
})

describe('pGC — persona 漂移风险', () => {
  it('persona 类且 intensity 过高 ⇒ persona_shift_risk + reject', () => {
    const cand: PgcCandidateWrite = {
      memory_write_id: 'mw_p',
      memory_kind: 'persona',
      candidate_payload: { persona: 'rude' },
      evidence_ids: ['e1', 'e2', 'e3'],
      proposed_intensity: 2.5,
    }
    const r = decideCandidate(cand, baseContext(), DEFAULT_PGC_POLICY_V1)
    expect(r.reason_codes).toContain('persona_shift_risk')
    expect(r.decision).toBe('reject')
  })
})

describe('pGC — 策略参数化（消融：只改策略不改代码）', () => {
  it('同一输入，中性策略把 low_evidence 处置从 reject 改为 throttle', () => {
    const strict = decideCandidate(noEvidence, baseContext(), DEFAULT_PGC_POLICY_V1)
    const neutral = decideCandidate(noEvidence, baseContext(), NEUTRAL_PGC_POLICY)
    expect(strict.decision).toBe('reject')
    expect(neutral.decision).toBe('throttle')
  })

  it('中性策略把矛盾阈值推到 1.0，因此同输入矛盾不再判高严重度', () => {
    const belief = acceptedBelief()
    const cand: PgcCandidateWrite = {
      memory_write_id: 'mw_c',
      memory_kind: 'long_term',
      candidate_payload: {},
      evidence_ids: ['e1', 'e2', 'e3'],
      proposed_intensity: 1.0,
      claim_ids: ['claim_x'],
    }
    const ctx = baseContext({ beliefs: [belief] })
    const neutral = decidePgc({ session_id: 's', trace_id: 't', candidate_memory_writes: [cand], pgc_read_context: ctx, pgc_policy_version: 'pgc_policy_neutral' })
    expect(neutral.contradiction_report.severity).toBe('low')
  })

  it('未知策略版本 ⇒ 抛错（强制注册，避免静默回退到错误策略）', () => {
    expect(() => resolvePgcPolicy('does_not_exist')).toThrow()
  })
})

describe('pGC — 复用 plasticity.ts 原语', () => {
  it('无显著性时，状态快照的 plasticity 分量为中性（呼应项目「生理保持中性」结论）', () => {
    const r = decideCandidate(withEvidence, baseContext(), DEFAULT_PGC_POLICY_V1)
    expect(isNeutralGate(r.pgc_state_snapshot.components.plasticity)).toBe(true)
  })

  it('带内容显著性时，consolidationGain 调制 final_intensity（复用 deriveGateFromContent）', () => {
    const plain = decideCandidate(withEvidence, baseContext(), DEFAULT_PGC_POLICY_V1)
    const salient = decideCandidate({ ...withEvidence, salience: { salience: 0.9, socialSalience: 0.5, novelty: 0.3 } }, baseContext(), DEFAULT_PGC_POLICY_V1)
    // 显著性推动 consolidationGain>1，因此 final_intensity 应高于中性情形（同 proposed_intensity）。
    expect(salient.final_intensity).toBeGreaterThan(plain.final_intensity)
    expect(salient.pgc_state_snapshot.components.plasticity.consolidationGain).toBeGreaterThan(1)
  })
})

describe('pGC — 确定性', () => {
  it('相同输入 ⇒ 完全相同的 write_plan（可复现/回放前提）', () => {
    const a = decidePgc({ session_id: 's', trace_id: 't', candidate_memory_writes: [withEvidence, noEvidence], pgc_read_context: baseContext(), pgc_policy_version: 'pgc_policy_v1' })
    const b = decidePgc({ session_id: 's', trace_id: 't', candidate_memory_writes: [withEvidence, noEvidence], pgc_read_context: baseContext(), pgc_policy_version: 'pgc_policy_v1' })
    expect(b.write_plan).toEqual(a.write_plan)
    expect(b.contradiction_report).toEqual(a.contradiction_report)
  })
})
