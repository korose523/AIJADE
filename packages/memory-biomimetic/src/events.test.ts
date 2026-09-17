import { describe, expect, it } from 'vitest'

import {
  AIJADE_TOPICS,
  aijadeEventSchema,
  envelopeSchema,
  eventEnvelopeSchema,
  memoryTxCommittedEvent,
  safeParseAijadeEvent,
} from './events'

function baseEnvelope(over: Record<string, unknown> = {}) {
  return {
    event_id: 'evt_1',
    trace_id: 'tr_1',
    correlation_id: 'cor_1',
    timestamp: 1_700_000_000_000,
    producer: 'memory-tx',
    // 观察/传输字段：与 HTTP 边界同集，**必填**（不是可选项）。
    origin_device: 'test-device',
    privacy_level: 1,
    evidence_refs: [],
    causal_context_refs: ['tr_1'],
    risk_score: 0,
    idempotency_key: 'idem_1',
    replay_mode: 'live',
    risk_level: 'low',
    ...over,
  }
}

describe('事件信封 — 统一契约', () => {
  it('合法信封通过校验', () => {
    const ok = eventEnvelopeSchema.parse({ ...baseEnvelope(), topic: 'aijade.memory_tx.committed', payload: { tx_id: 't' } })
    expect(ok.event_id).toBe('evt_1')
  })

  it('缺少 idempotency_key ⇒ 拒绝（支撑 events 表唯一约束/幂等）', () => {
    const r = eventEnvelopeSchema.safeParse({ ...baseEnvelope(), idempotency_key: undefined })
    expect(r.success).toBe(false)
  })

  it('非法 risk_level / replay_mode ⇒ 拒绝', () => {
    expect(eventEnvelopeSchema.safeParse({ ...baseEnvelope(), risk_level: 'critical' }).success).toBe(false)
    expect(eventEnvelopeSchema.safeParse({ ...baseEnvelope(), replay_mode: 'maybe' }).success).toBe(false)
  })
})

/**
 * 漂移守卫：内核信封与 HTTP 边界信封**必须是同一组字段**。
 *
 * 背景（这条守卫要防的正是它）：内核一度只有 8 个字段、边界要求 13 个，于是内核工厂产出的
 * 信封**根本投递不到事件总线**（必被 400 拒），而服务端落库侧只好自行合成缺失的 5 个 ——
 * 把真实 `originDevice` 覆写成字面量 `'v9-runtime'`、把连续的 `riskScore` 压回 3 级带宽。
 * 现在这组名字被钉死在这里：任何一侧多一个/少一个字段，都会在**本仓**或
 * `apps/server/scripts/verify-v10-contract-drift.ts` 的跨端同集断言上立刻变红。
 */
describe('事件信封 — 字段集与边界同集（漂移守卫）', () => {
  /** 边界 `v9EventEnvelopeSchema` 要求的 13 个字段，逐字对应。 */
  const REQUIRED = [
    'event_id',
    'trace_id',
    'correlation_id',
    'timestamp',
    'producer',
    'origin_device',
    'privacy_level',
    'evidence_refs',
    'causal_context_refs',
    'risk_score',
    'idempotency_key',
    'replay_mode',
    'risk_level',
  ]

  /** v10 可选字段：v9 生产者可省，`aijade.video.*` / `aijade.learning.*` 必给。 */
  const OPTIONAL = ['tick', 'causality', 'core_state_node']

  it('schema 的字段集合恰好是 13 必需 + 3 可选（多一个少一个都失败）', () => {
    expect(Object.keys(envelopeSchema.shape).sort()).toEqual([...REQUIRED, ...OPTIONAL].sort())
  })

  it('13 个必需字段逐个缺失都必须被拒（含 5 个观察/传输字段）', () => {
    // 注意用 `envelopeSchema`（仅信封）而不是 `eventEnvelopeSchema`（信封 + topic + payload）：
    // 后者在缺 topic/payload 时**也会**失败，会让「缺失某字段必须被拒」变成恒真断言。
    for (const field of REQUIRED) {
      const r = envelopeSchema.safeParse({ ...baseEnvelope(), [field]: undefined })
      expect(r.success, `缺失 ${field} 必须被拒`).toBe(false)
    }
  })

  it('3 个 v10 可选字段确实可省（与上面的「必需」形成对照，证明断言不是恒真）', () => {
    const r = envelopeSchema.safeParse(baseEnvelope())
    expect(r.success).toBe(true)
  })

  it('观察/传输字段不接受空串与越界值（不是「有键即通过」）', () => {
    expect(envelopeSchema.safeParse({ ...baseEnvelope(), origin_device: '' }).success).toBe(false)
    expect(envelopeSchema.safeParse({ ...baseEnvelope(), privacy_level: 4 }).success).toBe(false)
    expect(envelopeSchema.safeParse({ ...baseEnvelope(), risk_score: 1.5 }).success).toBe(false)
    expect(envelopeSchema.safeParse({ ...baseEnvelope(), risk_score: -0.1 }).success).toBe(false)
  })
})

