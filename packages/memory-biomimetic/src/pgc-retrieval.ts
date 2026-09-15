/**
 * PGC 检索门控 — 方向相反、可证伪（pgc-retrieval.ts）。
 *
 * ## 公式
 *
 *     r̂(m,q,s_t) = r(m,q) · (1 + β_τ · s_t) + ε
 *     ε ~ N(0, (σ0 + σ1·c_t)²)
 *
 * 与写入门控相反：写入门控用 `w(m,s_t)` 决定"是否落库"，检索门控用 `r̂` 决定"回忆被放大还是压低"。
 * 论文预测：c_t（strain）升高 ⇒ 陈述性检索准确率下降。要验证这一预测，**噪声必须可复现**——
 * 否则同样的状态两次检索得到不同分数，无法区分"是噪声还是真是生理效应"。
 *
 * ## 可复现性（红线）
 *
 * 噪声用可注入的确定性 PRNG（mulberry32），**禁止 Math.random()**。seed 必须被记录并能在回放时复现。
 * 这就是"可证伪"的工程前提：同一 seed 两次采样序列完全相同；不同 seed 不同。
 */

import type { PgcState4, Tau } from './pgc-state'

// ============================================================================
// 确定性 PRNG（mulberry32）
// ============================================================================

/**
 * pgcMulberry32：mulberry32 算法的确定性实现，32-bit 种子 → [0,1) 均匀序列。
 * 同一 seed ⇒ 同一序列，可被记录与复现。禁止 Math.random()。
 * （命名加 pgc 前缀以区别于 hac.ts 已有的同名工具，避免导出冲突。）
 */
export function pgcMulberry32(seed: number): () => number {
  let a = seed >>> 0
  return function () {
    a |= 0
    a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Box–Muller：用两个均匀样本生成一个标准正态样本。 */
function boxMuller(rng: () => number): number {
  const u1 = Math.max(rng(), Number.EPSILON) // 避免 log(0)
  const u2 = rng()
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2)
}

// ============================================================================
// 参数（第 4 份规范）
// ============================================================================

export const RETRIEVAL_BETA_BY_TAU: Record<Tau, PgcState4> = {
  episodic: { a: 0.10, c: 0.05, d: 0.00, f: 0.00 },
  affective: { a: -0.05, c: 0.20, d: 0.00, f: 0.00 },
  procedural: { a: 0.00, c: -0.10, d: 0.15, f: 0.00 },
  semantic: { a: 0.05, c: 0.10, d: 0.05, f: 0.00 },
}

export const RETRIEVAL_NOISE = { sigma0: 0.02, sigma1: 0.10 }

// ============================================================================
// 检索门控
// ============================================================================

export interface RetrievalGatingInput {
  memory_id: string
  query_id: string
  tau: Tau
  /** 基础相关度 r(m,q) ∈ [0,1]（来自既有检索器）。 */
  base_score: number
  state: PgcState4
  /** 确定性噪声种子（必须记录，供回放复现）。 */
  seed: number
}

export interface RetrievalGatingResult {
  memory_id: string
  query_id: string
  tau: Tau
  base_score: number
  /** 门控后分数 r̂。 */
  gated_score: number
  /** 放大因子 (1 + β_τ·s_t)。 */
  amplification_factor: number
  /** 注入的噪声 ε。 */
  noise: number
  /** 本次噪声标准差 σ = σ0 + σ1·c_t。 */
  sigma: number
  /** 使用的种子（必须为 true 以证明可追溯/可复现）。 */
  random_seed_recorded: true
  /** 记录的种子，回放时原样喂回即可复现。 */
  seed: number
}

/** 内部使用的噪声采样器（可复现）。 */
export interface RetrievalNoiseSampler {
  /** 用给定状态方差采样一个 N(0, σ²) 噪声。 */
  next: (state: PgcState4) => number
  readonly seed: number
  readonly random_seed_recorded: true
}

export function createRetrievalNoiseSampler(seed: number): RetrievalNoiseSampler {
  const rng = pgcMulberry32(seed)
  return {
    seed,
    random_seed_recorded: true as const,
    next(state: PgcState4): number {
      const sigma = RETRIEVAL_NOISE.sigma0 + RETRIEVAL_NOISE.sigma1 * state.c
      return boxMuller(rng) * sigma
    },
  }
}

/**
 * 对单条记忆的相关度做生理门控。
 *
 * 注意：检索门控"方向相反"——这里是把基础分数按生理状态放大/压低，再加可复现噪声。
 * `random_seed_recorded: true` 是硬性要求：论文预测的 c_t 效应只有在噪声可复现时才能被验证。
 */
export function gateRetrieval(input: RetrievalGatingInput): RetrievalGatingResult {
  const beta = RETRIEVAL_BETA_BY_TAU[input.tau]
  const s = input.state
  const dot = beta.a * s.a + beta.c * s.c + beta.d * s.d + beta.f * s.f
  const amplification = 1 + dot
  const sampler = createRetrievalNoiseSampler(input.seed)
  const sigma = RETRIEVAL_NOISE.sigma0 + RETRIEVAL_NOISE.sigma1 * s.c
  const noise = sampler.next(s)
  const gated = input.base_score * amplification + noise
  return {
    memory_id: input.memory_id,
    query_id: input.query_id,
    tau: input.tau,
    base_score: input.base_score,
    gated_score: gated,
    amplification_factor: amplification,
    noise,
    sigma,
    random_seed_recorded: true,
    seed: input.seed,
  }
}

/**
 * 批量门控：对一组 (memory, base_score) 施加同一 τ 与同一状态。
 * 返回的每条结果都带记录种子；回放时用相同 seed 即可逐条复现噪声序列。
 */
export function gateRetrievalBatch(params: {
  query_id: string
  tau: Tau
  state: PgcState4
  seed: number
  candidates: { memory_id: string, base_score: number }[]
}): RetrievalGatingResult[] {
  return params.candidates.map(c => gateRetrieval({
    memory_id: c.memory_id,
    query_id: params.query_id,
    tau: params.tau,
    base_score: c.base_score,
    state: params.state,
    seed: params.seed,
  }))
}
