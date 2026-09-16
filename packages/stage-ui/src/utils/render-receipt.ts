/**
 * 渲染回执的**表现层本地实现** —— `aijade.lpm.render_ready` 的生成端。
 *
 * ## 为什么这里"重复实现"而不是 import
 *
 * 该事件的契约（zod schema）住在 `@proj-aijade/memory-biomimetic`，实写参数的规范化编码
 * 住在 `@proj-aijade/research-telemetry`。**两个包都不是 `stage-ui` 的依赖**，也不该是：
 * 让表现层依赖研究内核会破坏三层隔离，而 `research-telemetry` 的 `storage.ts` 引用了
 * `node:fs/promises`，拖进浏览器包会带进 node-only 代码。
 *
 * 于是两侧靠**有意重复实现 + 跨边界字面量锁**保持逐位一致：
 * - `fingerprintAppliedParams` 与 `research-telemetry/src/render-audit.ts` 同构；
 * - 同一组 golden 向量在 `render-receipt.test.ts`（本包）与 `render-audit.test.ts`
 *   （telemetry 侧）、以及字段名字面量在 `events.test.ts`（内核侧）各钉了一遍。
 *   任一侧改了编码或字段名而另一侧不改，必有一个测试变红。
 *
 * 这是本仓既有房规，沿 `stage-ui-three/src/libs/determinism.ts` 里 mulberry32 的
 * "有意重复 + 一致性锁"先例，不是新发明的模式。
 *
 * ## 与 `asset-identity.ts` 的分工
 *
 * 两者都是"渲染身份"原语，但回答的问题不同：
 * - `asset-identity.ts` → **模型资产**是谁（内容哈希 / 引用哈希）
 * - 本模块 → 这一次**渲染实际写了什么**（规范化文本，供逐位对照）
 */

import { z } from 'zod'

/**
 * 单个通道的值。
 *
 * 三分类来自表现层真实写入的通道，只有第一类是数值：
 * 数值型（情绪强度 `emotion.intensity`、眨眼速率倍率 `blink.rateScale`）／
 * 类别型（表情预设名 `emotion.preset`、注视方向 `gaze.dir`、手势名 `gesture`）／
 * 开关型（`blink.engaged`）。
 *
 * 若强行只收 `number`，后两类就得编造数值编码 —— 那会让"记录到底写了什么"失真，
 * 而这正是这份记录唯一的意义。类型与 telemetry 侧 `AppliedParams` 同构。
 */
export type AppliedParamValue = number | string | boolean

/** 通道名 → 值。与 telemetry 侧 `AppliedParams` 同构（那边是 camelCase 命名空间下的同一概念）。 */
export type AppliedParams = Record<string, AppliedParamValue>

/**
 * 定点格式化，逐位镜像 telemetry 侧 `render-audit.ts` 的私有 `formatNumber`。
 *
 * 6 位有效小数：远超任何行为效应量，同时吸收渲染路径算术带来的浮点噪声
 * （`0.1 + 0.2` 与 `0.3` 必须得到同一指纹，否则两次本质相同的渲染会被判成不同）。
 */
function formatNumber(n: number): string {
  return Number(n.toFixed(6)).toString()
}

/**
 * 单值编码，逐位镜像 telemetry 侧 `formatScalar`。
 *
 * ⚠️ 数值**不带 tag** 是有意的：这让"仅含数值"的指纹与此前版本保持逐位一致，
 * 不会静默改写已产出指纹的含义。字符串加 `s:`、布尔加 `b:0`/`b:1`，于是
 * 字符串 `'0.5'` 与数值 `0.5`、字符串 `'true'` 与布尔 `true` 都不会碰撞
 * （`render-receipt.test.ts` 两侧都钉了这两条）。
 */
function formatScalar(v: AppliedParamValue): string {
  if (typeof v === 'number')
    return formatNumber(v)
  if (typeof v === 'boolean')
    return v ? 'b:1' : 'b:0'
  return `s:${v}`
}

