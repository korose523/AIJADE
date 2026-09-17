import type { ExtensionSettings } from './types'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resolveApiToken } from './credentials'
import { chatCompletion } from './llm'
import { reducePageToEvidence } from './v10-evidence'
import { buildV9EventEnvelope, postV9Event } from './v9-rest'

const pagePayload = {
  site: 'youtube' as const,
  url: 'https://example.test/article',
  title: 'A title',
  description: 'A summary',
}

function settingsWith(over: Partial<ExtensionSettings>): ExtensionSettings {
  return {
    wsUrl: 'ws://localhost:6121/ws',
    token: '',
    restBaseUrl: 'http://localhost:6121',
    bearerToken: '',
    llmBaseUrl: 'http://localhost:6121',
    llmModel: 'auto',
    enabled: true,
    sendPageContext: true,
    sendVideoContext: true,
    sendSubtitles: true,
    sendSparkNotify: true,
    enableVision: false,
    ...over,
  }
}

describe('resolveApiToken — REST + LLM 通道的唯一凭据真源', () => {
  it('返回 bearerToken 的值，而非 WS 的 token', () => {
    const s = settingsWith({ bearerToken: 'shared', token: 'ws-different' })
    expect(resolveApiToken(s)).toBe('shared')
  })

  it('bearerToken 为空时返回 undefined（未配置凭据）', () => {
    const s = settingsWith({ bearerToken: '', token: 'ws-only' })
    expect(resolveApiToken(s)).toBeUndefined()
  })

  it('v10 REST 与 LLM 两条通道都由 resolveApiToken 的同一个值驱动', async () => {
    const s = settingsWith({ bearerToken: 'shared-secret' })
    const apiToken = resolveApiToken(s)!

    const v9Headers: Record<string, string> = {}
    const v9Fetch = vi.fn(async (_u: string, init: RequestInit) => {
      Object.assign(v9Headers, init.headers as Record<string, string>)
      return { status: 201, json: async () => ({ ok: true, deduped: false, eventId: 'x' }) }
    }) as unknown as typeof fetch

    const llmHeaders: Record<string, string> = {}
    const llmFetch = vi.fn(async (_u: string, init: RequestInit) => {
      Object.assign(llmHeaders, init.headers as Record<string, string>)
      return { status: 200, json: async () => ({ choices: [{ message: { content: 'hi' } }] }) }
    }) as unknown as typeof fetch

    await postV9Event(
      s.restBaseUrl,
      buildV9EventEnvelope({ evidence: reducePageToEvidence(pagePayload)!, tick: 1 }),
      { token: apiToken, fetchImpl: v9Fetch },
    )
    globalThis.fetch = llmFetch
    await chatCompletion(s.llmBaseUrl!, { messages: [{ role: 'user', content: 'x' }], token: apiToken })

    // 两条通道都发出了同一个 Bearer 值；且都来自 bearerToken，不是 ws token。
    expect(v9Headers.authorization).toBe('Bearer shared-secret')
    expect(llmHeaders.authorization).toBe('Bearer shared-secret')
  })

  it('改 bearerToken → 两通道都变；改 WS token → 两通道都不受影响', async () => {
    const a = settingsWith({ bearerToken: 'A' })
    const b = settingsWith({ bearerToken: 'B', token: 'different-ws' })
    expect(resolveApiToken(a)).toBe('A')
    expect(resolveApiToken(b)).toBe('B')
    // WS 的 token 字段绝不进入这两条 HTTP 通道。
    const wsOnly = settingsWith({ bearerToken: '', token: 'ws-only' })
    expect(resolveApiToken(wsOnly)).toBeUndefined()
  })
})

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})
