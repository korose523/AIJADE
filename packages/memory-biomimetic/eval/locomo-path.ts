/**
 * LoCoMo 语料路径解析 + 完整性校验。
 *
 * ── 为什么这个文件必须存在 ────────────────────────────────────────────────
 * 在这之前，`eval/` 下 10 个脚本**全部硬编码默认值 `/tmp/locomo10.json`**。
 * 后果不是"不方便"，而是**研究不可复现**：
 *   · `/tmp` 会被系统清理、会被重启清空，不是数据集该待的地方；
 *   · 于是 P1.5 / H2 / H5 / 显著性探针 / 嵌套 CV 审计这五条证据链的**输入消失了**，
 *     而它们的结果报告还留在 `eval/results/` 里 —— 论文引用的数字无法被任何人重算。
 *   · 最坏的情况是静默：脚本读不到文件就抛一个 `ENOENT`，
 *     读者会以为是自己的环境问题，而不是"数据从未被持久保存"。
 *
 * ── 解析顺序（先到先用）────────────────────────────────────────────────
 *   1. 显式参数（`process.argv[2]`）—— 保持所有脚本原有的 CLI 用法可用；
 *   2. 环境变量 `AIJADE_LOCOMO_PATH` —— CI / 多机场景；
 *   3. 仓库内数据目录 `eval/data/locomo10.json` —— **默认值**，随仓库分发说明；
 *   4. 历史遗留 `/tmp/locomo10.json` —— 仅为兼容旧脚本调用，命中时**发出警告**。
 *
 * 全部落空时抛出的错误必须包含**可执行的补救步骤**，而不是只报"文件不存在"。
 *
 * ── 数据来源与许可 ──────────────────────────────────────────────────────
 * LoCoMo (Long Conversation Memory) 由 Snap Research 发布：
 *   https://github.com/snap-research/locomo  （data/locomo10.json）
 * 本仓库**不分发**该文件（第三方数据、另有其许可），只提供获取脚本与校验和。
 * 获取：`pnpm --filter @proj-aijade/memory-biomimetic exec tsx eval/fetch-locomo.ts`
 */
import type { LocomoConversation } from '../src/index'

import process from 'node:process'

import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** 本模块所在目录（`eval/`），用于定位默认数据路径，避免依赖 cwd。 */
const EVAL_DIR = dirname(fileURLToPath(import.meta.url))

/** 仓库内约定的数据路径。 */
export const DEFAULT_LOCOMO_PATH = resolve(EVAL_DIR, 'data/locomo10.json')

/** 旧脚本时期的硬编码路径，仅作兼容探测。 */
export const LEGACY_LOCOMO_PATH = '/tmp/locomo10.json'

/**
 * 期望的文件指纹。用于区分"拿到了数据集"与"拿到了**同一个**数据集"。
 *
 * 这一点不是洁癖：LoCoMo 上游仍在增补，`main` 分支的内容会变。
 * 若不钉住指纹，六个月后重跑得到不同的 recall@K，
 * 而**没有人能判断差异来自我们的方法还是来自语料的更新**。
 */
export const LOCOMO_SHA256
  = '79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'

/** 上游获取地址（单一真源，fetch 脚本与错误信息共用）。 */
export const LOCOMO_URL
  = 'https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json'

export interface ResolvedLocomo {
  path: string
  /** 来源标签，用于在结果报告里声明"数据从哪来"。 */
  source: 'cli-arg' | 'env' | 'repo' | 'legacy-tmp'
}

function missingDataError(tried: string[]): Error {
  return new Error(
    [
      'LoCoMo 语料未找到。已尝试以下路径：',
      ...tried.map(p => `  · ${p}`),
      '',
      '补救方式（任选其一）：',
      `  1) 获取语料到默认位置：tsx eval/fetch-locomo.ts`,
      `  2) 指定已有文件：            tsx <脚本> /path/to/locomo10.json`,
      `  3) 设置环境变量：            export AIJADE_LOCOMO_PATH=/path/to/locomo10.json`,
      '',
      `上游：${LOCOMO_URL}`,
      `（注意：/tmp 不是持久位置，语料曾因此丢失过一次，请勿再放回 /tmp）`,
    ].join('\n'),
  )
}

