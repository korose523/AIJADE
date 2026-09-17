import { describe, expect, it, vi } from 'vitest'

import {
  buildAuthorizationUrl,
  buildExtensionRedirectUri,
  exchangeCodeForTokens,
  EXTENSION_OIDC_CLIENT_ID,
  fetchOidcTokens,
  refreshAccessToken,
  runAuthorizationFlow,
} from './oidc'

const AUTH_BASE = 'http://localhost:6121'
const REDIRECT = 'chrome-extension://abcxyz/auth/callback'

// 固定 PKCE 材料，便于断言回调解析与 code_verifier 透传。
const VERIFIER = 'verifier-fixed-0123456789-abcdefghijklmnopqrstuvwxyz-0123456789-ABCDEFGHIJKL'
const STATE = 'state-fixed-value-0123456789-abcdefghij'

describe('buildExtensionRedirectUri', () => {
  it('构造 chrome-extension://<id>/auth/callback', () => {
    expect(buildExtensionRedirectUri('ext123')).toBe('chrome-extension://ext123/auth/callback')
  })
})

describe('buildAuthorizationUrl', () => {
  it('参数齐全且包含 resource=authBaseUrl、client_id 固定为扩展客户端', async () => {
    const { url } = await buildAuthorizationUrl({ authBaseUrl: AUTH_BASE, redirectUri: REDIRECT })
    const u = new URL(url)
    expect(u.pathname).toBe('/api/auth/oauth2/authorize')
    expect(u.searchParams.get('response_type')).toBe('code')
    expect(u.searchParams.get('client_id')).toBe(EXTENSION_OIDC_CLIENT_ID)
    expect(u.searchParams.get('client_id')).toBe('aijade-web-extension')
    expect(u.searchParams.get('redirect_uri')).toBe(REDIRECT)
    expect(u.searchParams.get('scope')).toBe('openid profile email offline_access')
    expect(u.searchParams.get('code_challenge_method')).toBe('S256')
    expect(u.searchParams.get('resource')).toBe(AUTH_BASE)
    expect(u.searchParams.get('state')?.length).toBeGreaterThan(0)
    expect(u.searchParams.get('code_challenge')?.length).toBeGreaterThan(0)
  })
})

describe('runAuthorizationFlow', () => {
  it('state 不匹配 ⇒ 返回 state_mismatch（CSRF，绝不静默继续）', async () => {
    // 回调里塞一个与我们生成的 state 不同的 state。
    const cb = new URL(REDIRECT)
    cb.searchParams.set('code', 'CODE123')
    cb.searchParams.set('state', 'attacker-state')
    const launch = vi.fn(async () => cb.toString())
    const result = await runAuthorizationFlow({
      authBaseUrl: AUTH_BASE,
      redirectUri: REDIRECT,
      launchWebAuthFlow: launch,
      state: STATE,
    })
    expect(result.ok).toBe(false)
    if (!result.ok)
      expect(result.kind).toBe('state_mismatch')
    expect(launch).toHaveBeenCalledTimes(1)
  })

  it('state 匹配 ⇒ 返回 code 与 flowState（成功解析）', async () => {
    const cb = new URL(REDIRECT)
    cb.searchParams.set('code', 'CODE123')
    cb.searchParams.set('state', STATE)
    const result = await runAuthorizationFlow({
      authBaseUrl: AUTH_BASE,
      redirectUri: REDIRECT,
      launchWebAuthFlow: async () => cb.toString(),
      state: STATE,
    })
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.code).toBe('CODE123')
      expect(result.flowState.state).toBe(STATE)
    }
  })

  it('用户关闭窗口（launch 返回 undefined）⇒ cancelled，不当成成功', async () => {
    const result = await runAuthorizationFlow({
      authBaseUrl: AUTH_BASE,
      redirectUri: REDIRECT,
      launchWebAuthFlow: async () => undefined,
    })
    expect(result.ok).toBe(false)
    if (!result.ok)
      expect(result.kind).toBe('cancelled')
  })

  it('用户拒绝授权（error=access_denied）⇒ denied', async () => {
    const cb = new URL(REDIRECT)
    cb.searchParams.set('error', 'access_denied')
    cb.searchParams.set('state', STATE)
    const result = await runAuthorizationFlow({
      authBaseUrl: AUTH_BASE,
      redirectUri: REDIRECT,
      launchWebAuthFlow: async () => cb.toString(),
      state: STATE,
    })
    expect(result.ok).toBe(false)
    if (!result.ok)
      expect(result.kind).toBe('denied')
  })
})

