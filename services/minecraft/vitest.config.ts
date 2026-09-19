import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    exclude: ['src/agents/action/*.test.ts'],
    // isolated-vm 沙箱（js-planner）会 fork 子进程执行用户脚本：多文件并行时
    // 曾出现子进程 SIGSEGV（资源竞争）导致假失败。串行执行文件可稳定复现。
    fileParallelism: false,
  },
})
