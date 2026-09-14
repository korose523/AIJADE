/**
 * Stable fingerprinting for L0.
 *
 * The fingerprint is what lets you look at an artifact six months later and
 * know exactly which weights and which decoding parameters produced it. It is
 * deliberately dependency-free so it can be computed in any runtime.
 */

import type { ModelIdentity, RunFingerprint, SamplingConfig, SubstrateMode } from './types'

import { SamplingError } from './types'

/** Bump when the fingerprint meaning changes, so old artifacts stay readable. */
export const FINGERPRINT_SCHEMA = 'aijade.substrate/1'

/**
 * FNV-1a 32-bit. Chosen over anything cryptographic because it only needs to be
 * stable across runs and machines, and this must work in browsers too.
 */
export function fnv1a(input: string): string {
  let hash = 0x811C9DC5
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i)
    // 32-bit FNV prime multiply, kept in range with Math.imul.
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

const SAMPLING_KEYS: readonly (keyof SamplingConfig)[] = [
  'temperature',
  'seed',
  'top_p',
  'top_k',
  'repeat_penalty',
  'num_ctx',
  'num_predict',
  'think',
]

/**
 * Order-independent hash of a sampling config.
 *
 * Sorting by key means two callers that build the same config in a different
 * property order still get one fingerprint — otherwise you end up with two
 * "different" conditions that are actually identical.
 */
export function hashSampling(sampling: SamplingConfig): string {
  return fnv1a(SAMPLING_KEYS.map(k => `${k}=${sampling[k]}`).join(';'))
}

/**
 * Build the full run fingerprint.
 *
 * `sampling` is validated here as well: a config missing any key would silently
 * fall back to server defaults and break the very guarantee this package exists
 * to provide.
 */
export function buildFingerprint(
  mode: SubstrateMode,
  model: ModelIdentity,
  sampling: SamplingConfig,
  serverVersion?: string,
): RunFingerprint {
  assertCompleteSampling(sampling)

  const samplingHash = hashSampling(sampling)
  const identityPart = model.digest ? `${model.tag}@${model.digest}` : model.tag
  const serverPart = serverVersion ?? 'unknown'

  return {
    schema: FINGERPRINT_SCHEMA,
    mode,
    model,
    sampling,
    samplingHash,
    serverVersion,
    fingerprint: fnv1a(`${FINGERPRINT_SCHEMA}|${mode}|${identityPart}|${samplingHash}|${serverPart}`),
  }
}

/** Reject any config that is not fully specified. */
export function assertCompleteSampling(sampling: SamplingConfig): void {
  const bad = SAMPLING_KEYS.filter((k) => {
    const v = sampling?.[k]
    if (k === 'think')
      return typeof v !== 'boolean'
    return typeof v !== 'number' || Number.isNaN(v as number)
  })
  if (bad.length > 0) {
    throw new SamplingError(
      `Sampling config is incomplete; missing or wrong-typed: ${bad.join(', ')}. `
      + 'Refusing to fall back to server defaults — that is what makes runs unreproducible.',
    )
  }
}

/** Enforce the invariants that make a run an experiment rather than a demo. */
export function assertResearchMode(sampling: SamplingConfig): void {
  if (sampling.temperature !== 0) {
    throw new SamplingError(
      `research mode requires temperature=0 (greedy decoding) for reproducibility; got ${sampling.temperature}. `
      + 'Use mode "interactive" if you really want sampling.',
    )
  }
}

const SHOW_TIMEOUT_MS = 10_000

/**
 * Ask Ollama what the model actually is.
 *
 * The digest is the important part: tags are mutable, so recording only the tag
 * would let a later re-run silently use different weights.
 *
 * Two endpoints are needed, which is not obvious:
 * - `/api/show` returns the *details* (family, parameter size, quantization)
 *   but, at least on Ollama 0.33.x, **no digest**.
 * - `/api/tags` returns the *digest* and byte size but no details.
 * So identity = tags (for digest) ∪ show (for details).
 */
export async function resolveModelIdentity(
  baseUrl: string,
  model: string,
  timeoutMs = SHOW_TIMEOUT_MS,
): Promise<ModelIdentity> {
  const [tagged, details] = await Promise.all([
    resolveFromTags(baseUrl, model, timeoutMs),
    resolveDetails(baseUrl, model, timeoutMs),
  ])

  return {
    tag: model,
    digest: tagged?.digest,
    sizeBytes: tagged?.sizeBytes,
    family: details?.family,
    parameterSize: details?.parameterSize,
    quantization: details?.quantization,
  }
}

interface TaggedModel {
  digest?: string
  sizeBytes?: number
}

/**
 * Find the digest by listing local models.
 *
 * Handles the `model` vs `model:latest` mismatch: a caller passing "qwythos"
 * will find the entry stored as "qwythos:latest".
 */
async function resolveFromTags(baseUrl: string, model: string, timeoutMs: number): Promise<TaggedModel | undefined> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${baseUrl}/api/tags`, { signal: controller.signal })
    if (!res.ok)
      return undefined
    const data = await res.json() as { models?: { name?: string, digest?: string, size?: number }[] }
    const candidates = new Set([model, `${model}:latest`, model.replace(/:latest$/, '')])
    const hit = (data.models ?? []).find(m => m.name && candidates.has(m.name))
    if (!hit)
      return undefined
    return { digest: hit.digest, sizeBytes: hit.size }
  }
  catch {
    // Identity metadata is best-effort; never break a run because of it.
    return undefined
  }
  finally {
    clearTimeout(timer)
  }
}

interface ModelDetails {
  family?: string
  parameterSize?: string
  quantization?: string
}

async function resolveDetails(baseUrl: string, model: string, timeoutMs: number): Promise<ModelDetails | undefined> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(`${baseUrl}/api/show`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ model }),
      signal: controller.signal,
    })
    if (!res.ok)
      return undefined
    const data = await res.json() as { details?: { family?: string, parameter_size?: string, quantization_level?: string } }
    return {
      family: data.details?.family,
      parameterSize: data.details?.parameter_size,
      quantization: data.details?.quantization_level,
    }
  }
  catch {
    return undefined
  }
  finally {
    clearTimeout(timer)
  }
}

/** Best-effort server version. Never fatal — it is metadata, not a guarantee. */
export async function resolveServerVersion(baseUrl: string, timeoutMs = 5000): Promise<string | undefined> {
  try {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const res = await fetch(`${baseUrl}/api/version`, { signal: controller.signal })
    clearTimeout(timer)
    if (!res.ok)
      return undefined
    const data = await res.json() as { version?: string }
    return data.version
  }
  catch {
    return undefined
  }
}
