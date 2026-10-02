/**
 * LongMemEval 语料路径解析 + 完整性校验。
 *
 * ── 为什么这个文件必须存在 ────────────────────────────────────────────────
 * 与 `locomo-path.ts` 同一个理由，只是后果更大：J5 / P4 的核心结论
 * 「recency 项主导非相关性、抑制 recency 后 recall@K 大幅提升」目前**只在一个语料
 * （LoCoMo，10 段对话）上成立**，这是论文自己声明的首要效度威胁（single-corpus
 * threat）。第二个语料一旦"路径写死在某台机器上 / 落在会被清理的目录里"，
 * 补做的跨语料复现就又变成一句无法重算的声明 —— 那比不补更糟，因为它看起来
 * 像是已经解决了问题。
 *
 * 本文件因此把三件事钉死：
 *   1. 路径不依赖 cwd（`EVAL_DIR` 由 `import.meta.url` 推导）；
 *   2. 文件指纹钉死（`LONGMEMEVAL_S_SHA256`），区分"拿到了数据集"与"拿到了同一个数据集"；
 *   3. 找不到时的错误自带**可执行的补救步骤**，而不是裸 ENOENT。
 *
 * ── 解析顺序（先到先用）────────────────────────────────────────────────
 *   1. 显式参数（`process.argv[2]`）；
 *   2. 环境变量 `AIJADE_LONGMEMEVAL_PATH`；
 *   3. 仓库内数据目录 `eval/data/longmemeval_s_cleaned.json`。
 *
 * 与 `locomo-path.ts` 的一处**有意差异**：这里**没有 `/tmp` 遗留层**。
 * LoCoMo 那个层是为了兼容 10 个已硬编码 `/tmp` 的旧脚本；LongMemEval 从未
 * 被放到 `/tmp`，加一个不存在的遗留路径只会让"数据从哪来"多一个说不清的分支。
 *
 * ── 数据来源与许可 ──────────────────────────────────────────────────────
 * LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory
 *   Wu D, Wang H, Yu W, Zhang Y, Chang K W, Yu D. arXiv:2410.10813 (ICLR 2025).
 *   代码仓库：https://github.com/xiaowu0162/LongMemEval
 *
 * **该仓库不分发数据**（`git tree` 里没有 `data/*.json`）。官方托管位置是
 * Hugging Face（README 明确 "This dataset replaces the original LongMemEval
 * dataset"，且 "removes noisy history sessions that interfere with the answer
 * correctness"）：
 *   https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned
 * 许可：**MIT**（HF 数据集卡片 `license: mit`）。
 *
 * 可用变体（实测 HTTP 200 + Content-Length）：
 *   · longmemeval_s_cleaned.json   277,383,467 B   ← 本仓库默认使用（LongMemEvalS）
 *   · longmemeval_m_cleaned.json 2,737,100,077 B   ← 未使用（见下）
 *   · longmemeval_oracle.json       15,388,478 B   ← 未使用（已含 oracle 检索，不适用）
 *
 * 为什么只钉 `S`：`M` 单文件 2.7 GB，且每题 haystack ≈500 sessions / 1.5M tokens，
 * 逐题建记忆的算力与内存开销在本机上不可控。是否跑 `M` 应由实测 `S` 的耗时决定，
 * 而不是假设机器扛得住 —— 这里先不下载它。
 */
import type { LongMemEvalItem } from './longmemeval-adapter'

import process from 'node:process'

import { createHash } from 'node:crypto'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

/** 本模块所在目录（`eval/`），用于定位默认数据路径，避免依赖 cwd。 */
const EVAL_DIR = dirname(fileURLToPath(import.meta.url))

/** 仓库内约定的数据路径（LongMemEvalS 变体）。 */
export const DEFAULT_LONGMEMEVAL_PATH = resolve(EVAL_DIR, 'data/longmemeval_s_cleaned.json')

/**
 * 期望的文件指纹。
 *
 * 该值**不是猜测**：它是对本机实际下载文件 `shasum -a 256` 的结果
 * （见 `fetch-longmemeval.ts`，下载后强制比对）。上游在 2025-09 发布过一次
 * "cleaned" 替换版，说明这个语料**确实会变**；钉住指纹才能让六个月内重跑的
 * recall@K 差异被归因到方法而不是语料。
 */
export const LONGMEMEVAL_S_SHA256
  = 'd6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442'

/** 期望的字节数，与指纹一起构成"同一份数据"的双重确认。 */
export const LONGMEMEVAL_S_BYTES = 277_383_467

/** 上游获取地址（单一真源，fetch 脚本与错误信息共用）。 */
export const LONGMEMEVAL_S_URL
  = 'https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json'

