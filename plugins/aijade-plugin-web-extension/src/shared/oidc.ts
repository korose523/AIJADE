/**
 * 浏览器扩展的 OIDC Authorization Code + PKCE 客户端（生产凭据链）。
 *
 * 对接服务端 OIDC provider（`@better-auth/oauth-provider`）：
 *   authorize `=/api/auth/oauth2/authorize`
 *   token     `=/api/auth/oauth2/token`
 *
 * 对接契约（逐字照 `packages/stage-ui/src/libs/auth-oidc.ts` 的参考实现）：
 *   - authorize 参数：`response_type=code` `client_id` `redirect_uri` `scope`
 *     `state` `code_challenge` `code_challenge_method=S256` **`resource=<SERVER_URL>`**
 *   - token 交换：`application/x-www-form-urlencoded`，字段
 *     `grant_type` `code` `redirect_uri` `client_id` `code_verifier` `resource`
 *   - refresh：`grant_type=refresh_token` `refresh_token` `client_id` `resource`
 *
 * 客户端契约（由"另一个 worker"在服务端注册，本插件不可改）：
 *   client_id = 'aijade-web-extension'，**public client**
 *   （`tokenEndpointAuthMethod: 'none'`，**无 client_secret**，仅 PKCE），
 *   `requirePKCE: true`，redirect URI = `chrome-extension://<id>/auth/callback`，
 *   scopes `openid profile email offline_access`，grant types
 *   `authorization_code refresh_token`。
 *
 * 本模块**纯逻辑 + 可注入依赖**：`launchWebAuthFlow` 与 `fetchImpl` 都可在测试中注入替身，
 * 因此 `chrome.identity` / 网络在 node 测试里都不需要真实存在。
 */

import { generateCodeChallenge, generateCodeVerifier, generateState } from './pkce'

/** 扩展持有的 OIDC 令牌集（持久化 + 内存热身）。 */
export interface OidcTokenSet {
  accessToken: string
  refreshToken?: string
  /** 过期时间（epoch ms）。由 `expiresIn` 换算。 */
  expiresAt: number
}

export const EXTENSION_OIDC_CLIENT_ID = 'aijade-web-extension'

const OIDC_AUTHORIZE_PATH = '/api/auth/oauth2/authorize'
const OIDC_TOKEN_PATH = '/api/auth/oauth2/token'

const DEFAULT_SCOPES = ['openid', 'profile', 'email', 'offline_access']

/** `chrome-extension://<id>/auth/callback` */
export function buildExtensionRedirectUri(extensionId: string): string {
  return `chrome-extension://${extensionId}/auth/callback`
}

export interface OidcFlowState {
  codeVerifier: string
  state: string
  redirectUri: string
}

export interface BuildAuthorizationUrlParams {
  authBaseUrl: string
  redirectUri: string
  scopes?: string[]
  /** 注入：测试可固定 verifier / challenge / state 以断言回调解析。 */
  codeVerifier?: string
  codeChallenge?: string
  state?: string
}

export interface AuthorizationUrlResult {
  url: string
  flowState: OidcFlowState
}

/**
 * 构造授权 URL，并返回必须持久化到回调抵达前的 PKCE flow state。
 * `resource` 设为 `authBaseUrl`（即服务端 `${API_SERVER_URL}`），与参考实现一致。
 */
export async function buildAuthorizationUrl(
  params: BuildAuthorizationUrlParams,
): Promise<AuthorizationUrlResult> {
  const codeVerifier = params.codeVerifier ?? generateCodeVerifier()
  const codeChallenge = params.codeChallenge ?? await generateCodeChallenge(codeVerifier)
  const state = params.state ?? generateState()
  const scopes = params.scopes ?? DEFAULT_SCOPES

  const url = new URL(OIDC_AUTHORIZE_PATH, params.authBaseUrl)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('client_id', EXTENSION_OIDC_CLIENT_ID)
  url.searchParams.set('redirect_uri', params.redirectUri)
  url.searchParams.set('scope', scopes.join(' '))
  url.searchParams.set('state', state)
  url.searchParams.set('code_challenge', codeChallenge)
  url.searchParams.set('code_challenge_method', 'S256')
  url.searchParams.set('resource', params.authBaseUrl)

  return {
    url: url.toString(),
    flowState: { codeVerifier, state, redirectUri: params.redirectUri },
  }
}

export type AuthorizationFlowKind
  = | 'cancelled' // 用户关闭窗口 / 取消
    | 'state_mismatch' // CSRF
    | 'denied' // 服务端在回调里回 `error=`（用户拒绝授权）
    | 'malformed' // 回调缺 code

