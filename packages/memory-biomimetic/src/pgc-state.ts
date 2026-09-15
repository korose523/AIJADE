/**
 * PGC 四维内生状态积分器 — v6 的核心动力学（之前只停留在文档规范，本文件首次落成真实代码）。
 *
 * ## 为什么存在
 *
 * 论文方法章声称存在"四维内生状态 s_t = [a, c, d, f]"（arousal / strain / drive / fatigue）、
 * 状态演化方程、写入门控 `w(m, s_t)` 与检索门控噪声。上一轮 `pgc.ts` 只是纯证据阈值策略，
 * 这些机制在代码里零实现。本文件补上状态层，让 `pgc.ts` 与 `pgc-retrieval.ts` 有真实状态可门控。
 *
 * ## 演化方程（欧拉积分）
 *
 *     s_{t+1} = clip( s_t + Δt · [ -Λ(s_t - s*) + W·u_t + B·σ(s_t) ] )
 *
 * - `s*` 基线（homeostasis 平衡点）
 * - `Λ` 对角恢复速率（把状态拉回基线）
 * - `W` 驱动矩阵（刺激 u_t 推高对应状态维）
 * - `B` 交互抑制矩阵（允许负值，是非单调响应的来源）
 * - `σ(s)` 逐元素 logistic 饱和函数
 *
 * 所有参数取"第 4 份规范"（已被数值证明：四种 τ 的 w 上限均为 1.0，能 commit；
 * 第 1 份四种 τ 的 w 上限全部 < commit 阈值，构造性零，永远无法 commit）。
 */

// ============================================================================
// 类型
// ============================================================================

/** 四维状态向量，每维 ∈ [0,1]。 */
export interface PgcState4 { a: number, c: number, d: number, f: number }

/** 四维的轴顺序，矩阵按此索引：a=0, c=1, d=2, f=3。 */
export const STATE_DIMS = ['a', 'c', 'd', 'f'] as const
export type PgcStateDim = (typeof STATE_DIMS)[number]

/** 四种生理型 τ（注意与 memory_kind 的 5 对 4 映射在 pgc.ts 里处理）。 */
export type Tau = 'episodic' | 'affective' | 'procedural' | 'semantic'

// ============================================================================
// 默认规格（第 4 份规范）
// ============================================================================

export interface PgcStateSpec {
  /** 基线（homeostasis 平衡点）。 */
  s_star: PgcState4
  /** 对角恢复速率（拉回基线）。 */
  Lambda: PgcState4
  /** 驱动矩阵 4×4：行=状态维 [a,c,d,f]，列=刺激维 [a,c,d,f]。 */
  W: number[][]
  /** 交互抑制矩阵 4×4：B_ii = 0，允许负值（非单调响应的来源）。 */
  B: number[][]
  /** 饱和函数 σ 的参数。 */
  sigma: { k: number, x0: number }
  /** 默认步长（秒）。 */
  dt: number
  /** 离线巩固触发条件。 */
  offline_consolidation: { fatigue_threshold: number, idle_seconds: number }
}

export const DEFAULT_PGC_STATE_SPEC: PgcStateSpec = {
  s_star: { a: 0.12, c: 0.10, d: 0.08, f: 0.05 },
  Lambda: { a: 0.22, c: 0.18, d: 0.20, f: 0.26 },
  W: [
    [0.90, 0.05, 0.00, 0.00],
    [0.10, 0.85, 0.05, 0.00],
    [0.00, 0.10, 0.80, 0.05],
    [0.00, 0.00, 0.10, 0.75],
  ],
  B: [
    [0.00, 0.00, 0.10, -0.35],
    [-0.15, 0.00, -0.28, 0.10],
    [0.08, -0.25, 0.00, -0.40],
    [0.00, 0.12, 0.05, 0.00],
  ],
  sigma: { k: 10.0, x0: 0.5 },
  dt: 1.0,
  offline_consolidation: { fatigue_threshold: 0.72, idle_seconds: 300 },
}

// ============================================================================
// 基础工具
// ============================================================================

function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x
}

/** 逐元素 logistic：σ(x) = 1 / (1 + exp(-k·(x - x0)))。 */
export function logistic(x: number, k: number, x0: number): number {
  return 1 / (1 + Math.exp(-k * (x - x0)))
}

/** 把 PgcState4 按 STATE_DIMS 顺序投影成数值向量。 */
function toVec(s: PgcState4): number[] {
  return [s.a, s.c, s.d, s.f]
}

/** 从数值向量还原 PgcState4（并 clip 到 [0,1]）。 */
function fromVec(v: number[]): PgcState4 {
  return { a: clamp01(v[0]), c: clamp01(v[1]), d: clamp01(v[2]), f: clamp01(v[3]) }
}

/** 4×4 矩阵 × 4 向量。 */
function matVec(M: number[][], u: number[]): number[] {
  const out = [0, 0, 0, 0]
  for (let i = 0; i < 4; i++) {
    let acc = 0
    for (let j = 0; j < 4; j++)
      acc += M[i][j] * u[j]
    out[i] = acc
  }
  return out
}

/** 逐元素 logistic 作用在状态向量上，返回 4 向量。 */
function sigmaVec(s: PgcState4, k: number, x0: number): number[] {
  return toVec(s).map(x => logistic(x, k, x0))
}

// ============================================================================
// 刺激评估器 g：特征 → u_t ∈ [0,1]^4
// ============================================================================

