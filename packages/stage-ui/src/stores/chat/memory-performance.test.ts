import { ContextUpdateStrategy } from '@proj-aijade/server-sdk'
import { describe, expect, it, vi } from 'vitest'

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
