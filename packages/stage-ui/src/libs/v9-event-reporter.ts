import type { V9EventEnvelope } from '../utils/render-receipt'

import { authedFetch } from './auth-fetch'
import { SERVER_URL } from './server'

/**
 * v9 事件总线的客户端上报器（Step B 设计稿 §4，传输层）。
 *
 * 约束（来自设计稿 §2 / 用户拍板）：
 * - **不 import 内核**：本文件只发普通 JSON，`stage-ui` 不依赖
 *   `@proj-aijade/memory-biomimetic`（破坏三层隔离）。信封/payload 形状由调用方负责
 *   构造，与内核 `events.ts` 逐字段同构（字段名由 `render-receipt.test.ts` 的 golden
 *   向量锁在 `events.test.ts` 上）。
 * - **fire-and-forget**：渲染链路调用它时绝不能被阻塞或抛错。投递失败只打日志，
 *   不向上抛——前车之鉴：`038655f` 的提交信息原文，「silent memory telemetry is how a
 *   dissertation ends up citing data that never existed」。
 * - **重试靠幂等键**：`idempotency_key` 由调用方保证同一次渲染稳定且唯一，服务端
 *   `ON CONFLICT DO NOTHING` 去重，这里无需复杂重试。
 */
export const V9_EVENTS_ENDPOINT = `${SERVER_URL}/api/v1/v9/events`

export function reportV9Event(envelope: V9EventEnvelope): void {
  void authedFetch(V9_EVENTS_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(envelope),
  }).then((res) => {
    if (!res.ok) {
      // 非 2xx 必须可见——但只日志，不抛。
      console.warn(`[v9-event-reporter] event rejected: topic=${envelope.topic} status=${res.status}`)
    }
  }).catch((err) => {
    console.warn('[v9-event-reporter] failed to report event', err)
  })
}