export type StimulusFeature
  = | 'stim_arousal_score'
    | 'persona_energy_score'
    | 'stim_strain_score'
    | 'uncertainty_load_score'
    | 'stim_drive_score'
    | 'skill_need_score'
    | 'stim_fatigue_score'
    | 'idle_and_overload_score'

/** 特征 → 各状态维权重。先按维加权求和，再过 sigmoid，再 clip 到 [0,1]。 */
export const STIMULUS_WEIGHTS: Record<StimulusFeature, PgcState4> = {
  stim_arousal_score: { a: 0.70, c: 0.05, d: 0.00, f: 0.00 },
  persona_energy_score: { a: 0.20, c: 0.00, d: 0.00, f: 0.00 },
  stim_strain_score: { a: 0.00, c: 0.75, d: 0.00, f: 0.05 },
  uncertainty_load_score: { a: 0.00, c: 0.15, d: 0.00, f: 0.00 },
  stim_drive_score: { a: 0.00, c: 0.05, d: 0.72, f: 0.00 },
  skill_need_score: { a: 0.00, c: 0.00, d: 0.20, f: 0.00 },
  stim_fatigue_score: { a: 0.00, c: 0.08, d: 0.00, f: 0.78 },
  idle_and_overload_score: { a: 0.00, c: 0.00, d: 0.00, f: 0.18 },
}

export const STIMULUS_SPEC = {
  type: 'weighted_linear_then_sigmoid' as const,
  sigmoid: { k: 9.0, x0: 0.5 },
}

/**
 * 把特征映射为刺激向量 u_t ∈ [0,1]^4。
 * 流程：对每维先 ∑_feat weight[feat][dim]·feature[feat]，再过 sigmoid(k=9, x0=0.5)，再 clip。
 * 缺省/缺失特征按 0 处理。
 */
export function evaluateStimulus(
  features: Partial<Record<StimulusFeature, number>>,
  spec: { sigmoid: { k: number, x0: number } } = STIMULUS_SPEC,
): PgcState4 {
  const acc: Record<PgcStateDim, number> = { a: 0, c: 0, d: 0, f: 0 }
  for (const feat of Object.keys(STIMULUS_WEIGHTS) as StimulusFeature[]) {
    const val = features[feat]
    if (val == null || Number.isNaN(val))
      continue
    const w = STIMULUS_WEIGHTS[feat]
    acc.a += w.a * val
    acc.c += w.c * val
    acc.d += w.d * val
    acc.f += w.f * val
  }
  return {
    a: clamp01(logistic(acc.a, spec.sigmoid.k, spec.sigmoid.x0)),
    c: clamp01(logistic(acc.c, spec.sigmoid.k, spec.sigmoid.x0)),
    d: clamp01(logistic(acc.d, spec.sigmoid.k, spec.sigmoid.x0)),
    f: clamp01(logistic(acc.f, spec.sigmoid.k, spec.sigmoid.x0)),
  }
}

// ============================================================================
// 状态积分器
// ============================================================================

export interface PgcStateIntegrator {
  /** 当前状态 s_t。 */
  readonly state: PgcState4
  /** 推进一步（给定刺激 u_t），返回更新后的状态（已 clip 到 [0,1]）。 */
  step: (stimulus: PgcState4, dt?: number) => PgcState4
  /** 复位到基线 s*。 */
  reset: () => PgcState4
  /**
   * 离线巩固触发判定：f > fatigue_threshold 且 idle > idle_seconds 时触发，
   * 触发后把状态复位到 s* 并返回 true；否则返回 false。
   */
  maybeTriggerOfflineConsolidation: (idleSeconds: number) => boolean
}

/**
 * 创建一个四维状态积分器。相同 seed（初值）+ 相同刺激序列 ⇒ 完全相同的状态轨迹（确定性）。
 * 注意：状态积分本身不含随机项，确定性来自纯欧拉积分；检索噪声的随机性在 pgc-retrieval.ts。
 */
export function createPgcStateIntegrator(
  initial: PgcState4 = DEFAULT_PGC_STATE_SPEC.s_star,
  spec: PgcStateSpec = DEFAULT_PGC_STATE_SPEC,
): PgcStateIntegrator {
  let state: PgcState4 = { ...initial }

  function step(stimulus: PgcState4, dt: number = spec.dt): PgcState4 {
    const s = toVec(state)
    const sStar = toVec(spec.s_star)
    const lam = toVec(spec.Lambda)
    const u = toVec(stimulus)
    const sig = sigmaVec(state, spec.sigma.k, spec.sigma.x0)

    // 恢复项：-Λ·(s - s*)
    const recovery = s.map((x, i) => -lam[i] * (x - sStar[i]))
    // 驱动项：W·u
    const drive = matVec(spec.W, u)
    // 交互项：B·σ(s)
    const interaction = matVec(spec.B, sig)

    const delta = recovery.map((r, i) => r + drive[i] + interaction[i])
    const next = s.map((x, i) => x + dt * delta[i])
    state = fromVec(next)
    return state
  }

  function reset(): PgcState4 {
    state = { ...spec.s_star }
    return state
  }

  function maybeTriggerOfflineConsolidation(idleSeconds: number): boolean {
    if (state.f > spec.offline_consolidation.fatigue_threshold && idleSeconds > spec.offline_consolidation.idle_seconds) {
      reset()
      return true
    }
    return false
  }

  return {
    get state() {
      return { ...state }
    },
    step,
    reset,
    maybeTriggerOfflineConsolidation,
  }
}