/**
 * 「实写通道→值」的规范化文本：键排序、`key=value`、以 `|` 连接。
 *
 * ⚠️ **不是密码学摘要**（名字里的 hash 沿用设计稿口径）。它可能较长，且**空 map 时是空串** ——
 * 后者是"什么都没写"的稳定编码，而契约中 `applied_params_hash` 是 `.min(1)`，
 * 所以空串情形必须走 {@link buildRenderReceipt} 的 `undefined` 分支（不发事件）。
 */
export function fingerprintAppliedParams(params: AppliedParams): string {
  const parts = Object.entries(params)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${formatScalar(v)}`)
  return parts.join('|')
}

/** 回执 topic。与内核 `events.ts` 的登记值一致，由 `render-receipt.test.ts` 的字面量锁守住。 */
export const LPM_RENDER_READY_TOPIC = 'aijade.lpm.render_ready' as const

/**
 * 回执 payload 的**本地** schema，与内核 `lpmRenderReadySchema` 逐字段同构
 * （snake_case；`asset_version_hash` 可缺省但不可为空串）。
 *
 * 为什么要在这里再写一遍而不是"仅做结构匹配"：本地 schema 让我们能在**发出前**
 * 做真正的运行时校验。仅靠 TS 类型是编译期的，而回执的组装发生在异步轮界上
 * （`onStreamEnd` 回调里），拼错字段名在编译期未必可见。
 */
export const lpmRenderReadyReceiptSchema = z.object({
  session_id: z.string().min(1),
  render_ref: z.string().min(1),
  applied_params_hash: z.string().min(1),
  asset_version_hash: z.string().min(1).optional(),
})
export type LpmRenderReadyReceipt = z.infer<typeof lpmRenderReadyReceiptSchema>

/**
 * 铸造**回指身份**。确定性：同 `sessionId` + 同序号必得同一字符串。
 *
 * 刻意**不用随机数**：本项目的表现层已全面改为可 bit-identical 回放
 * （见 `stage-ui-three/libs/determinism.ts`），身份若带随机性，同一次回放会对不上。
 * 序号由持有轮界的编排层递增（`onMessageSendStarted` / `onStreamEnd` 是天然轮界）。
 */
export function mintRenderRef(sessionId: string, turnSeq: number): string {
  if (!sessionId)
    throw new Error('mintRenderRef: sessionId 不能为空 —— 否则 render_ref 失去归档维度')
  if (!Number.isInteger(turnSeq) || turnSeq < 0)
    throw new Error(`mintRenderRef: turnSeq 必须是非负整数，收到 ${turnSeq}`)
  return `${sessionId}#render:${turnSeq}`
}

/**
 * 组装并校验一条渲染回执。
 *
 * 三种结局，刻意区分开：
 * - `appliedParams` 为空 ⇒ 返回 `undefined`。**没有写入就没有渲染发生**，此时正确行为是
 *   不发事件，而不是发一条 `applied_params_hash: ''` 的空回执（契约的 `.min(1)` 也会拒）。
 *   这是**合法跳过**，不是错误。
 * - 其它畸形（空 `sessionId`、空 `renderRef`、空串 `assetVersionHash` 被降级） ⇒ 抛错。
 *   这类是**代码 bug**，不是可以静默跳过的业务情形。
 * - 正常 ⇒ 返回通过本地 schema 校验的 payload。
 */
export function buildRenderReceipt(input: {
  sessionId: string
  /** 回指身份，由 {@link mintRenderRef} 或同构方式铸造。 */
  renderRef: string
  /** 本轮实际写入渲染模型的通道→值映射。 */
  appliedParams: AppliedParams
  /** 模型资产身份；异步解析，可能尚未就绪。空串会被降级为缺省。 */
  assetVersionHash?: string
}): LpmRenderReadyReceipt | undefined {
  const appliedParamsHash = fingerprintAppliedParams(input.appliedParams)
  if (appliedParamsHash === '')
    return undefined

  return lpmRenderReadyReceiptSchema.parse({
    session_id: input.sessionId,
    render_ref: input.renderRef,
    applied_params_hash: appliedParamsHash,
    // 空串会伪装成"已计算"，故显式降级为缺省而不是原样透传。
    ...(input.assetVersionHash ? { asset_version_hash: input.assetVersionHash } : {}),
  })
}
