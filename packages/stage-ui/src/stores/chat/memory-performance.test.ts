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
