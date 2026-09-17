/**
 * Core State Node (v10 §4.2 / §4.3 / §11.3) — 关键事件 → 内生状态节点映射。
 *
 * ## 为什么需要
 *
 * v10 要求：**每条关键事件必须能映射到某个 `coreStateNode`（`S0..S8`）**，且
 * 「同一 `tick` 与同一 `causality.inputHash` 下，ECD dispatcher 对应的 `coreStateNode`
 * 选择必须一致」。本模块是这层映射的**唯一真源**（内核产事件时打标、服务端回放时复算，
 * 两边都调同一个纯函数，保证一致）。
 *
 * ## 设计约束（红线）
 *
 * 节点的取值**必须依赖真实控制流事实**，不能只按 topic 字面映射，否则同一 tick/inputHash
 * 下不同事件会漂移、且回放无法检出。因此：
 * - `S5`（PGC 写入门控）无论 `commitPossible` 结论如何都归约到 `S5`；
 * - `S8`（真实落库）**只在 `hasMemoryVersion === true` 时出现**，否则停在 `S6`
 *   （MemoryTx 执行但未真正落库）。`hasMemoryVersion` 是「内存版本是否真的写进
 *   `memory_versions`」这一可审计事实，不是运行时发明——回放侧从持久化产物读回它。
 *
 * ## 映射表（逐行，附理由）
 *
 * | 节点 | 触发事件 / 条件                         | 理由 |
 * |------|----------------------------------------|------|
 * | S0   | 未纳入 v10 因果链的兜底（persona/lpm 等未知 topic） | 默认兜底，保证任何事件都有归属、不抛错 |
 * | S1   | `aijade.active_learning.*`（学习任务边界）            | 学习任务生命周期入口，独立阶段 |
 * | S2   | `aijade.video.*`（视频观察归约）                     | 视频观察是该前缀生产者产出的归约事件 |
 * | S3   | `aijade.learning.proposed.*`（学习提案归约 shadow params / evidence） | 内核 `processLearning` 产出 |
 * | S4   | `aijade.evidence.*` 中非 `weave_candidate_ready`      | EvidenceGate 求值（证据门） |
 * | S5   | `aijade.pgc.write_plan_ready`（PGC 写入门控）          | 无论 commit/reject/throttle/defer 结论，门已被求值 |
 * | S6   | `aijade.memory_tx.committed` 且未真正落库              | MemoryTx 执行，但 `memory_version_id === null` |
 * | S7   | `aijade.evidence.weave_candidate_ready`               | EvidenceWeave ready |
 * | S8   | `aijade.memory_tx.committed` 且 `hasMemoryVersion`     | 唯一「真实落库」节点，与 `memory_version_id !== null` 一一对应 |
 *
 * 注意：`S4` 与 `S7` 同属 `aijade.evidence.*` 前缀，靠「是否 `weave_candidate_ready`」
 * 区分；`S6`/`S8` 同属 `aijade.memory_tx.committed`，靠 `hasMemoryVersion` 区分。
 */

/** v10 内生状态节点全集（S0..S8）。 */
export const CORE_STATE_NODES = [
  'S0',
  'S1',
  'S2',
  'S3',
  'S4',
  'S5',
  'S6',
  'S7',
  'S8',
] as const

export type CoreStateNode = (typeof CORE_STATE_NODES)[number]

export interface DeriveCoreStateNodeInput {
  /**
   * 真实控制流事实：本次 `MemoryTx` 是否真正落库（即 `memory_versions` 中存在对应行，
   * `memory_version_id !== null`）。决定 `S6` ↔ `S8`。
   */
  hasMemoryVersion?: boolean
  /**
   * PGC 门控的实际结论（`commit_possible`）。本映射中 `S5` 不论结论，保留此字段
   * 以供审计/未来区分，当前不参与节点选择。
   */
  commitPossible?: boolean
}

/**
 * 纯函数：由事件 topic + 真实控制流事实推导其 `coreStateNode`。
 *
 * 确定性：相同输入 ⇒ 相同输出，回放侧可复算并与持久化记录比对（检出漂移）。
 */
export function deriveCoreStateNode(
  topic: string,
  input?: DeriveCoreStateNodeInput,
): CoreStateNode {
  if (topic.startsWith('aijade.video.'))
    return 'S2'
  if (topic.startsWith('aijade.learning.proposed.'))
    return 'S3'
  if (topic === 'aijade.pgc.write_plan_ready')
    return 'S5'
  if (topic === 'aijade.memory_tx.committed')
    return input?.hasMemoryVersion ? 'S8' : 'S6'
  if (topic === 'aijade.evidence.weave_candidate_ready')
    return 'S7'
  if (topic.startsWith('aijade.evidence.'))
    return 'S4'
  if (topic.startsWith('aijade.active_learning.'))
    return 'S1'
  return 'S0'
}
