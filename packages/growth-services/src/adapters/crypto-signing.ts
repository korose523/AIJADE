/**
 * Real detached-signature adapter — backs {@link SigningPort} with HMAC-SHA256
 * (node:crypto). This is the production-grade replacement for the trivial
 * FNV-1a stand-in in `in-memory.ts`: it signs a canonical JSON form of the
 * payload with a shared secret, so evolution proposals / trusted releases can
 * be verified for integrity and authenticity.
 */

import type { SigningPort } from '../ports'

import process from 'node:process'

import { Buffer } from 'node:buffer'
import { createHmac, timingSafeEqual } from 'node:crypto'

/** Deterministic, key-order-independent JSON serialisation. */
function canonicalize(payload: unknown): string {
  return stableStringify(payload)
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object')
    return JSON.stringify(value)
  if (Array.isArray(value))
    return `[${value.map(stableStringify).join(',')}]`
  const obj = value as Record<string, unknown>
  const keys = Object.keys(obj).sort()
  return `{${keys.map(k => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(',')}}`
}

/**
 * HMAC-SHA256 signing port. The secret is read from `AIJADE_SIGNING_SECRET`
 * (or passed in). Falls back to a dev secret only when no env is configured —
 * production deployments MUST set `AIJADE_SIGNING_SECRET`.
 */
export class CryptoSigningAdapter implements SigningPort {
  private readonly secret: string
  /** True when the dev fallback secret is in use (callers may warn). */
  readonly usingDevSecret: boolean

  constructor(secret?: string) {
    const resolved = secret ?? process.env.AIJADE_SIGNING_SECRET
    if (resolved) {
      this.secret = resolved
      this.usingDevSecret = false
    }
    else {
      this.secret = 'aijade-growth-dev-secret'
      this.usingDevSecret = true
    }
  }

  sign(payload: unknown): string {
    return createHmac('sha256', this.secret).update(canonicalize(payload)).digest('hex')
  }

  verify(payload: unknown, sig: string): boolean {
    let expected: Buffer
    let given: Buffer
    try {
      expected = Buffer.from(this.sign(payload), 'hex')
      given = Buffer.from(sig, 'hex')
    }
    catch {
      return false
    }
    if (expected.length !== given.length)
      return false
    return timingSafeEqual(expected, given)
  }
}
