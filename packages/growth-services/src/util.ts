/**
 * Small deterministic helpers shared by the growth services.
 *
 * No external dependencies: a collision-resistant-enough id and an FNV-1a hash
 * (mirrors the kernel's `fnv1a`) used for content-addressing and HMAC-style
 * signatures in the in-memory adapter.
 */

let __counter = 0

/** Monotonic-ish unique id with a readable prefix. */
export function genId(prefix: string): string {
  __counter += 1
  const t = Date.now().toString(36)
  const r = Math.floor(Math.random() * 0xFFFFFF).toString(36)
  return `${prefix}_${t}_${__counter.toString(36)}_${r}`
}

/** Today's date as ISO YYYY-MM-DD in local time. */
export function todayISO(now: number = Date.now()): string {
  const d = new Date(now)
  const y = d.getFullYear().toString().padStart(4, '0')
  const m = (d.getMonth() + 1).toString().padStart(2, '0')
  const day = d.getDate().toString().padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** Deterministic FNV-1a 32-bit hash (hex). Stable string → same digest. */
export function fnv1a(input: string): string {
  let h = 0x811C9DC5
  for (let i = 0; i < input.length; i++) {
    h ^= input.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/** Short content hash for de-duplicating reposts (FNV-1a over content). */
export function contentHashOf(content: string): string {
  return `h_${fnv1a(content)}`
}
