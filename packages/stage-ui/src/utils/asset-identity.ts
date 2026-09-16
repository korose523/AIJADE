/**
 * Deterministic identity of a display-model asset.
 *
 * The hash produced here is what the research-telemetry `RenderAuditEntry`
 * records as `assetVersionHash` — so a render is reproducible and attributable
 * to the exact model bytes (or reference) it used.
 *
 * Crucially the two model kinds get *different* semantics, and the difference is
 * load-bearing:
 *
 * - **file models** → the hash is a genuine *content* identity: we hash the
 *   actual model bytes, so two byte-identical files always collapse to the same
 *   hash and a single changed byte never does.
 * - **url models** → the hash is a *reference* identity: we hash the **resolved
 *   URL string plus the format**. This intentionally is NOT a content hash — we
 *   have no guarantee the URL still serves the same bytes, so this hash answers
 *   "which asset was referenced", never "what the bytes were". Do not describe
 *   the url branch as a "content hash" anywhere.
 *
 * No new dependencies are introduced: `crypto.subtle.digest` is available in
 * both the browser and Node >= 18.
 */

import type { DisplayModel } from '../stores/display-models'

/** Sentinel separating the url from the format in the reference string. A pipe
 *  is used deliberately: it is a plain ASCII char that can never appear inside a
 *  URL or a model-format enum value, so the reference string is unambiguous. */
const REFERENCE_SEP = '|'

const assetHashCache = new Map<string, Promise<string>>()

/**
 * SHA-256 hex digest of the given data.
 *
 * Accepts a string (UTF-8 encoded), a `Uint8Array`, or a raw `ArrayBuffer`.
 * The output is a lowercase 64-char hex string, stable across runtimes.
 */
export async function sha256Hex(
  data: ArrayBuffer | Uint8Array | string,
): Promise<string> {
  const bytes = typeof data === 'string'
    ? new TextEncoder().encode(data)
    : data instanceof Uint8Array
      ? data
      : new Uint8Array(data)

  const digest = await crypto.subtle.digest('SHA-256', bytes as BufferSource)
  return [...new Uint8Array(digest)]
    .map(b => b.toString(16).padStart(2, '0'))
    .join('')
}

/** Cheap change token used as part of the cache key. */
function changeToken(model: DisplayModel): string {
  if (model.type === 'file')
    return `${model.file.size}:${model.file.lastModified}`
  return model.url
}

/**
 * Resolve the deterministic version hash for a display model.
 *
 * - `type:'file'` → **content** identity: SHA-256 over the model's actual bytes.
 * - `type:'url'`  → **reference** identity: SHA-256 over `${url}${REFERENCE_SEP}${format}`.
 *   This is a reference/derivation identity (which asset was referenced), NOT a
 *   content identity — it must not be called or documented as a "content hash".
 *
 * Results are memoised in a module-level cache keyed by `model.id` plus a cheap
 * change token (file: `size`+`lastModified`; url: `url`), so repeated lookups for
 * the same model never re-hash.
 */
export async function resolveAssetVersionHash(model: DisplayModel): Promise<string> {
  const token = changeToken(model)
  const cacheKey = `${model.id}:${token}`

  const cached = assetHashCache.get(cacheKey)
  if (cached)
    return cached

  const promise = (async () => {
    if (model.type === 'file') {
      // Genuine content identity: hash the actual model bytes.
      const buf = await model.file.arrayBuffer()
      return sha256Hex(new Uint8Array(buf))
    }

    // Reference identity: hash the resolved URL string + format. NOT a content
    // hash — we only know which asset was referenced, not its bytes.
    const reference = `${model.url}${REFERENCE_SEP}${model.format}`
    return sha256Hex(reference)
  })()

  // Cache the promise itself so concurrent callers for the same model share one
  // in-flight hash instead of racing to compute it twice.
  assetHashCache.set(cacheKey, promise)
  return promise
}