export type AuthorizationFlowResult
  = | { ok: true, code: string, flowState: OidcFlowState }
    | { ok: false, kind: AuthorizationFlowKind, message: string }

export interface RunAuthorizationFlowParams {
  authBaseUrl: string
  redirectUri: string
  scopes?: string[]
  /** 注入替身：默认用 `chrome.identity.launchWebAuthFlow`。 */
  launchWebAuthFlow?: (url: string, interactive: boolean) => Promise<string | undefined>
  /** 注入固定 PKCE 材料（测试用）。 */
  codeVerifier?: string
  codeChallenge?: string
  state?: string
}

function defaultLaunchWebAuthFlow(url: string, _interactive: boolean): Promise<string | undefined> {
  return new Promise((resolve) => {
    // `browser` 在扩展运行时存在；node 测试一律注入替身，不会走到这里。
    browser.identity.launchWebAuthFlow({ url, interactive: true }, (responseUrl?: string) => {
      const lastError = browser.runtime.lastError
      if (lastError || !responseUrl) {
        resolve(undefined)
        return
      }
      resolve(responseUrl)
    })
  })
}

/**
 * 用 `chrome.identity.launchWebAuthFlow` 打开授权页，从返回的 redirect URL 解析 `code` 与 `state`。
 *
 * - `state` 不匹配 ⇒ **抛错/返回 `state_mismatch`**（CSRF，绝不静默继续）。
 * - `error=` 查询参数（用户拒绝授权）⇒ 返回可辨识的 `denied` 错误。
 * - 用户关闭窗口 ⇒ `launchWebAuthFlow` 返回 undefined ⇒ 归类为 `cancelled`，**不当成成功**。
 */
export async function runAuthorizationFlow(
  params: RunAuthorizationFlowParams,
): Promise<AuthorizationFlowResult> {
  const { url, flowState } = await buildAuthorizationUrl({
    authBaseUrl: params.authBaseUrl,
    redirectUri: params.redirectUri,
    scopes: params.scopes,
    codeVerifier: params.codeVerifier,
    codeChallenge: params.codeChallenge,
    state: params.state,
  })

  const launch = params.launchWebAuthFlow ?? defaultLaunchWebAuthFlow

  let responseUrl: string | undefined
  try {
    responseUrl = await launch(url, true)
  }
  catch {
    // `chrome.identity` 在用户取消时可能直接抛错。
    return { ok: false, kind: 'cancelled', message: 'Authorization flow cancelled by user.' }
  }

  if (!responseUrl)
    return { ok: false, kind: 'cancelled', message: 'Authorization flow returned no redirect URL (likely cancelled).' }

  const parsed = new URL(responseUrl)
  const error = parsed.searchParams.get('error')
  if (error)
    return { ok: false, kind: 'denied', message: `Authorization server returned error: ${error}` }

  const code = parsed.searchParams.get('code')
  const returnedState = parsed.searchParams.get('state')

  if (!code)
    return { ok: false, kind: 'malformed', message: 'No authorization code present in the redirect URL.' }

  if (returnedState !== flowState.state)
    return { ok: false, kind: 'state_mismatch', message: 'OIDC state mismatch — possible CSRF attack.' }

  return { ok: true, code, flowState }
}

export type TokenErrorKind
  = | 'invalid_client' // 客户端未注册（部署配置问题，与"用户没登录"完全不同）
    | 'unauthorized' // 用户未登录 / 凭据被拒（invalid_grant / access_denied 等）
    | 'network'
    | 'malformed'

export type TokenExchangeResult
  = | {
    ok: true
    accessToken: string
    refreshToken?: string
    expiresIn: number
    idToken?: string
    scope?: string
  }
  | { ok: false, kind: TokenErrorKind, message: string, status?: number }

export interface ExchangeParams {
  authBaseUrl: string
  code: string
  flowState: OidcFlowState
  redirectUri: string
  fetchImpl?: typeof fetch
}

function classifyTokenError(status: number, body: string): { kind: TokenErrorKind, message: string } {
  let errorCode = ''
  try {
    const j = JSON.parse(body) as { error?: string }
    if (typeof j.error === 'string')
      errorCode = j.error
  }
  catch {
    // 非 JSON 错误体：保留原始文本。
  }

  if (errorCode === 'invalid_client' || errorCode === 'unauthorized_client')
    return { kind: 'invalid_client', message: body }
  // invalid_grant（code 失效/被用）/ access_denied 等：归为"用户未登录/被拒"。
  if (status === 401 || status === 400)
    return { kind: 'unauthorized', message: body }
  return { kind: 'malformed', message: body }
}