describe('exchangeCodeForTokens', () => {
  it('成功返回令牌，且请求体不带 client_secret（public client）', async () => {
    const flowState = { codeVerifier: VERIFIER, state: STATE, redirectUri: REDIRECT }
    let bodyText = ''
    const fetchImpl = vi.fn(async (_u: string, init: RequestInit) => {
      bodyText = init.body as string
      return {
        ok: true,
        status: 200,
        json: async () => ({ access_token: 'AT', refresh_token: 'RT', expires_in: 3600 }),
      }
    }) as unknown as typeof fetch

    const res = await exchangeCodeForTokens({ authBaseUrl: AUTH_BASE, code: 'CODE123', flowState, redirectUri: REDIRECT, fetchImpl })
    expect(res.ok).toBe(true)
    if (res.ok) {
      expect(res.accessToken).toBe('AT')
      expect(res.refreshToken).toBe('RT')
      expect(res.expiresIn).toBe(3600)
    }
    const params = new URLSearchParams(bodyText)
    expect(params.get('client_secret')).toBeNull()
    expect(params.get('client_id')).toBe('aijade-web-extension')
    expect(params.get('grant_type')).toBe('authorization_code')
    expect(params.get('code_verifier')).toBe(VERIFIER)
    expect(params.get('resource')).toBe(AUTH_BASE)
  })

  it('invalid_client ⇒ kind 为 invalid_client（部署配置问题，须与 unauthorized 区分）', async () => {
    const flowState = { codeVerifier: VERIFIER, state: STATE, redirectUri: REDIRECT }
    const fetchImpl = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: 'invalid_client', error_description: 'Client not registered' }),
      text: async () => '{"error":"invalid_client"}',
    })) as unknown as typeof fetch
    const res = await exchangeCodeForTokens({ authBaseUrl: AUTH_BASE, code: 'CODE123', flowState, redirectUri: REDIRECT, fetchImpl })
    expect(res.ok).toBe(false)
    if (!res.ok) {
      expect(res.kind).toBe('invalid_client')
      expect(res.kind).not.toBe('unauthorized')
    }
  })

  it('invalid_grant（code 失效）⇒ 归为 unauthorized', async () => {
    const flowState = { codeVerifier: VERIFIER, state: STATE, redirectUri: REDIRECT }
    const fetchImpl = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: 'invalid_grant' }),
      text: async () => '{"error":"invalid_grant"}',
    })) as unknown as typeof fetch
    const res = await exchangeCodeForTokens({ authBaseUrl: AUTH_BASE, code: 'BAD', flowState, redirectUri: REDIRECT, fetchImpl })
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.kind).toBe('unauthorized')
  })
})

describe('refreshAccessToken', () => {
  it('成功续期且不带 client_secret', async () => {
    let bodyText = ''
    const fetchImpl = vi.fn(async (_u: string, init: RequestInit) => {
      bodyText = init.body as string
      return { ok: true, status: 200, json: async () => ({ access_token: 'AT2', refresh_token: 'RT2', expires_in: 3600 }) }
    }) as unknown as typeof fetch
    const res = await refreshAccessToken({ authBaseUrl: AUTH_BASE, refreshToken: 'RT', fetchImpl })
    expect(res.ok).toBe(true)
    if (res.ok)
      expect(res.accessToken).toBe('AT2')
    const params = new URLSearchParams(bodyText)
    expect(params.get('client_secret')).toBeNull()
    expect(params.get('grant_type')).toBe('refresh_token')
    expect(params.get('client_id')).toBe('aijade-web-extension')
  })

  it('refresh 返回 invalid_client ⇒ kind invalid_client', async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: 'invalid_client' }),
      text: async () => '{"error":"invalid_client"}',
    })) as unknown as typeof fetch
    const res = await refreshAccessToken({ authBaseUrl: AUTH_BASE, refreshToken: 'RT', fetchImpl })
    expect(res.ok).toBe(false)
    if (!res.ok)
      expect(res.kind).toBe('invalid_client')
  })
})

describe('fetchOidcTokens（门面）', () => {
  it('用户取消 ⇒ cancelled，且不发起换码请求（不写 token）', async () => {
    const exchangeFetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) })) as unknown as typeof fetch
    const result = await fetchOidcTokens({
      authBaseUrl: AUTH_BASE,
      redirectUri: REDIRECT,
      launchWebAuthFlow: async () => undefined,
      fetchImpl: exchangeFetch,
    })
    expect(result.ok).toBe(false)
    if (!result.ok)
      expect(result.kind).toBe('cancelled')
    expect(exchangeFetch).not.toHaveBeenCalled()
  })

  it('服务端 invalid_client ⇒ kind invalid_client，与 unauthorized 区分开', async () => {
    const cb = new URL(REDIRECT)
    cb.searchParams.set('code', 'CODE123')
    cb.searchParams.set('state', STATE)
    const exchangeFetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ error: 'invalid_client' }),
      text: async () => '{"error":"invalid_client"}',
    })) as unknown as typeof fetch
    const result = await fetchOidcTokens({
      authBaseUrl: AUTH_BASE,
      redirectUri: REDIRECT,
      launchWebAuthFlow: async () => cb.toString(),
      fetchImpl: exchangeFetch,
      state: STATE,
    })
    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.kind).toBe('invalid_client')
      expect(result.kind).not.toBe('unauthorized')
    }
  })

  it('完整成功：授权回调 → 换码 → 返回 access/refresh/expiresAt', async () => {
    const cb = new URL(REDIRECT)
    cb.searchParams.set('code', 'CODE123')
    cb.searchParams.set('state', STATE)
    const exchangeFetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ access_token: 'AT', refresh_token: 'RT', expires_in: 3600 }),
    })) as unknown as typeof fetch
    const result = await fetchOidcTokens({
      authBaseUrl: AUTH_BASE,
      redirectUri: REDIRECT,
      launchWebAuthFlow: async () => cb.toString(),
      fetchImpl: exchangeFetch,
      state: STATE,
    })
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.accessToken).toBe('AT')
      expect(result.refreshToken).toBe('RT')
      expect(result.expiresAt).toBeGreaterThan(Date.now())
    }
  })
})
