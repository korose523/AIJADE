import type { CapabilityTokenSigner } from './capability-token'
import type { CapabilityGrant } from './contracts'
import type { AijadeEvent } from './events'
import type { V9PerceptionInput } from './v9-runtime'
import type { PgcStateRow } from './v9-schema'

import { describe, expect, it } from 'vitest'

import { createMemoryWriteGate } from './capability-token'
import { buildLearningProposedShadowParamsEvent, eventEnvelopeSchema } from './events'
import { MemoryTxEngine } from './memory-tx'
import { computeLearningInputHash } from './shadow-params'
import { V9CausalRuntime } from './v9-runtime'

describe('v9CausalRuntime', () => {
  it('runs perception through PGC, MemoryTx and EvidenceWeave in one persisted artifact', async () => {
    const artifacts: any[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (artifact) => {
        artifacts.push(artifact)
      },
    })

    const result = await runtime.processPerception({
      eventId: 'e1',
      sessionId: 's1',
      traceId: 't1',
      correlationId: 't1',
      timestamp: 1,
      originDevice: 'desktop',
      privacyLevel: 1,
      riskScore: 0.1,
      source: 'chat:user',
      content: 'A concrete user observation with a source.',
    })

    expect(artifacts).toHaveLength(1)
    expect(result.artifact.evidencePack.sessionId).toBe('s1')
    expect(result.artifact.pgcState.v6State).toEqual(expect.objectContaining({ a: expect.any(Number) }))
    expect(result.artifact.memoryTx.id).toBe('tx_e1')
    expect(result.artifact.evidenceWeave.txId).toBe('tx_e1')
    expect(result.artifact.events.map(event => event.topic)).toEqual([
      'aijade.pgc.write_plan_ready',
      'aijade.memory_tx.committed',
      'aijade.evidence.weave_candidate_ready',
    ])
  })

  it('rehydrates the previous session state before processing the next perception', async () => {
    const state: PgcStateRow = {
      id: 'pgc-old',
      sessionId: 's1',
      traceId: 'old',
      policyVersion: 'pgc_policy_v1',
      components: {
        plasticity: {
          consolidationGain: 1,
          decayMultiplier: 1,
          retrievalNoise: 0,
          moodCongruenceWeight: 0,
          socialBonus: 0,
          explorationTemperature: 0,
        },
        evidence_strength: 0,
        contradiction_severity: 0,
        evidence_uncertainty: 0,
        persona_shift_risk: 0,
      },
      v6State: { a: 0.7, c: 0.2, d: 0.3, f: 0.1 },
      createdAt: 0,
    }
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => state,
      persist: async () => undefined,
    })
    const result = await runtime.processPerception({
      eventId: 'e2',
      sessionId: 's1',
      traceId: 't2',
      correlationId: 't2',
      timestamp: 2,
      originDevice: 'desktop',
      privacyLevel: 0,
      riskScore: 0,
      source: 'chat:user',
      content: 'next',
    })
    expect(result.artifact.pgcState.v6State.a).not.toBe(state.v6State.a)
  })

  /**
   * 漂移守卫：信封的观察/传输字段必须是**运行时输入的真实值**。
   *
   * 要防的退化有两种，且都真实发生过：
   * 1. 运行时把真实 `originDevice` / 连续 `riskScore` 丢掉，让服务端落库时自行合成
   *    （`'v9-runtime'` + 3 级带宽）；
   * 2. `MemoryTxEngine` 在「无观察上下文」时的层内占位值 `'kernel:memory-tx'` 泄漏到总线。
   *    `memory_tx.committed` 是**引擎内部构造**的那条，所以它是最容易漏掉的一条 ——
   *    本测试对它逐字段钉死，而不是只看运行时自己构造的那两条。
   */
  it('stamps the runtime observation context onto every event (never the engine placeholder)', async () => {
    const artifacts: any[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (artifact) => {
        artifacts.push(artifact)
      },
    })

    const result = await runtime.processPerception({
      eventId: 'e-ctx',
      sessionId: 's-ctx',
      traceId: 't-ctx',
      correlationId: 'c-ctx',
      timestamp: 5,
      originDevice: 'pixel-9-pro',
      privacyLevel: 3,
      riskScore: 0.42,
      source: 'chat:user',
      content: 'carries a real observation context',
    })

    expect(result.artifact.events).toHaveLength(3)

    // 1) 每条事件都带真实上下文（不是"两条运行时构造的带、引擎构造的那条不带"）。
    for (const event of result.artifact.events) {
      expect(event.origin_device, `${event.topic} 的 origin_device`).toBe('pixel-9-pro')
      expect(event.privacy_level, `${event.topic} 的 privacy_level`).toBe(3)
      expect(event.risk_score, `${event.topic} 的 risk_score`).toBeCloseTo(0.42, 10)
      expect(event.causal_context_refs, `${event.topic} 的 causal_context_refs`).toEqual(['t-ctx'])
    }

    // 2) 逐条钉死引擎内部构造的那条：占位值泄漏会立刻让这条变红。
    const txEvent = result.artifact.events.find(e => e.topic === 'aijade.memory_tx.committed') as AijadeEvent
    expect(txEvent).toBeDefined()
    expect(txEvent.origin_device).not.toBe('kernel:memory-tx')
    expect(txEvent.origin_device).toBe('pixel-9-pro')
    expect(txEvent.risk_score).toBeCloseTo(0.42, 10)
    // 证据引用由引擎从本 tx 的证据链**真实派生**，不是空数组、也不是编造。
    expect(txEvent.evidence_refs).toEqual(expect.arrayContaining(['ep_e-ctx', 'ec_e-ctx']))
    expect(txEvent.evidence_refs!.length).toBeGreaterThan(0)

    // 3) 每条事件都能通过**内核自己的整事件校验** ⇒ 13 字段齐全，可直接投递 HTTP 边界。
    //    （此前内核只有 8 个字段，这一条必然失败 —— 这就是漂移的可执行判据。）
    //
    // ⚠️ 这里用的是 `eventEnvelopeSchema`（含 `topic` / `payload`），**不是** `envelopeSchema`。
    // 后者只声明信封字段；拿它去校验一个完整事件，在 `z.object` 下会**静默剥离** topic 与
    // payload 然后判"通过"—— 即断言恒为真，测不到任何东西。信封改为 `strictObject` 后，
    // 这种误用会立刻以 `unrecognized_keys: ["topic","payload"]` 暴露出来。
    for (const event of result.artifact.events) {
      const parsed = eventEnvelopeSchema.safeParse(event)
      expect(parsed.success, `${event.topic} 的信封不完整：${JSON.stringify(parsed.error?.issues)}`).toBe(true)
    }
  })

  it('learning 路径同样把真实上下文与 tick/inputHash 一起传播到信封', async () => {
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async () => undefined,
    })

    // 用真实工厂构造输入学习事件，保证 input_hash 自洽闸门通过。
    const candidateParams = { lr: 0.01 }
    const inputHash = computeLearningInputHash('s-learn', 'p-learn', candidateParams)

    const inputEvent = buildLearningProposedShadowParamsEvent({
      session_id: 's-learn',
      proposal_id: 'p-learn',
      render_ref: 'r-learn',
      applied_params_hash: 'aph-learn',
      asset_version_hash: 'avh-learn',
      input_hash: inputHash,
      candidate_params: candidateParams,
      confidence: 0.8,
    }, {
      event_id: 'evt-learn',
      trace_id: 't-learn',
      correlation_id: 'c-learn',
      timestamp: 9,
      producer: 'test',
      origin_device: 'tablet-2',
      privacy_level: 2,
      evidence_refs: [],
      causal_context_refs: ['t-learn'],
      risk_score: 0,
      idempotency_key: 'ik-learn',
      replay_mode: 'live',
      risk_level: 'low',
      tick: 7,
      causality: { inputHash },
    })

    const result = await runtime.processLearning({
      eventId: 'e-learn',
      sessionId: 's-learn',
      traceId: 't-learn',
      correlationId: 'c-learn',
      timestamp: 9,
      originDevice: 'tablet-2',
      privacyLevel: 2,
      riskScore: 0.77,
      tick: 7,
      inputHash,
      event: inputEvent,
    })

    const learningEvent = result.artifact.events.find(e => e.topic === 'aijade.learning.proposed.shadow_params')!
    expect(learningEvent.origin_device).toBe('tablet-2')
    expect(learningEvent.privacy_level).toBe(2)
    expect(learningEvent.risk_score).toBeCloseTo(0.77, 10)
    // tick / inputHash 由输入事件传播而来，不是运行时发明。
    expect(learningEvent.tick).toBe(7)
    expect(learningEvent.causality).toEqual({ inputHash })

    // 同一 artifact 里的非 v10 事件也必须带真实上下文（同一个信封家族）。
    for (const event of result.artifact.events) {
      expect(eventEnvelopeSchema.safeParse(event).success, `${event.topic} 的信封不完整`).toBe(true)
      expect(event.origin_device).toBe('tablet-2')
      expect(event.risk_score).toBeCloseTo(0.77, 10)
    }

    // v10 溯源必须覆盖**该次输入快照派生的全部事件**，而不只是 v10 前缀那一条。
    // 回放按 `tick` + `causality.inputHash` 取事件；若 `memory_tx.committed`（S6/S8 的
    // 唯一记录点）缺席，按 tick 回放就看不到「这次到底有没有真实落库」这一事实。
    for (const event of result.artifact.events) {
      expect(event.tick, `${event.topic} 丢失 tick`).toBe(7)
      expect(event.causality, `${event.topic} 丢失 causality`).toEqual({ inputHash })
    }
    // 存在性断言，避免上面那个 for 因 events 为空而恒真。
    expect(result.artifact.events.map(e => e.topic)).toContain('aijade.memory_tx.committed')
  })
})

