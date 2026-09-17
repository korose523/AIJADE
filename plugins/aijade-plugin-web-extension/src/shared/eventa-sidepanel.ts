import type { ExtensionStatus } from './types'
import type { OpinionEvaluationPayload, V10EvidenceEvent } from './v10-evidence'

import { defineInvokeEventa } from '@moeru/eventa'

/**
 * 侧边栏 → background 的"请求当前标签页归约结果"调用。
 *
 * 复用既有 eventa 约定（与 popup 的 `popupGetStatus` 同机制，只是通道名不同），
 * **不新造通信层**。background 在 `entrypoints/background.ts` 注册对应 handler。
 *
 * 侧边栏只负责"展示"，不直接调 LLM / 不直接 fetch 服务端：
 * - `pageEvidence` / `subtitleEvidence` 由 background 用确定性 `reduce*` 归约（无 LLM）；
 * - `opinion` 由 background 走 LLM 产出（仅当请求带 `includeOpinion` 时才计算，
 *   避免后台状态频繁变化时反复打 LLM）。
 */
export interface SidePanelEvidenceRequest {
  /** 是否一并计算观点评价（需要后台 LLM）。默认 false。 */
  includeOpinion?: boolean
}

export interface SidePanelEvidence {
  /** 连接 / 设置 / 最近一次页面·字幕原始上下文（来自 `ExtensionStatus`）。 */
  status: ExtensionStatus
  /** 当前页面的确定性归约（摘要卡片用），无页面时为 null。 */
  pageEvidence: V10EvidenceEvent | null
  /** 当前字幕的确定性归约（字幕要点用，含 `time_spans` 时间码），无字幕时为 null。 */
  subtitleEvidence: V10EvidenceEvent | null
  /**
   * 当前页面的观点评价（`claims` + `uncertainty_notes`，由 background 走 LLM 产出），
   * 失败 / 未启用 LLM / 未请求时为 null。UI 只展示，不在此处调用 LLM。
   */
  opinion: OpinionEvaluationPayload | null
}

export const sidepanelRequestEvidence = defineInvokeEventa<SidePanelEvidence, SidePanelEvidenceRequest>(
  'eventa:invoke:web-extension:sidepanel:request-evidence',
)
