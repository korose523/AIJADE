import type { AppliedParams } from '../../utils/render-receipt'

import { ContextUpdateStrategy } from '@proj-aijade/server-sdk'
import { describe, expect, it, vi } from 'vitest'

import { fingerprintAppliedParams } from '../../utils/render-receipt'
import { createMemoryBridge, createPerformanceBridge } from './memory-performance'

// ---------------------------------------------------------------------------
// Mocks — the bridge only needs the MemoryPort / PerformanceDirector *shapes*,
// so we drive it with lightweight fakes instead of the real engines.
// ---------------------------------------------------------------------------

function makeMemoryPort() {
  const ingested: string[] = []
  return {
    ingested,
    recall: vi.fn(async (q: string) => (q.trim() ? `[recall:${q}]` : null)),
    ingestUser: vi.fn((t: string) => { ingested.push(`u:${t}`) }),
    ingestAssistant: vi.fn((t: string) => { ingested.push(`a:${t}`) }),
    maybeCompact: vi.fn(),
  }
}

function makeDirector() {
  const calls: string[] = []
  return {
    calls,
    enterListen: vi.fn(() => calls.push('enterListen')),
    onToken: vi.fn((_t: string) => calls.push('onToken')),
    applyMarkers: vi.fn((_t: string) => calls.push('applyMarkers')),
    onTurnEnd: vi.fn(() => calls.push('onTurnEnd')),
    // 真实的 PerformanceDirector 有 tick()（被 bridge 的自驱 100ms 定时器调用）。
    // 缺省会导致定时器在测试结束后异步抛出 "tick is not a function"，使整个进程崩溃。
    tick: vi.fn(() => calls.push('tick')),
    snapshot: vi.fn(() => ({ state: 'listen' as const, emotion: 'neutral' as const, relationDelta: 0 })),
  }
}

const noopDeps = {} as any

describe('createMemoryBridge', () => {
  it('prepareSend pre-computes a recall that the sync provider drains in FIFO order', async () => {
    const port = makeMemoryPort()
    const bridge = createMemoryBridge(port)
    const deps = bridge.wrapDeps(noopDeps)

    expect(Array.isArray(deps.runtimeContextProviders)).toBe(true)
    const provider = deps.runtimeContextProviders![deps.runtimeContextProviders!.length - 1]

    await bridge.prepareSend('hello world')
    const msg = provider()
    expect(msg).not.toBeNull()
    expect(msg!.text).toContain('[recall:hello world]')
    expect(msg!.contextId).toBe('memory:recall')
    expect(msg!.strategy).toBe(ContextUpdateStrategy.ReplaceSelf)
    expect(msg!.createdAt).toBeTypeOf('number')

    // Second drain is empty -> provider yields null so the caller skips it.
    expect(provider()).toBeNull()
  })

  it('skips recall injection when the query is blank', async () => {
    const port = makeMemoryPort()
    const bridge = createMemoryBridge(port)
    const deps = bridge.wrapDeps(noopDeps)
    const provider = deps.runtimeContextProviders![0]

    await bridge.prepareSend('   ')
    expect(provider()).toBeNull()
  })

  it('persists user / assistant turns via the lifecycle callbacks', () => {
    const port = makeMemoryPort()
    const bridge = createMemoryBridge(port)
    const deps = bridge.wrapDeps(noopDeps)

    deps.onUserMessageAppended!({ messageText: 'hi from user' } as any)
    deps.onAssistantMessageAppended!({ messageText: 'hi from ai' } as any)
    deps.onAssistantTurnReady!({} as any)

    expect(port.ingestUser).toHaveBeenCalledWith('hi from user')
    expect(port.ingestAssistant).toHaveBeenCalledWith('hi from ai')
    expect(port.maybeCompact).toHaveBeenCalledTimes(1)
  })

  it('chains any pre-existing callbacks instead of overwriting them', () => {
    const port = makeMemoryPort()
    const bridge = createMemoryBridge(port)
    const prior = vi.fn()
    const deps = bridge.wrapDeps({ onUserMessageAppended: prior } as any)

    deps.onUserMessageAppended!({ messageText: 'x' } as any)
    expect(prior).toHaveBeenCalled()
    expect(port.ingestUser).toHaveBeenCalledWith('x')
  })
})

