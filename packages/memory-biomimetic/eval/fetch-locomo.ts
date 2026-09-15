import process from 'node:process'

/**
 * 获取 LoCoMo 语料到持久位置，并校验指纹。
 *
 * 用法：
 *   tsx eval/fetch-locomo.ts            # 缺失才下载
 *   tsx eval/fetch-locomo.ts --force    # 强制重新下载
 *
 * 退出码：0 成功（含"已存在且指纹正确"）；1 失败。
 *
 * ── 为什么需要这个脚本 ────────────────────────────────────────────────────
 * 见 `locomo-path.ts` 顶部说明：语料曾放在 `/tmp` 并因此丢失，
 * 导致五条证据链的输入消失而结果报告还在。一个"数据从哪来、怎么再拿到"
 * 的可执行入口，比文档里写一句"请下载 LoCoMo"要可靠得多。
 */
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

import {
  DEFAULT_LOCOMO_PATH,
  LEGACY_LOCOMO_PATH,
  LOCOMO_SHA256,
  LOCOMO_URL,
  sha256File,
} from './locomo-path'

async function main(): Promise<void> {
  const force = process.argv.includes('--force')
  const target = DEFAULT_LOCOMO_PATH

  console.info(`[fetch-locomo] 目标路径：${target}`)

  if (existsSync(target) && !force) {
    const actual = sha256File(target)
    if (actual === LOCOMO_SHA256) {
      console.info('[fetch-locomo] 已存在且指纹正确，无需下载（用 --force 可强制重下）。')
      return
    }
    console.warn(
      `[fetch-locomo] 已存在但指纹不匹配：\n  期望 ${LOCOMO_SHA256}\n  实际 ${actual}\n  → 将重新下载。`,
    )
  }

  const res = await fetch(LOCOMO_URL)
  if (!res.ok)
    throw new Error(`下载失败：HTTP ${res.status} ${res.statusText}  ← ${LOCOMO_URL}`)

  const buf = Buffer.from(await res.arrayBuffer())
  mkdirSync(dirname(target), { recursive: true })
  writeFileSync(target, buf)

  const actual = sha256File(target)
  if (actual !== LOCOMO_SHA256) {
    throw new Error(
      [
        '下载完成但指纹不匹配 —— 上游语料很可能已更新。',
        `  期望 ${LOCOMO_SHA256}`,
        `  实际 ${actual}`,
        '',
        '请勿直接改这个脚本去迁就新指纹。正确做法：',
        '  1) 确认上游确有更新（看上游仓库的提交记录）；',
        '  2) 判断更新是否影响已发表数字（题量、对话数、evidence id 是否变化）；',
        '  3) 同步更新 locomo-path.ts 的 LOCOMO_SHA256，并在论文中注明语料版本。',
      ].join('\n'),
    )
  }

  console.info(`[fetch-locomo] 完成：${(buf.length / 1024 / 1024).toFixed(1)} MB，指纹校验通过 ✅`)

  if (existsSync(LEGACY_LOCOMO_PATH)) {
    console.warn(
      `[fetch-locomo] 提示：遗留路径 ${LEGACY_LOCOMO_PATH} 仍存在。`
      + `它不是持久位置，确认无脚本依赖后可删除，避免两份数据并存导致"用的是哪一份"说不清。`,
    )
  }
}

main().catch((err) => {
  console.error(`[fetch-locomo] 失败：${err instanceof Error ? err.message : String(err)}`)
  process.exitCode = 1
})
