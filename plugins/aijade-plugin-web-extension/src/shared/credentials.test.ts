import type { OidcTokenSet } from './oidc'
import type { ExtensionSettings } from './types'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { resolveApiToken, resolveApiTokenFresh, setActiveOidcTokens } from './credentials'
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

describe('resolveApiToken — OIDC access token 优先于配置的 bearerToken', () => {
  beforeEach(() => {
    setActiveOidcTokens(null)
  })

  function freshTokens(over: Partial<OidcTokenSet> = {}): OidcTokenSet {
    return { accessToken: 'oidc-at', refreshToken: 'oidc-rt', expiresAt: Date.now() + 600_000, ...over }
  }

  it('有新鲜 OIDC token 时，resolveApiToken 返回 OIDC access token（而非 bearerToken）', () => {
    setActiveOidcTokens(freshTokens())
    const s = settingsWith({ bearerToken: 'bearer-fallback' })
    expect(resolveApiToken(s)).toBe('oidc-at')
  })

  it('oIDC token 过期时回落到 bearerToken（绝不静默发过期 token）', () => {
    setActiveOidcTokens(freshTokens({ expiresAt: Date.now() - 1000 }))
    const s = settingsWith({ bearerToken: 'bearer-fallback' })
    expect(resolveApiToken(s, Date.now())).toBe('bearer-fallback')
  })

  it('两层真源：设置 OIDC token 后，v10 REST 与 LLM 两条通道都发同一个 OIDC access token', async () => {
    setActiveOidcTokens(freshTokens())
    const s = settingsWith({ bearerToken: 'bearer-ignored' })
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

    await postV9Event(s.restBaseUrl, buildV9EventEnvelope({ evidence: reducePageToEvidence(pagePayload)!, tick: 1 }), { token: apiToken, fetchImpl: v9Fetch })
    globalThis.fetch = llmFetch
    await chatCompletion(s.llmBaseUrl!, { messages: [{ role: 'user', content: 'x' }], token: apiToken })

    // 两条通道都发出 OIDC access token（来自 OIDC，不是 bearerToken）。
    expect(v9Headers.authorization).toBe('Bearer oidc-at')
    expect(llmHeaders.authorization).toBe('Bearer oidc-at')

    // 改 OIDC token → 两通道都变（证明是同一个真源）。
    setActiveOidcTokens(freshTokens({ accessToken: 'oidc-at-2' }))
    const apiToken2 = resolveApiToken(s)!
    const v9Headers2: Record<string, string> = {}
    const v9Fetch2 = vi.fn(async (_u: string, init: RequestInit) => {
      Object.assign(v9Headers2, init.headers as Record<string, string>)
      return { status: 201, json: async () => ({ ok: true }) }
    }) as unknown as typeof fetch
    const llmHeaders2: Record<string, string> = {}
    const llmFetch2 = vi.fn(async (_u: string, init: RequestInit) => {
      Object.assign(llmHeaders2, init.headers as Record<string, string>)
      return { status: 200, json: async () => ({ choices: [{ message: { content: 'hi' } }] }) }
    }) as unknown as typeof fetch
    await postV9Event(s.restBaseUrl, buildV9EventEnvelope({ evidence: reducePageToEvidence(pagePayload)!, tick: 2 }), { token: apiToken2, fetchImpl: v9Fetch2 })
    globalThis.fetch = llmFetch2
    await chatCompletion(s.llmBaseUrl!, { messages: [{ role: 'user', content: 'x' }], token: apiToken2 })
    expect(v9Headers2.authorization).toBe('Bearer oidc-at-2')
    expect(llmHeaders2.authorization).toBe('Bearer oidc-at-2')
  })
})

describe('resolveApiTokenFresh — 过期续期与诚实降级', () => {
  beforeEach(() => {
    setActiveOidcTokens(null)
  })

  function okTokenFetch(accessToken = 'new-at') {
    return vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ access_token: accessToken, refresh_token: 'new-rt', expires_in: 3600 }),
    })) as unknown as typeof fetch
  }

  function failTokenFetch(error = 'invalid_client', status = 400) {
    return vi.fn(async () => ({
      ok: false,
      status,
      json: async () => ({ error }),
      text: async () => JSON.stringify({ error }),
    })) as unknown as typeof fetch
  }

  it('oIDC 新鲜 → 直接返回 source:oidc', async () => {
    setActiveOidcTokens({ accessToken: 'at', refreshToken: 'rt', expiresAt: Date.now() + 600_000 })
    const res = await resolveApiTokenFresh(settingsWith({}), { authBaseUrl: AUTH_BASE })
    expect(res.ok).toBe(true)
    if (res.ok)
      expect(res.source).toBe('oidc')
  })

  it('oIDC 过期 + 有 refresh → 触发续期，返回新 token 并回调 onRefreshed', async () => {
    setActiveOidcTokens({ accessToken: 'old-at', refreshToken: 'rt', expiresAt: Date.now() - 1000 })
    let saved: OidcTokenSet | null = null
    const res = await resolveApiTokenFresh(settingsWith({}), {
      authBaseUrl: AUTH_BASE,
      fetchImpl: okTokenFetch('refreshed-at'),
      onRefreshed: (t) => { saved = t },
    })
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.token).toBe('refreshed-at')
      expect(res.source).toBe('oidc')
    }
    expect(saved).not.toBeNull()
    expect(saved!.accessToken).toBe('refreshed-at')
  })

  it('oIDC 过期 + refresh 失败(invalid_client) → requires_relogin，绝不返回旧 token', async () => {
    setActiveOidcTokens({ accessToken: 'old-at', refreshToken: 'rt', expiresAt: Date.now() - 1000 })
    const res = await resolveApiTokenFresh(settingsWith({}), {
      authBaseUrl: AUTH_BASE,
      fetchImpl: failTokenFetch('invalid_client'),
    })
    expect(res.ok).toBe(false)
    if (!res.ok) {
      expect(res.kind).toBe('requires_relogin')
      expect(res.message).not.toContain('old-at')
    }
  })

  it('无任何凭据（无 OIDC 且未配 bearer）→ unauthorized（信息上区分"未配置"）', async () => {
    setActiveOidcTokens(null)
    const res = await resolveApiTokenFresh(settingsWith({ bearerToken: '' }), { authBaseUrl: AUTH_BASE })
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.kind).toBe('unauthorized')
  })

  it('无 OIDC 但配了 bearer → 回退到 bearer（source:bearer）', async () => {
    setActiveOidcTokens(null)
    const res = await resolveApiTokenFresh(settingsWith({ bearerToken: 'bearer-x' }), { authBaseUrl: AUTH_BASE })
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.token).toBe('bearer-x')
      expect(res.source).toBe('bearer')
    }
  })
})

const AUTH_BASE = 'http://localhost:6121'

beforeEach(() => {
  vi.restoreAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})