describe('createPerformanceBridge', () => {
  it('enterListen on send-start; token stream drives the director; stream end -> silence', () => {
    const director = makeDirector()
    const states: any[] = []
    const bridge = createPerformanceBridge(director as any, s => states.push(s))
    const deps = bridge.wrapDeps(noopDeps)
    const runtime: any = {
      hooks: {
        onTokenSpecial: vi.fn(),
        onTokenLiteral: vi.fn(),
        onStreamEnd: vi.fn(),
      },
    }
    bridge.registerHooks(runtime)

    // Send start -> director enters listen.
    deps.onMessageSendStarted!({} as any)
    expect(director.enterListen).toHaveBeenCalledTimes(1)

    // First streamed literal flips the director into "speak" and is forwarded.
    runtime.hooks.onTokenLiteral.mock.calls[0][0]('i am so happy')
    expect(director.onToken).toHaveBeenCalledWith('i am so happy')

    // A special token applies performance markers.
    runtime.hooks.onTokenSpecial.mock.calls[0][0]('<emotion>happy</emotion>')
    expect(director.applyMarkers).toHaveBeenCalledWith('<emotion>happy</emotion>')

    // Stream end -> director drops into silence.
    runtime.hooks.onStreamEnd.mock.calls[0][0]()
    expect(director.onTurnEnd).toHaveBeenCalledTimes(1)

    // The bridge surfaced every state change to the UI callback.
    expect(states.length).toBeGreaterThan(0)
  })

  it('chains a pre-existing onMessageSendStarted callback', () => {
    const director = makeDirector()
    const bridge = createPerformanceBridge(director as any, () => {})
    const prior = vi.fn()
    const deps = bridge.wrapDeps({ onMessageSendStarted: prior } as any)

    deps.onMessageSendStarted!({} as any)
    expect(prior).toHaveBeenCalled()
    expect(director.enterListen).toHaveBeenCalled()
  })
})

describe('createPerformanceBridge.recordAppliedParams (render receipt)', () => {
  it('(a) empty params → undefined and onRenderReceipt NOT called', () => {
    const onRenderReceipt = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => 's1',
      onRenderReceipt,
    })
    const receipt = bridge.recordAppliedParams({})
    expect(receipt).toBeUndefined()
    expect(onRenderReceipt).not.toHaveBeenCalled()
  })

  it('(b) writes → receipt with incrementing render_ref and hash == fingerprint', () => {
    const onRenderReceipt = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => 's1',
      onRenderReceipt,
    })
    const deps = bridge.wrapDeps(noopDeps)
    // Two send-starts → turnSeq becomes 2.
    deps.onMessageSendStarted!({} as any)
    deps.onMessageSendStarted!({} as any)

    const map: AppliedParams = { 'emotion.preset': 'happy', 'emotion.intensity': 0.5 }
    const r1 = bridge.recordAppliedParams(map)
    expect(r1).toBeDefined()
    expect(r1!.render_ref).toBe('s1#render:2')
    expect(r1!.applied_params_hash).toBe(fingerprintAppliedParams(map))
    expect(onRenderReceipt).toHaveBeenCalledWith(r1)

    // Another send-start → turnSeq becomes 3; render_ref must advance.
    deps.onMessageSendStarted!({} as any)
    const r2 = bridge.recordAppliedParams(map)
    expect(r2!.render_ref).toBe('s1#render:3')
    expect(r2!.render_ref).not.toBe(r1!.render_ref)
  })

  it('(c) assetVersionHash undefined → receipt omits asset_version_hash', () => {
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => 's1',
      getAssetVersionHash: () => undefined,
    })
    bridge.wrapDeps(noopDeps).onMessageSendStarted!({} as any)
    const r = bridge.recordAppliedParams({ 'emotion.preset': 'happy' })
    expect(r).toBeDefined()
    expect('asset_version_hash' in r!).toBe(false)
  })

  it('no active session → silently skipped (cannot mint a stable render_ref)', () => {
    const onRenderReceipt = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => undefined,
      onRenderReceipt,
    })
    bridge.wrapDeps(noopDeps).onMessageSendStarted!({} as any)
    expect(bridge.recordAppliedParams({ 'emotion.preset': 'happy' })).toBeUndefined()
    expect(onRenderReceipt).not.toHaveBeenCalled()
  })
})