export interface ResolvedLongMemEval {
  path: string
  /** 来源标签，用于在结果报告里声明"数据从哪来"。 */
  source: 'cli-arg' | 'env' | 'repo'
}

function missingDataError(tried: string[]): Error {
  return new Error(
    [
      'LongMemEval 语料未找到。已尝试以下路径：',
      ...tried.map(p => `  · ${p}`),
      '',
      '补救方式（任选其一）：',
      '  1) 获取语料到默认位置：tsx eval/fetch-longmemeval.ts',
      '  2) 指定已有文件：      tsx <脚本> /path/to/longmemeval_s_cleaned.json',
      '  3) 设置环境变量：      export AIJADE_LONGMEMEVAL_PATH=/path/to/longmemeval_s_cleaned.json',
      '',
      `上游：${LONGMEMEVAL_S_URL}`,
      '（该仓库不分发数据文件；GitHub 仓库里没有 data/*.json，只有 Hugging Face 托管。）',
    ].join('\n'),
  )
}

/**
 * 解析语料路径。`cliArg` 传 `process.argv[2]`。
 * 找不到时抛错，错误信息自带补救步骤。
 */
export function resolveLongMemEvalPath(cliArg?: string): ResolvedLongMemEval {
  const tried: string[] = []

  if (cliArg) {
    if (existsSync(cliArg))
      return { path: cliArg, source: 'cli-arg' }
    tried.push(`${cliArg} (命令行参数)`)
    // 显式给了参数却不存在 ⇒ 使用者意图明确，直接报错，不要悄悄 fallback。
    throw missingDataError(tried)
  }

  const fromEnv = process.env.AIJADE_LONGMEMEVAL_PATH
  if (fromEnv) {
    if (existsSync(fromEnv))
      return { path: fromEnv, source: 'env' }
    tried.push(`${fromEnv} (AIJADE_LONGMEMEVAL_PATH)`)
    throw missingDataError(tried)
  }

  if (existsSync(DEFAULT_LONGMEMEVAL_PATH))
    return { path: DEFAULT_LONGMEMEVAL_PATH, source: 'repo' }
  tried.push(`${DEFAULT_LONGMEMEVAL_PATH} (仓库数据目录)`)

  throw missingDataError(tried)
}

/** 计算文件的 sha256。 */
export function sha256File(path: string): string {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

export interface LoadedLongMemEval {
  data: LongMemEvalItem[]
  path: string
  source: ResolvedLongMemEval['source']
  sha256: string
  checksumMatches: boolean
  bytes: number
}

/**
 * 读取语料并校验题量、字节数与指纹。
 *
 * 校验 `bytes` 的原因：`wget`/`curl` 被中断会产生一个**语法合法但被截断**的文件，
 * 只比对 sha256 当然也能抓到，但字节数能让人一眼看出"是下了一半"还是"下错了文件"。
 *
 * `verifyChecksum = false` 仅供探索性运行；进入 `eval/results/` 的产物必须通过校验。
 */
export function loadLongMemEvalVerified(
  cliArg?: string,
  opts: { verifyChecksum?: boolean } = {},
): LoadedLongMemEval {
  const { verifyChecksum = true } = opts
  const { path, source } = resolveLongMemEvalPath(cliArg)

  const bytes = statSync(path).size
  const sha256 = sha256File(path)
  const checksumMatches = sha256 === LONGMEMEVAL_S_SHA256 && bytes === LONGMEMEVAL_S_BYTES

  if (verifyChecksum && !checksumMatches) {
    throw new Error(
      [
        'LongMemEval 语料指纹/大小不匹配，拒绝据此产出结果。',
        `  期望 sha256: ${LONGMEMEVAL_S_SHA256}`,
        `  实际 sha256: ${sha256}`,
        `  期望字节数: ${LONGMEMEVAL_S_BYTES}`,
        `  实际字节数: ${bytes}`,
        `  路径: ${path}`,
        '',
        '可能的原因与处理：',
        '  · 下载被中断（实际字节数明显偏小）→ 重新执行 tsx eval/fetch-longmemeval.ts --force；',
        '  · 上游发布了新的 cleaned 版本 → 更新 LONGMEMEVAL_S_SHA256 / LONGMEMEVAL_S_BYTES，',
        '    并在论文中注明语料版本（该语料在 2025-09 就替换过一次）；',
        '  · 只做探索、不需要可比数字 → 传 { verifyChecksum: false }。',
      ].join('\n'),
    )
  }

  const data = JSON.parse(readFileSync(path, 'utf8')) as LongMemEvalItem[]
  if (!Array.isArray(data) || data.length === 0)
    throw new Error(`LongMemEval 语料格式异常：期望非空数组，实际得到 ${typeof data}`)

  return { data, path, source, sha256, checksumMatches, bytes }
}