describe('topic schema — 判别联合', () => {
  it('已知 topic 的强类型事件通过校验', () => {
    const ev = memoryTxCommittedEvent.parse({
      ...baseEnvelope(),
      topic: 'aijade.memory_tx.committed',
      payload: { tx_id: 'tx_1', trace_id: 'tr_1', committed_count: 2, rejected_count: 0, throttled_count: 1 },
    })
    expect(ev.topic).toBe('aijade.memory_tx.committed')
    expect((ev.payload as { committed_count: number }).committed_count).toBe(2)
  })

  it('未知 topic ⇒ 拒绝（强制登记，防止静默接受非法事件）', () => {
    const r = safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.unknown.topic', payload: {} })
    expect(r.success).toBe(false)
  })

  it('payload 形状错误（缺字段）⇒ 拒绝', () => {
    const r = safeParseAijadeEvent({
      ...baseEnvelope(),
      topic: 'aijade.pgc.write_plan_ready',
      payload: { pgc_state_id: 'x' }, // 缺 write_plan_size / policy_version
    })
    expect(r.success).toBe(false)
  })

  it('全部 7 个规范 topic 都能被判别联合接受', () => {
    const topics: { topic: string, payload: Record<string, unknown> }[] = [
      { topic: 'aijade.active_learning.requested', payload: { session_id: 's', trace_id: 't', requested_at: 1, quest_ref: 'q1', resource_budget: { allocated: 10, spent: 0, unit: 'queries' }, stop_conditions: ['信息增益低于阈值'] } },
      { topic: 'aijade.active_learning.completed', payload: { session_id: 's', trace_id: 't', completed_at: 2, quest_ref: 'q1' } },
      { topic: 'aijade.evidence.weave_candidate_ready', payload: { tx_id: 'x', weave_id: 'w', graph_hash: 'h', candidate_memory_write_ids: [] } },
      { topic: 'aijade.pgc.write_plan_ready', payload: { pgc_state_id: 'p', write_plan_size: 1, policy_version: 'v1' } },
      { topic: 'aijade.memory_tx.committed', payload: { tx_id: 'x', trace_id: 't', committed_count: 1, rejected_count: 0, throttled_count: 0 } },
      { topic: 'aijade.persona.render_requested', payload: { session_id: 's', persona_snapshot_ref: 'ps1', intent_ref: 'pi1' } },
      { topic: 'aijade.lpm.render_ready', payload: { session_id: 's', render_ref: 'rr1', applied_params_hash: 'h1' } },
    ]
    for (const t of topics) {
      const r = aijadeEventSchema.safeParse({ ...baseEnvelope(), topic: t.topic, payload: t.payload })
      expect(r.success, `topic ${t.topic} 应被接受`).toBe(true)
    }
  })
})

describe('有界性 — v8 §48.2 由 schema 保证（不是靠调用方自觉）', () => {
  const validRequested = {
    session_id: 's',
    trace_id: 't',
    requested_at: 1,
    quest_ref: 'q1',
    resource_budget: { allocated: 10, spent: 0, unit: 'queries' },
    stop_conditions: ['信息增益低于阈值'],
  }

  function parseRequested(payload: Record<string, unknown>) {
    return safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.active_learning.requested', payload })
  }

  it('基线：合法请求被接受', () => {
    expect(parseRequested(validRequested).success).toBe(true)
  })

  it('缺 stop_conditions ⇒ 拒绝（禁止无终点浏览）', () => {
    const { stop_conditions: _drop, ...rest } = validRequested
    expect(parseRequested(rest).success).toBe(false)
  })

  it('stop_conditions 为空数组 ⇒ 拒绝', () => {
    expect(parseRequested({ ...validRequested, stop_conditions: [] }).success).toBe(false)
  })

  it('缺 resource_budget ⇒ 拒绝（任务必须在开始前被界定）', () => {
    const { resource_budget: _drop, ...rest } = validRequested
    expect(parseRequested(rest).success).toBe(false)
  })

  it('spent > allocated ⇒ 拒绝（预算必须可界定）', () => {
    const r = parseRequested({ ...validRequested, resource_budget: { allocated: 5, spent: 6, unit: 'queries' } })
    expect(r.success).toBe(false)
  })

  it('缺 quest_ref ⇒ 拒绝（无法回指活真源）', () => {
    const { quest_ref: _drop, ...rest } = validRequested
    expect(parseRequested(rest).success).toBe(false)
  })
})

describe('渲染请求 — §52.5 引用必填', () => {
  function parseRenderRequested(payload: Record<string, unknown>) {
    return safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.persona.render_requested', payload })
  }

  it('缺 persona_snapshot_ref ⇒ 拒绝（先渲染再补身份被排除）', () => {
    expect(parseRenderRequested({ session_id: 's', intent_ref: 'pi1' }).success).toBe(false)
  })

  it('persona_snapshot_ref 为空串 ⇒ 拒绝', () => {
    expect(parseRenderRequested({ session_id: 's', persona_snapshot_ref: '', intent_ref: 'pi1' }).success).toBe(false)
  })

  it('缺 intent_ref ⇒ 拒绝（否则 lpm.render_ready 无法回指）', () => {
    expect(parseRenderRequested({ session_id: 's', persona_snapshot_ref: 'ps1' }).success).toBe(false)
  })

  it('已废弃的旧字段名 persona_ref 不再被接受', () => {
    expect(parseRenderRequested({ session_id: 's', persona_ref: 'ps1' }).success).toBe(false)
  })
})

