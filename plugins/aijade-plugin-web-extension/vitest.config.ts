import { defineConfig } from 'vitest/config'

/**
 * 本包的独立测试配置。
 *
 * 为什么需要它：此前本包**没有任何 vitest 配置**，于是从本目录执行 `vitest run` 会向上
 * 找到仓库根的 `vitest.config.ts`（那份配置是「多项目聚合」形态），结果是
 * ① 启动即因 projects 相对路径解析失败而报错，② 即使不报错也会跑去跑整个 monorepo。
 * 有了本文件，`pnpm test`（本目录）与根配置里作为 project 被引用，两种用法都只跑本包。
 *
 * 测试全部是纯 TS 单元测试（PKCE / REST 上报 / 证据归约 / 存储），不依赖 WXT 运行时，
 * 故统一用 node 环境、只收 `src/**\/*.test.ts`，刻意**不**引入 wxt 的 vite 插件
 * （wxt 插件会要求 `.wxt/` 生成产物存在，会让纯单测产生无谓的构建依赖）。
 */
export default defineConfig({
  test: {
    name: 'aijade-plugin-web-extension',
    include: ['src/**/*.test.ts'],
    environment: 'node',
  },
})
