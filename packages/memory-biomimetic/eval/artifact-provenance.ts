/**
 * 产物溯源块（批次 0-3 / M4-3）。
 *
 * 为什么需要它：`commit 014b17b` 改变了检索打分器默认（`retrievalScoreMode` →
 * `standardized`、`dedupeByContent` → true），使旧 `recall@K` 口径失效——同一个
 * "recall@8 = 0.09" 在 additive 与 standardized 下不是同一个量。若不把
 * `scoreMode` / `weights` / `gitSha` 写进产物，读者无法判断一个数字属于哪一次
 * 打分口径，这正是 J4 所指的"数字归属不明"。
 *
 * 用法（各评测脚本在写产物前包一层）：
 *
 *   import { withProvenance } from './artifact-provenance'
 *   writeFileSync(p, `${JSON.stringify(withProvenance(artifact), null, 2)}\n`)
 *
 * 若本脚本覆盖了打分模式或权重（例如用 `CORRECTED_RETRIEVAL_WEIGHTS` 跑
 * recency=0 的修正权重对照），**必须**显式传入，否则产物会谎报口径：
 *
 *   withProvenance(artifact, { weights: CORRECTED_RETRIEVAL_WEIGHTS })
 */

import type { RetrievalScoreMode, RetrievalWeights } from '../src/index'

import process from 'node:process'

import { execSync } from 'node:child_process'

import { DEFAULT_MEMORY_CONFIG } from '../src/index'

/** 产物溯源块的 schema 标识，与 `aijade.experiment_registry@1` 同族。 */
export const RUN_PROVENANCE_SCHEMA = 'aijade.run_provenance@1'

export interface RunProvenance {
  schema: typeof RUN_PROVENANCE_SCHEMA
  /** 本次运行生效的检索打分模式（缺省取 `DEFAULT_MEMORY_CONFIG.retrievalScoreMode`）。 */
  scoreMode: RetrievalScoreMode
  /** 本次运行生效的检索权重（缺省取 `DEFAULT_MEMORY_CONFIG.weights`）。 */
  weights: RetrievalWeights
  /** 运行时的 git HEAD；非 git 环境或取不到时为 `'unknown'`。 */
  gitSha: string
  /** 产物生成时刻（ISO 8601）。 */
  generatedAt: string
}

export interface RunProvenanceOverrides {
  scoreMode?: RetrievalScoreMode
  weights?: RetrievalWeights
  gitSha?: string
}

/**
 * 解析当前 git HEAD。写法与 `research-harness` 既有实现保持一致
 * （`execSync('git rev-parse HEAD', { cwd: process.cwd() })`）；取不到时返回
 * `'unknown'` 而非抛错——产物溯源不应让一次长跑在最后一步崩掉。
 */
export function resolveGitSha(): string {
  try {
    return execSync('git rev-parse HEAD', { cwd: process.cwd() })
      .toString()
      .trim()
  }
  catch {
    return 'unknown'
  }
}

/** 构造产物溯源块。 */
export function runProvenance(over: RunProvenanceOverrides = {}): RunProvenance {
  return {
    schema: RUN_PROVENANCE_SCHEMA,
    scoreMode: over.scoreMode ?? DEFAULT_MEMORY_CONFIG.retrievalScoreMode,
    weights: { ...(over.weights ?? DEFAULT_MEMORY_CONFIG.weights) },
    gitSha: over.gitSha ?? resolveGitSha(),
    generatedAt: new Date().toISOString(),
  }
}

/**
 * 把溯源块并入产物。若产物自身已带 `provenance`，**以产物自带的为准**——
 * 不静默改写脚本作者显式写下的口径。
 */
export function withProvenance<T extends object>(
  artifact: T,
  over: RunProvenanceOverrides = {},
): T & { provenance: RunProvenance } {
  const existing = (artifact as { provenance?: RunProvenance }).provenance
  return { ...artifact, provenance: existing ?? runProvenance(over) }
}