describe('渲染回执 — 身份/内容职责分离，且不可退化', () => {
  const validReady = {
    session_id: 's',
    render_ref: 'rr1',
    applied_params_hash: 'emotion.intensity=0.4|emotion.preset=s:happy',
  }

  function parseRenderReady(payload: Record<string, unknown>) {
    return safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.lpm.render_ready', payload })
  }

  it('基线：合法回执被接受', () => {
    expect(parseRenderReady(validReady).success).toBe(true)
  })

  it('render_ref 为空串 ⇒ 拒绝（否则回执无法与请求配对）', () => {
    expect(parseRenderReady({ ...validReady, render_ref: '' }).success).toBe(false)
  })

  it('缺 render_ref ⇒ 拒绝（旧 optional 契约的回退锁）', () => {
    const { render_ref: _drop, ...rest } = validReady
    expect(parseRenderReady(rest).success).toBe(false)
  })

  it('缺 applied_params_hash ⇒ 拒绝（回执必须能证明写了什么）', () => {
    const { applied_params_hash: _drop, ...rest } = validReady
    expect(parseRenderReady(rest).success).toBe(false)
  })

  it('applied_params_hash 为空串 ⇒ 拒绝（"什么都没写"不得表达为一条空回执）', () => {
    expect(parseRenderReady({ ...validReady, applied_params_hash: '' }).success).toBe(false)
  })

  it('asset_version_hash 缺省可接受（异步解析可能未就绪）', () => {
    expect(parseRenderReady({ ...validReady, asset_version_hash: undefined }).success).toBe(true)
  })

  it('asset_version_hash 为空串 ⇒ 拒绝（空串会伪装成"已计算"）', () => {
    expect(parseRenderReady({ ...validReady, asset_version_hash: '' }).success).toBe(false)
  })

  it('跨边界字面量锁：topic 与字段名被钉死（表现层镜像同组字面量）', () => {
    // 这组字面量在 `@proj-aijade/stage-ui` 的 `utils/render-receipt.test.ts` 里被同样钉了一遍。
    // 表现层不能 import 本包（会违反三层隔离），所以两侧靠"有意重复 + 字面量锁"防分叉 ——
    // 任一侧改名而另一侧不改，两个测试里必有一个变红。沿 `stage-ui-three/libs/determinism.ts`
    // 里 mulberry32 跨实现锁的既有房规。
    expect(AIJADE_TOPICS).toContain('aijade.lpm.render_ready')

    const r = parseRenderReady({ ...validReady, asset_version_hash: 'a1' })
    expect(r.success).toBe(true)
    expect(Object.keys((r as { data: { payload: Record<string, unknown> } }).data.payload).sort()).toEqual([
      'applied_params_hash',
      'asset_version_hash',
      'render_ref',
      'session_id',
    ])
  })
})

describe('video 观察 payload — A 路「会话」必须携带 session_id', () => {
  const webpagePayload = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
    session_id: 's-1',
    source_url: 'https://example.com',
    content_hash: 'ch-1',
    spans: [{ start_offset: 0, end_offset: 5, label: 'p' }],
    observation_text: 'text',
    ...over,
  })
  const transcriptPayload = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
    session_id: 's-1',
    video_id: 'v-1',
    transcript_hash: 'th-1',
    time_spans: [{ start_ms: 0, end_ms: 100, text: 'cap' }],
    caption_text: 'cap',
    ...over,
  })

  function parseWebpage(payload: Record<string, unknown>) {
    return safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.video.observation.webpage_text', payload })
  }
  function parseTranscript(payload: Record<string, unknown>) {
    return safeParseAijadeEvent({ ...baseEnvelope(), topic: 'aijade.video.observation.video_transcript', payload })
  }

  it('webpage_text 基线：带 session_id 被接受', () => {
    expect(parseWebpage(webpagePayload({ session_id: 's-1' })).success).toBe(true)
  })
  it('webpage_text 缺 session_id ⇒ 拒绝', () => {
    const { session_id: _drop, ...rest } = webpagePayload({ session_id: 's-1' })
    expect(parseWebpage(rest).success).toBe(false)
  })
  it('webpage_text session_id 为空串 ⇒ 拒绝', () => {
    expect(parseWebpage(webpagePayload({ session_id: '' })).success).toBe(false)
  })

  it('video_transcript 基线：带 session_id 被接受', () => {
    expect(parseTranscript(transcriptPayload({ session_id: 's-1' })).success).toBe(true)
  })
  it('video_transcript 缺 session_id ⇒ 拒绝', () => {
    const { session_id: _drop, ...rest } = transcriptPayload({ session_id: 's-1' })
    expect(parseTranscript(rest).success).toBe(false)
  })
  it('video_transcript session_id 为空串 ⇒ 拒绝', () => {
    expect(parseTranscript(transcriptPayload({ session_id: '' })).success).toBe(false)
  })
})
