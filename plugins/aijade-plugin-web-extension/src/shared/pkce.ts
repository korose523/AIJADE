/**
 * PKCE 原语（RFC 7636），纯函数、零 node 依赖、浏览器安全。
 *
 * 扩展**没有** `@proj-aijade/stage-shared` 依赖，且**不允许新增 npm 依赖**，
 * 故用浏览器/Worker 自带的 WebCrypto 自行实现这三件小事：
 *   `crypto.getRandomValues` + `crypto.subtle.digest('SHA-256')` + base64url（无填充）。
 * 与 `packages/stage-shared/src/auth/pkce.ts` 行为保持一致（含 RFC 7636 附录 B 测试向量）。
 *
 * ⚠️ 绝不使用 `Math.random()` —— 它不提供密码学强度。
 */

const BASE64_PLUS = /\+/g
const BASE64_SLASH = /\//g
const BASE64_TRAILING_EQ = /=+$/

/** 字节数组 → URL-safe base64（无填充）。浏览器 (`btoa`) 与 Node 全局均可用。 */
export function base64UrlEncode(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes)
    binary += String.fromCharCode(byte)

  return btoa(binary)
    .replace(BASE64_PLUS, '-')
    .replace(BASE64_SLASH, '_')
    .replace(BASE64_TRAILING_EQ, '')
}

/**
 * 生成密码学随机的 code_verifier（RFC 7636 §4.1）：
 * 43–128 个字符，取自 unreserved URL 字符集。
 */
export function generateCodeVerifier(length = 64): string {
  const array = new Uint8Array(length)
  crypto.getRandomValues(array)
  return base64UrlEncode(array)
}

/** 由 code_verifier 派生 S256 code_challenge（RFC 7636 §4.2）。 */
export async function generateCodeChallenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return base64UrlEncode(new Uint8Array(digest))
}

/** 生成密码学随机的 state 参数，用于 CSRF 防护。 */
export function generateState(): string {
  const array = new Uint8Array(32)
  crypto.getRandomValues(array)
  return base64UrlEncode(array)
}
