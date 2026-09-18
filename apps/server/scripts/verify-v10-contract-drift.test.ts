import { describe, expect, it } from 'vitest'

import { runContractDriftMatrix } from './verify-v10-contract-drift'

/**
 * P3-5：把契约漂移矩阵的 **PGlite 腿**（内存 Postgres 引擎，无需真库）下沉为
 * vitest 用例 —— 矩阵失败随 `vitest run` 进 CI 红灯，而不是依赖有人手动跑
 * `verify:*` 脚本（报告 P3-5：验收脚本是手动 tsx 命令，失败无法进入 CI）。
 *
 * 真实 PostgreSQL 腿仍保留为 CLI（`--postgres` + `DATABASE_URL`，需真库），
 * 与报告"需要真库的部分保留为 verify:*"的边界一致。
 *
 * 断言语义与脚本内 `check()` 一致：任何一条 dual-end 断言失败 ⇒ `failures > 0`
 * ⇒ 本用例红。
 */
describe('v10 contract-drift matrix — PGlite leg (P3-5)', () => {
  it('passes every dual-end assertion: kernel/HTTP agreement, 400 + no-write negatives, topic guard', async () => {
    const { failures } = await runContractDriftMatrix({ postgres: false })
    expect(failures).toBe(0)
  }, 120_000)
})
