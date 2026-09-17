import { describe, expect, it } from 'vitest'

import { deriveWebExtensionOrigin, getAuthTrustedOrigins, getTrustedOrigin, resolveCheckoutRedirectBase, resolveTrustedRequestOrigin } from '../origin'

describe('origin utils', () => {
  it('allows localhost origins', () => {
    expect(getTrustedOrigin('http://localhost:5173')).toBe('http://localhost:5173')
  })

  it('allows https localhost (mkcert dev)', () => {
    expect(getTrustedOrigin('https://localhost:5273')).toBe('https://localhost:5273')
    expect(getTrustedOrigin('https://127.0.0.1:5273')).toBe('https://127.0.0.1:5273')
  })

  it('rejects private LAN Vite dev origins unless listed in ADDITIONAL_TRUSTED_ORIGINS', () => {
    expect(getTrustedOrigin('https://10.0.0.129:5273')).toBe('')
    expect(getTrustedOrigin('https://198.18.0.1:5273')).toBe('')
    expect(getTrustedOrigin('https://192.168.1.5:5273')).toBe('')

    const extra = ['https://10.0.0.129:5273', 'https://198.18.0.1:5273', 'https://192.168.1.5:5273']
    expect(getTrustedOrigin('https://10.0.0.129:5273', extra)).toBe('https://10.0.0.129:5273')
    expect(getTrustedOrigin('https://198.18.0.1:5273', extra)).toBe('https://198.18.0.1:5273')
    expect(getTrustedOrigin('https://192.168.1.5:5273', extra)).toBe('https://192.168.1.5:5273')
  })

  it('rejects untrusted origins', () => {
    expect(getTrustedOrigin('https://example.com')).toBe('')
  })

  it('prefers a trusted referer origin', () => {
    const request = new Request('http://localhost/api/v1/stripe/checkout', {
      headers: {
        referer: 'https://aijade.ai/settings/flux',
        origin: 'https://example.com',
      },
    })

    expect(resolveTrustedRequestOrigin(request)).toBe('https://aijade.ai')
  })

  it('falls back to a trusted origin header when referer is missing', () => {
    const request = new Request('http://localhost/api/v1/stripe/checkout', {
      headers: {
        origin: 'http://localhost:5173',
      },
    })

    expect(resolveTrustedRequestOrigin(request)).toBe('http://localhost:5173')
  })

  it('collects api and request origins for auth', () => {
    const request = new Request('http://localhost/api/auth/sign-in/social', {
      headers: {
        origin: 'http://localhost:5173',
      },
    })

    expect(getAuthTrustedOrigins({
      API_SERVER_URL: 'https://api.aijade.ai',
      ADDITIONAL_TRUSTED_ORIGINS: [],
    }, request)).toEqual([
      'https://api.aijade.ai',
      'http://localhost:*',
      'http://127.0.0.1:*',
      'http://localhost:5173',
    ])
  })

  describe('resolveCheckoutRedirectBase', () => {
    const fallback = 'https://aijade.ai'

    it('prefers the trusted request origin over the fallback', () => {
      const request = new Request('http://localhost/api/v1/stripe/checkout', {
        headers: { referer: 'http://localhost:5173/settings/flux' },
      })

      expect(resolveCheckoutRedirectBase(request, [], fallback)).toBe('http://localhost:5173')
    })

    // ROOT CAUSE:
    //
    // The packaged Electron renderer loads from file://, so its Stripe checkout
    // request carries no Referer and an opaque/absent Origin. resolveTrustedRequestOrigin
    // then returns undefined and the checkout route threw
    // `createBadRequestError('Missing trusted request origin', 'INVALID_ORIGIN')`,
    // blocking FLUX purchases on desktop (web/mobile were unaffected because they
    // send a trusted web origin).
    //
    // Before patch: no trusted origin -> undefined -> route throws INVALID_ORIGIN.
    // After patch: no trusted origin -> falls back to the configured web app URL,
    // which Stripe accepts as a success_url/cancel_url base.
    it('falls back to the web app URL when the request has no trusted origin (Electron file://)', () => {
      const request = new Request('http://localhost/api/v1/stripe/checkout', {
        method: 'POST',
        // file:// renderers send no Referer; Origin is absent or the opaque literal "null".
        headers: { origin: 'null' },
      })

      expect(resolveTrustedRequestOrigin(request, [])).toBeUndefined()
      expect(resolveCheckoutRedirectBase(request, [], fallback)).toBe(fallback)
    })

    it('falls back to the web app URL for an untrusted web origin', () => {
      const request = new Request('http://localhost/api/v1/stripe/checkout', {
        headers: { origin: 'https://evil.example.com' },
      })

      expect(resolveCheckoutRedirectBase(request, [], fallback)).toBe(fallback)
    })
  })

  it('includes ADDITIONAL_TRUSTED_ORIGINS in Better Auth trustedOrigins list', () => {
    expect(getAuthTrustedOrigins({
      API_SERVER_URL: 'https://api.aijade.ai',
      ADDITIONAL_TRUSTED_ORIGINS: ['https://10.0.0.129:5273'],
    })).toEqual([
      'https://api.aijade.ai',
      'https://10.0.0.129:5273',
      'http://localhost:*',
      'http://127.0.0.1:*',
    ])
  })

  // ROOT CAUSE:
  //
  // `URL.origin` is the literal string "null" for *every* non-special scheme, not only
  // for opaque origins. That makes `new URL('chrome-extension://<id>').origin === 'null'`,
  // so an extension origin could never survive normalization and could never equal the
  // `Origin` header it was meant to match — the extension's /api/* calls were blocked by
  // CORS no matter how the allowlist was configured, which in turn made the OIDC token
  // exchange and every Bearer call unreachable.
  //
  // The same normalization is what `parseAdditionalTrustedOriginsEnv` applies, so a
  // `chrome-extension://` entry in ADDITIONAL_TRUSTED_ORIGINS is not merely useless: it
  // is rewritten to "null" and would then match the *opaque* origin that packaged
  // Electron renderers send. Hence the extension id has its own env var (WEB_EXTENSION_ID).
  describe('chrome extension origins', () => {
    const EXTENSION_ID = 'abcdefghijklmnopabcdefghijklmnop'
    const EXTENSION_ORIGIN = `chrome-extension://${EXTENSION_ID}`

    it('derives the extension origin from WEB_EXTENSION_ID', () => {
      expect(deriveWebExtensionOrigin({ WEB_EXTENSION_ID: EXTENSION_ID })).toEqual([EXTENSION_ORIGIN])
      expect(deriveWebExtensionOrigin({ WEB_EXTENSION_ID: `  ${EXTENSION_ID}  ` })).toEqual([EXTENSION_ORIGIN])
    })

    it('trusts no extension origin when WEB_EXTENSION_ID is unset or blank', () => {
      // Fails closed: an unconfigured deployment must not trust every extension.
      expect(deriveWebExtensionOrigin({})).toEqual([])
      expect(deriveWebExtensionOrigin({ WEB_EXTENSION_ID: '' })).toEqual([])
      expect(deriveWebExtensionOrigin({ WEB_EXTENSION_ID: '   ' })).toEqual([])
    })

    it('accepts the extension origin the browser sends verbatim in the Origin header', () => {
      // NOTE: this path does not touch getOriginFromUrl — getTrustedOrigin compares the
      // header string as-is. It guards that deriveWebExtensionOrigin emits exactly the
      // spelling the browser sends, which is what the allowlist match depends on.
      expect(getTrustedOrigin(EXTENSION_ORIGIN, [EXTENSION_ORIGIN])).toBe(EXTENSION_ORIGIN)
      expect(resolveTrustedRequestOrigin(
        new Request('http://localhost/api/v1/v9/events', { headers: { origin: EXTENSION_ORIGIN } }),
        [EXTENSION_ORIGIN],
      )).toBe(EXTENSION_ORIGIN)
    })

    it('normalizes a full chrome-extension URL down to its origin', () => {
      // This is the actual regression guard for the opaque-origin collapse. A referer is a
      // full URL, so it passes through getOriginFromUrl, where `URL.origin` would have
      // returned the literal "null" for the non-special `chrome-extension:` scheme —
      // making the origin unmatchable no matter what the allowlist contained.
      expect(resolveTrustedRequestOrigin(
        new Request('http://localhost/api/v1/v9/events', {
          headers: { referer: `${EXTENSION_ORIGIN}/sidepanel/index.html` },
        }),
        [EXTENSION_ORIGIN],
      )).toBe(EXTENSION_ORIGIN)

      // Contrast: an http(s) referer is unaffected by the fix (URL.origin already worked).
      expect(resolveTrustedRequestOrigin(
        new Request('http://localhost/api/v1/v9/events', {
          headers: { referer: 'http://localhost:5173/chat' },
        }),
        [],
      )).toBe('http://localhost:5173')
    })

    it('still rejects an extension origin that was not configured', () => {
      expect(getTrustedOrigin(EXTENSION_ORIGIN, [])).toBe('')
      expect(getTrustedOrigin('chrome-extension://someotherextensionid', [EXTENSION_ORIGIN])).toBe('')
    })

    it('keeps file:// opaque so the Electron Stripe fallback still applies', () => {
      // The normalization fix must not turn file:// into a trustable origin: it has no
      // host to rebuild from, and trusting it would bypass resolveCheckoutRedirectBase.
      expect(resolveTrustedRequestOrigin(
        new Request('http://localhost/api/v1/stripe/checkout', { headers: { origin: 'null' } }),
        [],
      )).toBeUndefined()

      // This asserts a hazard, not a desirable configuration. Because
      // parseAdditionalTrustedOriginsEnv normalizes through `URL.origin`, an
      // ADDITIONAL_TRUSTED_ORIGINS entry of `chrome-extension://<id>` becomes the string
      // "null" — which then matches the opaque origin packaged Electron renderers send.
      // Writing the extension there would therefore widen trust to file:// rather than to
      // that one extension. It is why WEB_EXTENSION_ID exists as a separate setting.
      expect(new URL('chrome-extension://abcdefghijklmnop').origin).toBe('null')
    })

    it('merges the extension origin into the auth trusted-origins list', () => {
      expect(getAuthTrustedOrigins({
        API_SERVER_URL: 'https://api.aijade.ai',
        ADDITIONAL_TRUSTED_ORIGINS: [],
        WEB_EXTENSION_ID: EXTENSION_ID,
      })).toEqual([
        'https://api.aijade.ai',
        EXTENSION_ORIGIN,
        'http://localhost:*',
        'http://127.0.0.1:*',
      ])
    })

    it('omits the extension origin from the auth list when unconfigured', () => {
      const origins = getAuthTrustedOrigins({
        API_SERVER_URL: 'https://api.aijade.ai',
        ADDITIONAL_TRUSTED_ORIGINS: [],
      })
      expect(origins.some(origin => origin.startsWith('chrome-extension://'))).toBe(false)
    })
  })
})
