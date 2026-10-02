import process from 'node:process'

/**
 * 获取 LongMemEval（S 变体）到持久位置，并校验大小 + 指纹。
 *
 * 用法：
 *   tsx eval/fetch-longmemeval.ts            # 缺失才下载
 *   tsx eval/fetch-longmemeval.ts --force    # 强制重新下载
 *
 * 退出码：0 成功（含"已存在且指纹正确"）；1 失败。
 *
 * ── 与 fetch-locomo.ts 的两点差异 ──────────────────────────────────────────
 * 1. 上游是 Hugging Face 而不是 raw.githubusercontent：GitHub 仓库
 *    `xiaowu0162/LongMemEval` **不托管数据**（其 git tree 中没有 data/*.json）。
 *    本脚本因此把 `LONGMEMEVAL_S_URL` 作为单一真源，不写第二个下载源。
 * 2. 文件 264 MiB，下载可能中断。中断会产生**语法合法但被截断**的 JSON，
 *    所以校验同时比对**字节数**与 **sha256**，并在失败信息里区分这两种情况。
 *
 * 注意：`eval/data/` 已在仓库根 `.gitignore` 中忽略（第 253 行），
 * 因此本脚本下载的数据**不会进版本库** —— 与 LoCoMo 侧一致：分发获取方式，不分发第三方数据。
 */
import { existsSync, mkdirSync, statSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

import {
  DEFAULT_LONGMEMEVAL_PATH,
  LONGMEMEVAL_S_BYTES,
  LONGMEMEVAL_S_SHA256,
  LONGMEMEVAL_S_URL,
  sha256File,
} from './longmemeval-path'

function mismatchError(actualBytes: number, actualSha: string): Error {
  const truncated = actualBytes < LONGMEMEVAL_S_BYTES
  return new Error(
    [
      '下载完成但校验未通过。',
      `  期望 sha256 : ${LONGMEMEVAL_S_SHA256}`,
      `  实际 sha256 : ${actualSha}`,
      `  期望字节数  : ${LONGMEMEVAL_S_BYTES}`,
      `  实际字节数  : ${actualBytes}`,
      '',
      truncated
        ? '实际字节数偏小 —— 很可能是下载被中断，产生了被截断但仍可被 JSON.parse 的文件。请重新执行：tsx eval/fetch-longmemeval.ts --force'
        : '字节数与期望不一致 —— 上游语料很可能已更新（该数据集在 2025-09 发布过一次 cleaned 替换版）。',
      '',
      '请勿直接改本脚本去迁就新指纹。正确做法：',
      '  1) 确认上游确有更新（HF 数据集卡片的 lastModified / commits）；',
      '  2) 判断更新是否影响已发表数字（题量、题型分布、answer_session_ids 是否变化）；',
      '  3) 同步更新 longmemeval-path.ts 的 LONGMEMEVAL_S_SHA256 / LONGMEMEVAL_S_BYTES，',
      '     并在论文中注明语料版本。',
    ].join('\n'),
  )
}

async function main(): Promise<void> {
  const force = process.argv.includes('--force')
  const target = DEFAULT_LONGMEMEVAL_PATH

  console.info(`[fetch-longmemeval] 目标路径：${target}`)
  console.info(`[fetch-longmemeval] 上游：${LONGMEMEVAL_S_URL}`)

  if (existsSync(target) && !force) {
    const actualBytes = statSync(target).size
    const actual = sha256File(target)
    if (actual === LONGMEMEVAL_S_SHA256 && actualBytes === LONGMEMEVAL_S_BYTES) {
      console.info('[fetch-longmemeval] 已存在且大小/指纹正确，无需下载（用 --force 可强制重下）。')
      return
    }
    console.warn(
      '[fetch-longmemeval] 已存在但校验不通过：'
      + `\n  期望 ${LONGMEMEVAL_S_SHA256} / ${LONGMEMEVAL_S_BYTES} B`
      + `\n  实际 ${actual} / ${actualBytes} B\n  → 将重新下载。`,
    )
  }

  const res = await fetch(LONGMEMEVAL_S_URL)
  if (!res.ok)
    throw new Error(`下载失败：HTTP ${res.status} ${res.statusText}  ← ${LONGMEMEVAL_S_URL}`)

  const buf = Buffer.from(await res.arrayBuffer())
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, buf)

  const actualBytes = statSync(target).size
  const actual = sha256File(target)
  if (actual !== LONGMEMEVAL_S_SHA256 || actualBytes !== LONGMEMEVAL_S_BYTES)
    throw mismatchError(actualBytes, actual)

  console.info(`[fetch-longmemeval] 完成：${(actualBytes / 1024 / 1024).toFixed(1)} MB，大小与指纹校验通过 ✅`)
  console.info(`[fetch-longmemeval] sha256 = ${actual}`)
}

main().catch((err) => {
  console.error(`[fetch-longmemeval] 失败：${err instanceof Error ? err.message : String(err)}`)
  process.exitCode = 1
})
