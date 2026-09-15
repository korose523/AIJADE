/**
 * v9 内核共享的确定性哈希工具。
 *
 * 为什么需要它（而不是 Math.random 或 JSON.stringify 直接拼）：
 * - `memory_versions.content_hash_sha256` 与 `evidence_weaves.graph_hash` 都必须
 *   **可复现**——同一次实验两次运行、或回放校验时，必须得到逐字节相同的哈希，
 *   否则"无证据写入"与"回放一致性"两条硬性保证就失去意义。
 * - `JSON.stringify` 的键顺序依赖对象插入顺序，不稳定；这里用**规范化的 JSON**
 *   （键名按字典序排序、数组保持原序）来消除顺序歧义。
 *
 * 仅依赖 node:crypto 的 sha256（内存内核运行在 Node 侧，vitest 亦在 Node 跑），
 * 不引入浏览器不兼容的 API。
 */

import { createHash } from 'node:crypto'

/** 递归规范化：对象键按字典序排序后序列化；数组保持元素顺序；其他原样。 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object')
    return JSON.stringify(value)
  if (Array.isArray(value))
    return `[${value.map(canonicalJson).join(',')}]`
  const obj = value as Record<string, unknown>
  const keys = Object.keys(obj).sort()
  return `{${keys.map(k => `${JSON.stringify(k)}:${canonicalJson(obj[k])}`).join(',')}}`
}

/** 任意字符串的 SHA-256 十六进制摘要（确定性）。 */
export function sha256Hex(input: string): string {
  return createHash('sha256').update(input, 'utf8').digest('hex')
}

/**
 * 内容哈希：规范化 payload → sha256。用作 `memory_versions.content_hash_sha256`。
 * 同一内容永远得到同一哈希；多一个字节也会改变结果。
 */
export function contentHash(payload: unknown): string {
  return sha256Hex(canonicalJson(payload))
}

/**
 * 图哈希：规范化的图（links 先按 `memory_version_id` 排序再序列化）→ sha256。
 * 用作 `evidence_weaves.graph_hash`，支撑回放一致性校验。
 */
export function graphHash(links: unknown[], spec: unknown): string {
  const sorted = [...links].sort((a, b) =>
    canonicalJson(a) < canonicalJson(b) ? -1 : canonicalJson(a) > canonicalJson(b) ? 1 : 0)
  return sha256Hex(canonicalJson({ spec, links: sorted }))
}
