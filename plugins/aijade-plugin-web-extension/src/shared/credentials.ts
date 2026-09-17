import type { OidcTokenSet } from './oidc'
import type { ExtensionSettings } from './types'

import { refreshAccessToken } from './oidc'

/**
 * 扩展两条 HTTP 通道（v10 REST 事件上报 `postV9Event` 与 LLM 摘要 `chatCompletion`）
 * 共用的**唯一** Bearer 凭据来源。
 *
 * 凭据优先级链（从新到旧，生产优先）：
 *
 * 1. **OIDC access token（生产路径）**——由本插件通过 PKCE 授权码流程
 *    （见 `oidc.ts` 的 `fetchOidcTokens`）向服务端 OIDC provider 换取，落在
 *    `chrome-extension://<id>/auth/callback` 回调、写入持久化存储。服务端
 *    `resolveRequestAuth` 的 JWT 分支（`createRemoteJWKSet` + 校验 issuer/audience）
 *    **已经能用**，缺口只是扩展此前从未注册成 OIDC 客户端、也从未实现授权流程——
 *    本文件与 `oidc.ts` / popup 登录入口补齐了这一环。
 *    access token 过期时优先用 refresh token 续期（见 `resolveApiTokenFresh`）；
 *    续期失败则明确降级为"需重新登录"，**绝不**静默发过期 token。
 *
 * 2. 设置里显式配置的 `bearerToken`（dev / 调试用，对应服务端 `TEST_AUTH_TOKEN`
 *    或未来的扩展令牌签发端点；绝不在代码里硬编码）。
 *
 * 为什么是 Bearer、且只有这一条真源：
 * better-auth 会话 cookie 在扩展里根本不可行（跨源 cookie jar 隔离，见旧注释），
 * 故两条通道都必须从这里读**同一个**值，绝不允许各自引用独立字段。
 * `makeLlm` 与 `reportV9Observation` 都调用本文件的函数。
 */

/** 距过期前多少 ms 就视为"即将过期"并触发刷新。 */
export const OIDC_EXPIRY_SKEW_MS = 30_000

// 内存持热：登录/刷新成功后由 background 写入，供同步 `resolveApiToken` 立即取用。
let activeOidc: OidcTokenSet | null = null

/** 写入当前生效的 OIDC 令牌集（登录/刷新成功后调用；登出传 null）。 */
export function setActiveOidcTokens(tokens: OidcTokenSet | null): void {
  activeOidc = tokens
}

/** 读取当前生效的 OIDC 令牌集（无则 null）。 */
export function getActiveOidcTokens(): OidcTokenSet | null {
  return activeOidc
}

/** 令牌是否仍新鲜（未越过"过期前 skew"）。 */
export function isOidcTokenFresh(tokens: OidcTokenSet, now: number = Date.now()): boolean {
  return tokens.expiresAt - OIDC_EXPIRY_SKEW_MS > now
}

/**
 * 同步解析本次请求应携带的 Bearer token。
 * 优先 OIDC access token（需新鲜），否则回退到配置的 `bearerToken`，都没有返回 undefined。
 *
 * 注意：本函数是同步的（被 `makeLlm` / `reportV9Observation` 直接调用），
 * 无法在此处异步刷新；刷新由 `resolveApiTokenFresh`（异步）或 background 主动维护。
 * 令牌若已过期，这里**不会**返回过期 token，而是回落到 `bearerToken`。
 */
export function resolveApiToken(
  settings: Pick<ExtensionSettings, 'bearerToken'>,
  now: number = Date.now(),
): string | undefined {
  if (activeOidc && isOidcTokenFresh(activeOidc, now))
    return activeOidc.accessToken

  const token = settings.bearerToken?.trim()
  return token || undefined
}

export type ResolveApiTokenKind
  = | 'requires_relogin' // OIDC 过期且无可用 refresh / refresh 失败（部署或登录态问题）
    | 'unauthorized' // 根本没配置任何凭据（与 rejected 语义不同）
    | 'network'
    | 'malformed'

export type ResolveApiTokenResult
  = | { ok: true, token: string, source: 'oidc' | 'bearer' }
    | { ok: false, kind: ResolveApiTokenKind, message: string }

export interface ResolveApiTokenDeps {
  authBaseUrl: string
  fetchImpl?: typeof fetch
  now?: number
  /** 刷新成功后回调（用于把新令牌写回持久化存储）。 */
  onRefreshed?: (tokens: OidcTokenSet) => void | Promise<void>
}

/**
 * 异步版凭据解析：在 OIDC 令牌过期时**主动续期**。
 *
 * - OIDC 新鲜 ⇒ 直接返回（source: 'oidc'）。
 * - OIDC 过期且有 refresh token ⇒ 调 `refreshAccessToken`；成功则更新持热 + 回调，
 *   返回新 access token；**失败（含 `invalid_client`）则降级为 `requires_relogin`**，
 *   绝不返回旧 token。
 * - 无 OIDC ⇒ 回退到 `bearerToken`；都没配 ⇒ `unauthorized`（信息上区分"未配置"）。
 */
export async function resolveApiTokenFresh(
  settings: Pick<ExtensionSettings, 'bearerToken'>,
  deps: ResolveApiTokenDeps,
): Promise<ResolveApiTokenResult> {
  const now = deps.now ?? Date.now()

  if (activeOidc) {
    if (isOidcTokenFresh(activeOidc, now))
      return { ok: true, token: activeOidc.accessToken, source: 'oidc' }

    if (activeOidc.refreshToken) {
      let refreshed: Awaited<ReturnType<typeof refreshAccessToken>>
      try {
        refreshed = await refreshAccessToken({
          authBaseUrl: deps.authBaseUrl,
          refreshToken: activeOidc.refreshToken,
          fetchImpl: deps.fetchImpl,
        })
      }
      catch (err) {
        return { ok: false, kind: 'network', message: err instanceof Error ? err.message : String(err) }
      }

      if (refreshed.ok) {
        const next: OidcTokenSet = {
          accessToken: refreshed.accessToken,
          refreshToken: refreshed.refreshToken ?? activeOidc.refreshToken,
          expiresAt: now + refreshed.expiresIn * 1000,
        }
        setActiveOidcTokens(next)
        await deps.onRefreshed?.(next)
        return { ok: true, token: next.accessToken, source: 'oidc' }
      }

      // 续期失败（invalid_client / unauthorized / malformed）：诚实上报，需重新登录。
      return { ok: false, kind: 'requires_relogin', message: refreshed.message }
    }

    // 过期且无 refresh token ⇒ 必须重新登录。
    return { ok: false, kind: 'requires_relogin', message: 'OIDC access token expired and no refresh token available.' }
  }

  // 无 OIDC：回退到配置的 bearer token。
  const token = settings.bearerToken?.trim()
  if (!token)
    return { ok: false, kind: 'unauthorized', message: 'No credential configured (set a Bearer token or sign in via OIDC).' }
  return { ok: true, token, source: 'bearer' }
}
