import { integer, minLength, minValue, number, object, picklist, pipe, record, string, unknown as vUnknown } from 'valibot'

/**
 * v9 事件信封的服务端校验 schema（valibot）。
 *
 * 真源：`packages/memory-biomimetic/src/events.ts` 的 `aijadeEventSchema`（zod v4）。
 * 本仓 `apps/` 不依赖研究内核（三层隔离，见 `PROVENANCE.md` / working-memory 备注），
 * 故此处**有意复制** envelope + topic 约束，而不是 import 内核。复制带来的漂移风险由
 * 以下机制兜底：
 * - 表现层 `packages/stage-ui/src/utils/render-receipt.ts` 用 golden 向量把 payload 字段名
 *   逐位锁在 `events.test.ts`（内核侧），任一侧改字段名都会变红；
 * - 本文件的 `AIJADE_TOPICS` 必须与内核 `AIJADE_TOPICS` 字面量集合逐一一致——新增 topic
 *   时两处都要加，否则该 topic 会在 HTTP 边界被拒（400）。
 *
 * 目的：在 HTTP 边界处**拒绝畸形信封**，绝不静默吞下；`payload` 以宽松 record 透传，
 * 因为 `events` 是 jsonb 通用总线，语义校验留给各 topic 的属主（目前是 P4 证据管线）。
 *
 * ⚠️ 不在服务端重算 `applied_params_hash`：客户端是"实写"的唯一目击者，服务端重算会
 * 引入双实现漂移（见 Step B 设计稿 §2 / §6）。
 */
export const AIJADE_TOPICS = [
  'aijade.active_learning.requested',
  'aijade.active_learning.completed',
  'aijade.evidence.weave_candidate_ready',
  'aijade.pgc.write_plan_ready',
  'aijade.memory_tx.committed',
  'aijade.persona.render_requested',
  'aijade.lpm.render_ready',
] as const

export const v9EventEnvelopeSchema = object({
  event_id: pipe(string(), minLength(1)),
  trace_id: pipe(string(), minLength(1)),
  correlation_id: pipe(string(), minLength(1)),
  /** 内核信封用 number（unix ms）。服务端只做非负整数校验，再 `new Date()` 落库。 */
  timestamp: pipe(number(), integer(), minValue(0)),
  producer: pipe(string(), minLength(1)),
  /** 幂等键：承担去重，不是 event_id（event_id 只保证全局不撞）。 */
  idempotency_key: pipe(string(), minLength(1)),
  replay_mode: picklist(['live', 'replay']),
  risk_level: picklist(['low', 'medium', 'high']),
  topic: picklist(AIJADE_TOPICS),
  /** 通用总线：payload 透传，语义校验留待各 topic 属主。 */
  payload: record(string(), vUnknown()),
})