describe('v9CausalRuntime capability-token gate (P2-1)', () => {
  // 报告 P2-1：把 `capability-token` 原语的 `authorize` 接线到运行时落库边界。
  // 此前该原语齐备却零调用（§8「能力不旁路」停留在"原语可用"）。本组测试证明：
  // 配置 gate 后，无令牌 / 无效令牌 → 拒绝落库；持有效令牌 → 正常落库。
  const signer: CapabilityTokenSigner = {
    async sign() {
      return 'signed'
    },
    async verify(token) {
      if (token !== 'valid-token')
        throw new Error('capability token invalid')
      return {
        token,
        capability: 'memory:write',
        scope: 'global',
        grantee: { userScope: 'global' },
        issuedAt: 0,
        grantId: 'grant-1',
      }
    },
  }
  const grants: CapabilityGrant[] = [{
    id: 'grant-1',
    schema: 'aijade.capability_grant@1',
    grantee: { userScope: 'global' },
    capability: 'memory:write',
    scope: 'global',
    grantedBy: 'user',
    issuedAt: 0,
    consentPolicy: 'cp-1',
    source: [{ ref: 'src-1', trusted: true }],
  }]
  const gate = createMemoryWriteGate(signer, grants)

  const perceptionInput: V9PerceptionInput = {
    eventId: 'e-gate',
    sessionId: 's-gate',
    traceId: 't-gate',
    correlationId: 't-gate',
    timestamp: 1,
    originDevice: 'desktop',
    privacyLevel: 1,
    riskScore: 0.1,
    source: 'chat:user',
    content: 'A concrete user observation that should be gated.',
  }

  it('rejects persistence when no capability token is supplied', async () => {
    const persisted: unknown[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (artifact) => {
        persisted.push(artifact)
      },
    }, { gate, writeCapability: 'memory:write', writeScope: 'global' })

    await expect(runtime.processPerception(perceptionInput)).rejects.toThrow()
    expect(persisted).toHaveLength(0)
  })

  it('rejects persistence when the token fails verification', async () => {
    const persisted: unknown[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (artifact) => {
        persisted.push(artifact)
      },
    }, { gate, writeCapability: 'memory:write', writeScope: 'global' })

    await expect(runtime.processPerception({ ...perceptionInput, capabilityToken: 'bogus' })).rejects.toThrow()
    expect(persisted).toHaveLength(0)
  })

  it('persists normally when a valid capability token is supplied', async () => {
    const persisted: unknown[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (artifact) => {
        persisted.push(artifact)
      },
    }, { gate, writeCapability: 'memory:write', writeScope: 'global' })

    const result = await runtime.processPerception({ ...perceptionInput, capabilityToken: 'valid-token' })
    expect(persisted).toHaveLength(1)
    expect(result.artifact.memoryTx.id).toBe('tx_e-gate')
    expect(result.tx.committed.length).toBeGreaterThan(0)
  })

  it('memoryTxEngine refuses commit without a token when a gate is configured', () => {
    const engine = new MemoryTxEngine({ gate })
    expect(() => engine.commit({
      session_id: 's',
      trace_id: 't',
      pgc_write_plan: [],
      memory_payloads: [],
      tx_policy: { atomicity: 'per_write', max_writes: 1 },
    })).toThrow(/missing capability token/)
  })

  it('without a gate configured, behaviour is unchanged (no enforcement)', async () => {
    const persisted: unknown[] = []
    const runtime = new V9CausalRuntime({
      readLatestPgcState: async () => undefined,
      persist: async (artifact) => {
        persisted.push(artifact)
      },
    })
    await runtime.processPerception(perceptionInput)
    expect(persisted).toHaveLength(1)
  })
})