describe('createPerformanceBridge — v9 event reporting (Step B closed loop, P0-1)', () => {
  // 报告 P0-1：真实 ref 由 app 层注入；无真实来源 ⇒ 宁缺勿伪造，不发事件。
  const realRefs = {
    getPersonaSnapshotRef: () => 'persona-snapshot-ref-xyz',
    getIntentRef: () => 'performance-intent-abc',
  }

  it('emits persona.render_requested (with real refs) on send-start and lpm.render_ready on render, sharing one trace_id', () => {
    const reportEvent = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => 's1',
      onRenderReceipt: vi.fn(),
      reportEvent,
      ...realRefs,
    })
    const deps = bridge.wrapDeps(noopDeps)
    deps.onMessageSendStarted!({} as any)

    // 请求侧：persona.render_requested，铸造 trace_id；ref 为注入的真实值。
    expect(reportEvent).toHaveBeenCalledTimes(1)
    const reqCall = reportEvent.mock.calls[0][0]
    expect(reqCall.topic).toBe('aijade.persona.render_requested')
    expect(reqCall.trace_id).toBeTruthy()
    expect(reqCall.idempotency_key).toBe('s1#1#request')
    expect(reqCall.payload.persona_snapshot_ref).toBe('persona-snapshot-ref-xyz')
    expect(reqCall.payload.intent_ref).toBe('performance-intent-abc')

    // 回执侧：lpm.render_ready，复用同一 trace_id（配对校验的关键）。
    bridge.recordAppliedParams({ 'emotion.preset': 'happy', 'emotion.intensity': 0.5 })
    expect(reportEvent).toHaveBeenCalledTimes(2)
    const readyCall = reportEvent.mock.calls[1][0]
    expect(readyCall.topic).toBe('aijade.lpm.render_ready')
    expect(readyCall.trace_id).toBe(reqCall.trace_id)
    expect(readyCall.correlation_id).toBe(reqCall.trace_id)
    expect(readyCall.idempotency_key).toBe('s1#s1#render:1')
    expect(readyCall.payload.applied_params_hash).toBe(
      fingerprintAppliedParams({ 'emotion.preset': 'happy', 'emotion.intensity': 0.5 }),
    )
  })

  it('does NOT emit when no real persona/intent ref is available (宁缺勿伪造)', () => {
    const reportEvent = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => 's1',
      onRenderReceipt: vi.fn(),
      reportEvent,
      // 故意不注入 getPersonaSnapshotRef / getIntentRef ⇒ 不伪造、不发事件。
    })
    bridge.wrapDeps(noopDeps).onMessageSendStarted!({} as any)
    expect(reportEvent).not.toHaveBeenCalled()
  })

  it('does NOT emit when there is no active session (cannot mint a stable trace)', () => {
    const reportEvent = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => undefined,
      reportEvent,
      ...realRefs,
    })
    bridge.wrapDeps(noopDeps).onMessageSendStarted!({} as any)
    expect(reportEvent).not.toHaveBeenCalled()
  })

  it('reuses the trace_id across turns so each render pairs with its own request', () => {
    const reportEvent = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => 's1',
      reportEvent,
      ...realRefs,
    })
    const deps = bridge.wrapDeps(noopDeps)
    // Turn 1
    deps.onMessageSendStarted!({} as any)
    const trace1 = reportEvent.mock.calls[0][0].trace_id
    bridge.recordAppliedParams({ 'emotion.preset': 'happy' })
    expect(reportEvent.mock.calls[1][0].trace_id).toBe(trace1)
    // Turn 2 — new trace, must differ from turn 1.
    deps.onMessageSendStarted!({} as any)
    const trace2 = reportEvent.mock.calls[2][0].trace_id
    expect(trace2).not.toBe(trace1)
    bridge.recordAppliedParams({ 'emotion.preset': 'sad' })
    expect(reportEvent.mock.calls[3][0].trace_id).toBe(trace2)
  })

  it('same-turn request and render share one trace_id and carry real refs (projection pairing key)', () => {
    const reportEvent = vi.fn()
    const bridge = createPerformanceBridge(makeDirector() as any, () => {}, {
      getSessionId: () => 's1',
      onRenderReceipt: vi.fn(),
      reportEvent,
      ...realRefs,
    })
    const deps = bridge.wrapDeps(noopDeps)
    deps.onMessageSendStarted!({} as any)
    expect(reportEvent).toHaveBeenCalledTimes(1)
    const reqCall = reportEvent.mock.calls[0][0]
    expect(reqCall.payload.persona_snapshot_ref).toBe('persona-snapshot-ref-xyz')
    expect(reqCall.payload.intent_ref).toBe('performance-intent-abc')
    bridge.recordAppliedParams({ 'emotion.preset': 'happy', 'emotion.intensity': 0.5 })
    const readyCall = reportEvent.mock.calls[1][0]
    // 配对键是 trace_id（不是 intent_ref === render_ref）；两者都真实存在即可投影为 paired。
    expect(readyCall.trace_id).toBe(reqCall.trace_id)
    expect(readyCall.payload.render_ref).toBeTruthy()
  })
})
