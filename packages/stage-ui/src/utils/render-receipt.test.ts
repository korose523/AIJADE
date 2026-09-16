import { describe, expect, it } from 'vitest'

import {
  buildRenderReceipt,
  fingerprintAppliedParams,
  LPM_RENDER_READY_TOPIC,
  lpmRenderReadyReceiptSchema,
  mintRenderRef,
} from './render-receipt'

describe('fingerprintAppliedParams — 表现层本地实现', () => {
  it('与键插入顺序无关（键排序）', () => {
    const a = fingerprintAppliedParams({ 'emotion.intensity': 0.4, 'blink.rateScale': 1.25 })
    const b = fingerprintAppliedParams({ 'blink.rateScale': 1.25, 'emotion.intensity': 0.4 })
    expect(a).toBe(b)
  })

  it('定点吸收浮点噪声', () => {
    expect(fingerprintAppliedParams({ a: 0.1 + 0.2 })).toBe(fingerprintAppliedParams({ a: 0.3 }))
  })

  it('空 map ⇒ 空串（"什么都没写"的稳定编码）', () => {
    expect(fingerprintAppliedParams({})).toBe('')
  })

  it('非数值通道带 tag，三类通道可区分', () => {
    expect(fingerprintAppliedParams({ 'emotion.preset': 'happy' })).toBe('emotion.preset=s:happy')
    expect(fingerprintAppliedParams({ 'blink.engaged': true })).toBe('blink.engaged=b:1')
    expect(fingerprintAppliedParams({ 'blink.engaged': false })).toBe('blink.engaged=b:0')
  })

  it('跨类型不碰撞（字符串 "0.5" 不等于数值 0.5）', () => {
    expect(fingerprintAppliedParams({ x: '0.5' })).not.toBe(fingerprintAppliedParams({ x: 0.5 }))
    expect(fingerprintAppliedParams({ x: 'true' })).not.toBe(fingerprintAppliedParams({ x: true }))
  })

  /**
   * 跨边界一致性锁（golden vector）—— 与 `@proj-aijade/research-telemetry` 的
   * `render-audit.test.ts` 里钉的是**同一个字面量**。
   *
   * 两处必须逐位一致：内核侧用 `applied_params_hash` 与存储的 `appliedParams` 复算对照，
   * 若两侧编码不同，事件里的指纹将永远对不上存储记录 —— 而且是**静默**对不上。
   * 该字面量是用 telemetry 侧实现实跑出来的值。
   */
  it('钉住跨边界 golden 向量（与 telemetry 侧同一字面量）', () => {
    const vector = {
      'emotion.preset': 'happy',
      'emotion.intensity': 0.4,
      'blink.engaged': true,
      'blink.rateScale': 1.25,
      'gaze.dir': 'down',
    }
    expect(fingerprintAppliedParams(vector))
      .toBe('blink.engaged=b:1|blink.rateScale=1.25|emotion.intensity=0.4|emotion.preset=s:happy|gaze.dir=s:down')
  })
})

describe('mintRenderRef — 确定性回指身份', () => {
  it('同 session + 同序号 ⇒ 同身份（回放可复现）', () => {
    expect(mintRenderRef('s1', 3)).toBe(mintRenderRef('s1', 3))
  })

  it('不同序号 ⇒ 不同身份（不与内容指纹混同）', () => {
    expect(mintRenderRef('s1', 3)).not.toBe(mintRenderRef('s1', 4))
  })

  it('空 sessionId / 非法序号 ⇒ 抛错（身份不可为空白）', () => {
    expect(() => mintRenderRef('', 0)).toThrow()
    expect(() => mintRenderRef('s1', -1)).toThrow()
    expect(() => mintRenderRef('s1', 1.5)).toThrow()
  })
})

describe('buildRenderReceipt — 组装并本地校验', () => {
  const params = { 'emotion.preset': 'happy', 'emotion.intensity': 0.4 }

  it('正常情形 ⇒ 产出通过本地 schema 的 payload', () => {
    const r = buildRenderReceipt({ sessionId: 's1', renderRef: 'r1', appliedParams: params })
    expect(r).toBeDefined()
    expect(lpmRenderReadyReceiptSchema.safeParse(r).success).toBe(true)
    expect(r?.applied_params_hash).toBe(fingerprintAppliedParams(params))
  })

  it('未写入任何通道 ⇒ 返回 undefined（合法跳过，不发空回执）', () => {
    expect(buildRenderReceipt({ sessionId: 's1', renderRef: 'r1', appliedParams: {} })).toBeUndefined()
  })

  it('assetVersionHash 缺省 ⇒ payload 不含该键', () => {
    const r = buildRenderReceipt({ sessionId: 's1', renderRef: 'r1', appliedParams: params })
    expect(r && 'asset_version_hash' in r).toBe(false)
  })

  it('assetVersionHash 为空串 ⇒ 降级为缺省（空串不得伪装成"已计算"）', () => {
    const r = buildRenderReceipt({ sessionId: 's1', renderRef: 'r1', appliedParams: params, assetVersionHash: '' })
    expect(r && 'asset_version_hash' in r).toBe(false)
  })

  it('assetVersionHash 有值 ⇒ 原样带出', () => {
    const r = buildRenderReceipt({ sessionId: 's1', renderRef: 'r1', appliedParams: params, assetVersionHash: 'avh_1' })
    expect(r?.asset_version_hash).toBe('avh_1')
  })

  it('畸形输入（空 renderRef）⇒ 抛错，而不是静默产出坏回执', () => {
    expect(() => buildRenderReceipt({ sessionId: 's1', renderRef: '', appliedParams: params })).toThrow()
  })

  /**
   * 跨边界字面量锁 —— 字段名与 topic 与内核 `events.test.ts` 钉的是同一组。
   * 表现层不能 import 内核包，所以靠这条 + 内核侧同名断言防分叉。
   */
  it('跨边界字面量锁：topic 与字段名被钉死', () => {
    expect(LPM_RENDER_READY_TOPIC).toBe('aijade.lpm.render_ready')

    const r = buildRenderReceipt({
      sessionId: 's1',
      renderRef: 'r1',
      appliedParams: params,
      assetVersionHash: 'avh_1',
    })
    expect(Object.keys(r ?? {}).sort()).toEqual([
      'applied_params_hash',
      'asset_version_hash',
      'render_ref',
      'session_id',
    ])
  })
})
