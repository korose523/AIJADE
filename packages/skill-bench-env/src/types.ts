export type BenchCategory = 'string' | 'array' | 'object' | 'math' | 'date' | 'parsing' | 'logic'

export type BenchTier = 'easy' | 'medium' | 'hard'

export interface BenchCase {
  args: unknown[]
  expected: unknown
}

export interface BenchTask {
  id: string
  instruction: string // 给模型的自然语言规格
  tests: BenchCase[] // 确定性 ground truth，每任务 3-6 条
  category: BenchCategory
  tier: BenchTier
  timeoutMs?: number
}

export interface BenchFailure {
  index: number
  args: unknown[]
  expected: unknown
  actual?: unknown
  error?: string
}

export interface ExecutionVerdict {
  ok: boolean // 全部用例通过
  passed: number
  total: number
  durationMs: number
  failures: BenchFailure[]
  error?: string // 沙箱级错误：语法错、超时、加载即抛
}
