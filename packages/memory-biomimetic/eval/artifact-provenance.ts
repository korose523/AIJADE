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
 *
 * ── 可复现性：为什么有`gitSha` 还要 `gitShaAtRun` + `gitDirty` ──────────
 * 一次全量跑十几分钟，期间仓库常会变化：`gitSha` 在**写产物那一刻**求值，可能指向
 * 一个跑完才存在的提交；更糟的是**未提交的产品代码改动**——它会直接改变数字，
 * 却在任何 commit 里都查不到。因此溯源块记录三件事：
 * · `gitSha`      —— 写产物时的 HEAD（既有字段，语义不变）
 * · `gitShaAtRun` —— 模块加载时（≈开跑前）的 HEAD；与上一项不等即说明期间变了
 * · `gitDirty`    —— 跑的时候工作区是否有未提交/未跟踪改动；`true` ⇒ 该数字
 *   **不可按 commit 复现**，进论文前必须先说明或重跑
 * 非 git 环境统一降级为 `'unknown'`，与 `resolveGitSha` 一致，不抛错。
 *
 * 三个字段都是**加法**：`schema` 仍为 `aijade.run_provenance@1`，既有 14 个脚本的
 * 产物结构与调用方式全部不受影响。
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
  /**
   * **模块加载时**（≈脚本启动、跑第一题之前）的 git HEAD。
   *
   * 为什么与 `gitSha` 并存：`gitSha` 在**写产物那一刻**求值，而一次全量跑动辄
   * 十几分钟——期间队友完全可能提交了新commit，于是产物里的 `gitSha` 指向一个
   * **跑完之后**才存在的提交。反过来，读者若拿 `gitSha` 去 `git show` 复现，
   * 看到的是"跑完之后"的代码，而不是实际产出该数字的代码。
   * `gitShaAtRun` 钉住跑的那一刻；两者不一致即说明期间仓库发生了变化。
   *
   * 与 `gitDirty` 配合：`gitSha` 只说"HEAD 是哪个"，`gitDirty` 才说"HEAD 之外
   * 还有没有未提交改动"—— 后者对实验更致命，因为未提交的产品代码改动会直接
   * 改变数字，却在任何 commit 里都查不到。`unknown` 表示非 git 环境。
   */
  gitShaAtRun: string
  /**
   * 运行时工作区是否**不干净**（有已跟踪文件的修改 / 暂存差异 / 未跟踪文件）。
   *
   * `true` 意味着这个产物**不可按commit 复现**：它的数字可能来自尚未入库的代码。
   * 任何要进论文的产物都应为 `false`；若为 `true`，该数字必须先说明未提交改动
   * 是什么（或重跑），否则就是 J4 所指的"数字归属不明"。
   *
   * 非 git 环境返回 `'unknown'`（同 `resolveGitSha` 的降级姿态，不抛错）。
   */
  gitDirty: boolean | 'unknown'
  /** 产物生成时刻（ISO 8601）。 */
  generatedAt: string
}

export interface RunProvenanceOverrides {
  scoreMode?: RetrievalScoreMode
  weights?: RetrievalWeights
  gitSha?: string
  gitShaAtRun?: string
  gitDirty?: boolean | 'unknown'
}

/**
 * 解析当前 git HEAD。写法与 `research-harness` 既有实现保持一致
 * （`execSync('git rev-parse HEAD', { cwd: process.cwd() })`）；取不到时返回
 * `'unknown'` 而非抛错——产物溯源不应让一次长跑在最后一步崩掉。
 */
export function resolveGitSha(): string {
  try {
    // `stdio` 显式丢弃 stderr：非 git 环境是**预期**情形（降级为'unknown'），
    // 让 git 把 `fatal: not a git repository` 打到调用方日志里只会制造噪音，
    // 让人误以为出了故障。
    return execSync('git rev-parse HEAD', { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim()
  }
  catch {
    return 'unknown'
  }
}

/**
 * 判断工作区是否不干净。`git status --porcelain` 只要**有任何输出**即为脏。
 *
 * 覆盖三种情况，缺一不可：已跟踪文件的修改（` M`）、暂存差异（`M `）、未跟踪
 * 文件（`??`）。第三种最容易被漏掉——它同样会改变运行结果（eval 脚本现读现编译
 * `src/**`），却是最不像"改动"的一种。
 *
 * 非 git 环境（`fatal: not a git repository`）返回 `'unknown'` 而非 `false`：
 * `'false'` 是一个**断言**（"工作区确定是干净的"），而无 git 环境时我们什么也
 * 不知道，谎报干净比承认不知道更危险。与 `resolveGitSha` 同样的降级姿态。
 */
export function resolveGitDirty(): boolean | 'unknown' {
  try {
    return execSync('git status --porcelain', { cwd: process.cwd(), stdio: ['ignore', 'pipe', 'ignore'] })
      .toString()
      .trim()
      .length > 0
  }
  catch {
    return 'unknown'
  }
}

/**
 * **跑的那一刻**的 HEAD，在模块加载时抓一次。
 *
 * 必须是模块加载时而不是每次调用时：一次全量跑十几分钟，期间队友会提交；
 * 若等到写产物时才求值，拿到的就是收尾时的 HEAD，无法代表产出该数字的代码。
 * 惰性求值（`??=`）保证同一进程内多次调用只真正执行一次 git。
 */
const gitShaAtRun: string = resolveGitSha()

/** 构造产物溯源块。 */
export function runProvenance(over: RunProvenanceOverrides = {}): RunProvenance {
  return {
    schema: RUN_PROVENANCE_SCHEMA,
    scoreMode: over.scoreMode ?? DEFAULT_MEMORY_CONFIG.retrievalScoreMode,
    weights: { ...(over.weights ?? DEFAULT_MEMORY_CONFIG.weights) },
    gitSha: over.gitSha ?? resolveGitSha(),
    gitShaAtRun: over.gitShaAtRun ?? gitShaAtRun,
    gitDirty: over.gitDirty ?? resolveGitDirty(),
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
