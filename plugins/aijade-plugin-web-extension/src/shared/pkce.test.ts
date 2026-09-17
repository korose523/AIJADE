import { describe, expect, it } from 'vitest'

import { base64UrlEncode, generateCodeChallenge, generateCodeVerifier, generateState } from './pkce'

describe('pkce', () => {
  it('rFC 7636 Appendix B 测试向量：S256 challenge 正确', async () => {
    const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
    const challenge = await generateCodeChallenge(verifier)
    // 这条向量能证明 SHA-256 + base64url 实现不是"看起来对"。
    expect(challenge).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')
  })

  it('base64UrlEncode 无填充且 +/ 被转义', () => {
    const bytes = new Uint8Array([251, 255, 16, 0, 128, 63, 254])
    const enc = base64UrlEncode(bytes)
    expect(enc).not.toMatch(/[+/=]/)
  })

  it('generateCodeVerifier 长度 43–128 且不重复', () => {
    const v = generateCodeVerifier()
    expect(v.length).toBeGreaterThanOrEqual(43)
    expect(v.length).toBeLessThanOrEqual(128)
    expect(generateCodeVerifier()).not.toBe(v)
  })

  it('generateState 长度 43（32 字节 base64url）且唯一', () => {
    const a = generateState()
    const b = generateState()
    expect(a.length).toBe(43)
    expect(a).not.toBe(b)
  })

  it('同一 verifier 的 challenge 稳定可复现', async () => {
    const v = generateCodeVerifier()
    expect(await generateCodeChallenge(v)).toBe(await generateCodeChallenge(v))
  })
})
