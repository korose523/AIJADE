import type { ExtensionSettings } from './types'

/**
 * 扩展两条 HTTP 通道（v10 REST 事件上报 `postV9Event` 与 LLM 摘要 `chatCompletion`）
 * 共用的**唯一** Bearer 凭据来源。
 *
 * 为什么是 Bearer、且只有这一条路径：
 *
 * 1. better-auth 会话 cookie 在扩展里**根本不可行**——扩展跑在
 *    `chrome-extension://<id>` 源下，服务端会话 cookie 落在服务端自身的 Web 源
 *    （且 `SameSite=Lax`/`Secure`），浏览器 cookie jar 按源隔离，跨源 fetch 不会
 *    附带这些 cookie；扩展也没有任何办法去"登录并拿到"落在别的源下的 cookie。
 *    （见 `client.ts` 的相关说明。）
 *
 * 2. 真正生产可用的 OIDC access token 路径（服务端 `resolveRequestAuth` 的 JWT 分支）
 *    **当前无法在扩展侧落地**——它需要一个已注册的扩展 OIDC 客户端（redirect_uri 含
 *    `chrome-extension://<id>/auth/callback`）以及扩展内完整的 PKCE 授权码流程，
 *    而这两者目前都不存在。这属于产品决策 + 服务端/扩展两侧的新工作，超出本次文件所有权范围。
 *
 * 3. 因此扩展今天能携带、且服务端 `resolveRequestAuth` 会接受的凭据，只有两类：
 *    - 服务端 `TEST_AUTH_TOKEN` 环境变量的值（dev/调试用，`env.ts` 注释明确"生产环境务必留空"）；
 *    - 未来某个真正的"扩展令牌签发端点"下发的 token（尚未实现）。
 *    两类都是**由操作者/用户显式放进设置**的 Bearer 字符串，绝不在代码里硬编码。
 *
 * 所以：两条通道都必须从这里读**同一个** `bearerToken` 值，绝不允许各自引用独立字段，
 * 否则就会退化为"两个 token 各自为政"。`makeLlm` 与 `reportV9Observation` 都调用本函数。
 */
export function resolveApiToken(
  settings: Pick<ExtensionSettings, 'bearerToken'>,
): string | undefined {
  const token = settings.bearerToken?.trim()
  return token || undefined
}
