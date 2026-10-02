import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'

const __dirname = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  root: __dirname,
  test: {
    name: '@proj-aijade/memory-biomimetic',
    // `eval/` 也纳入：`artifact-provenance.ts` 等被 14 个评测脚本共用的模块住在
    // 这里，它们的测试若不在 include 内就会**永远不被执行**（而不是失败）——
    // 这正是本文件顶部注释所说的"测试游离于列表之外"那类静默失效。
    // 这是纯加法：`src/**` 的既有收集范围完全不变。
    include: ['src/**/*.test.ts', 'eval/**/*.test.ts'],
  },
})