/**
 * 解析语料路径。`cliArg` 传 `process.argv[2]`。
 * 找不到时抛错，错误信息自带补救步骤。
 */
export function resolveLocomoPath(cliArg?: string): ResolvedLocomo {
  const tried: string[] = []

  if (cliArg) {
    if (existsSync(cliArg))
      return { path: cliArg, source: 'cli-arg' }
    tried.push(`${cliArg} (命令行参数)`)
    // 显式给了参数却不存在 ⇒ 这是使用者意图明确的情况，直接报错，不要悄悄 fallback。
    throw missingDataError(tried)
  }

  const fromEnv = process.env.AIJADE_LOCOMO_PATH
  if (fromEnv) {
    if (existsSync(fromEnv))
      return { path: fromEnv, source: 'env' }
    tried.push(`${fromEnv} (AIJADE_LOCOMO_PATH)`)
    throw missingDataError(tried)
  }

  if (existsSync(DEFAULT_LOCOMO_PATH))
    return { path: DEFAULT_LOCOMO_PATH, source: 'repo' }
  tried.push(`${DEFAULT_LOCOMO_PATH} (仓库数据目录)`)

  if (existsSync(LEGACY_LOCOMO_PATH)) {
    console.warn(
      `[locomo] 警告：正在使用遗留路径 ${LEGACY_LOCOMO_PATH}。`
      + `该位置不持久，请执行 tsx eval/fetch-locomo.ts 迁移到 ${DEFAULT_LOCOMO_PATH}。`,
    )
    return { path: LEGACY_LOCOMO_PATH, source: 'legacy-tmp' }
  }
  tried.push(`${LEGACY_LOCOMO_PATH} (遗留 /tmp 路径)`)

  throw missingDataError(tried)
}

/** 计算文件的 sha256。 */
export function sha256File(path: string): string {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

/**
 * 读取语料并校验数量与指纹。
 *
 * `verifyChecksum = false` 用于**探索性**运行（例如上游更新后想先看看差多少）；
 * 但任何进入 `eval/results/` 的结果都必须通过校验 —— 否则数字归属不明。
 */
export function loadLocomoVerified(
  cliArg?: string,
  opts: { verifyChecksum?: boolean } = {},
): { conversations: LocomoConversation[], path: string, source: ResolvedLocomo['source'], sha256: string, checksumMatches: boolean } {
  const { verifyChecksum = true } = opts
  const { path, source } = resolveLocomoPath(cliArg)

  const sha256 = sha256File(path)
  const checksumMatches = sha256 === LOCOMO_SHA256

  if (verifyChecksum && !checksumMatches) {
    throw new Error(
      [
        `LoCoMo 语料指纹不匹配，拒绝据此产出结果。`,
        `  期望: ${LOCOMO_SHA256}`,
        `  实际: ${sha256}`,
        `  路径: ${path}`,
        '',
        '上游语料可能已更新。请确认差异来源后再决定：',
        '  · 若是上游更新 → 更新本文件的 LOCOMO_SHA256，并在论文中注明语料版本；',
        '  · 若是本地被改动 → 重新获取（tsx eval/fetch-locomo.ts）。',
        '  · 只做探索、不需要可比数字 → 传 { verifyChecksum: false }。',
      ].join('\n'),
    )
  }

  const conversations = JSON.parse(readFileSync(path, 'utf8')) as LocomoConversation[]
  if (!Array.isArray(conversations) || conversations.length === 0)
    throw new Error(`LoCoMo 语料格式异常：期望非空数组，实际得到 ${typeof conversations}`)

  return { conversations, path, source, sha256, checksumMatches }
}