async function postTokenEndpoint(
  authBaseUrl: string,
  body: URLSearchParams,
  fetchImpl?: typeof fetch,
): Promise<TokenExchangeResult> {
  const fetchFn = fetchImpl ?? globalThis.fetch
  let response: Response
  try {
    response = await fetchFn(new URL(OIDC_TOKEN_PATH, authBaseUrl), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    })
  }
  catch (err) {
    return { ok: false, kind: 'network', message: err instanceof Error ? err.message : String(err) }
  }

  if (response.ok) {
    const data = (await response.json().catch(() => null)) as Record<string, unknown> | null
    if (!data || typeof data.access_token !== 'string')
      return { ok: false, kind: 'malformed', message: 'Token response missing access_token.' }
    return {
      ok: true,
      accessToken: data.access_token,
      refreshToken: typeof data.refresh_token === 'string' ? data.refresh_token : undefined,
      expiresIn: typeof data.expires_in === 'number' ? data.expires_in : 0,
      idToken: typeof data.id_token === 'string' ? data.id_token : undefined,
      scope: typeof data.scope === 'string' ? data.scope : undefined,
    }
  }

  const text = await response.text().catch(() => '')
  const { kind, message } = classifyTokenError(response.status, text)
  return { ok: false, kind, message, status: response.status }
}

/** 用授权码交换令牌（RFC 6749 §4.1.3）。**不带 client_secret**（public client）。 */
export async function exchangeCodeForTokens(params: ExchangeParams): Promise<TokenExchangeResult> {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    code: params.code,
    redirect_uri: params.redirectUri,
    client_id: EXTENSION_OIDC_CLIENT_ID,
    code_verifier: params.flowState.codeVerifier,
    resource: params.authBaseUrl,
  })
  return postTokenEndpoint(params.authBaseUrl, body, params.fetchImpl)
}

/** 用 refresh token 续期（RFC 6749 §6）。同样不带 client_secret。 */
export async function refreshAccessToken(params: {
  authBaseUrl: string
  refreshToken: string
  fetchImpl?: typeof fetch
}): Promise<TokenExchangeResult> {
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    refresh_token: params.refreshToken,
    client_id: EXTENSION_OIDC_CLIENT_ID,
    resource: params.authBaseUrl,
  })
  return postTokenEndpoint(params.authBaseUrl, body, params.fetchImpl)
}

export type FetchOidcTokensKind
  = | 'cancelled'
    | 'state_mismatch'
    | 'invalid_client'
    | 'unauthorized'
    | 'network'
    | 'malformed'

export type FetchOidcTokensResult
  = | { ok: true, accessToken: string, refreshToken?: string, expiresAt: number }
    | { ok: false, kind: FetchOidcTokensKind, message: string }

export interface FetchOidcTokensParams {
  authBaseUrl: string
  redirectUri: string
  scopes?: string[]
  launchWebAuthFlow?: (url: string, interactive: boolean) => Promise<string | undefined>
  fetchImpl?: typeof fetch
  codeVerifier?: string
  codeChallenge?: string
  state?: string
}

/**
 * 门面：把"授权流 + 换码"串起来，返回统一可判别的结果。
 * `kind` 区分部署问题（`invalid_client`）与用户问题（`cancelled` / `unauthorized`），
 * 调用方据此决定"报错给运维"还是"提示用户重新登录"。
 */
export async function fetchOidcTokens(params: FetchOidcTokensParams): Promise<FetchOidcTokensResult> {
  const flow = await runAuthorizationFlow({
    authBaseUrl: params.authBaseUrl,
    redirectUri: params.redirectUri,
    scopes: params.scopes,
    launchWebAuthFlow: params.launchWebAuthFlow,
    codeVerifier: params.codeVerifier,
    codeChallenge: params.codeChallenge,
    state: params.state,
  })

  if (!flow.ok) {
    // `runAuthorizationFlow` 的 `denied`（用户拒绝授权）在门面层折叠为 `unauthorized`。
    const kind: FetchOidcTokensKind = flow.kind === 'denied' ? 'unauthorized' : flow.kind
    return { ok: false, kind, message: flow.message }
  }

  const exchanged = await exchangeCodeForTokens({
    authBaseUrl: params.authBaseUrl,
    code: flow.code,
    flowState: flow.flowState,
    redirectUri: params.redirectUri,
    fetchImpl: params.fetchImpl,
  })

  if (!exchanged.ok)
    return { ok: false, kind: exchanged.kind, message: exchanged.message }

  const now = Date.now()
  return {
    ok: true,
    accessToken: exchanged.accessToken,
    refreshToken: exchanged.refreshToken,
    expiresAt: now + exchanged.expiresIn * 1000,
  }
}
