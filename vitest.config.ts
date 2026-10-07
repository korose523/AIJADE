import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vitest/config'

/**
 * 项目根的绝对路径。
 *
 * ⚠️ 为什么必须显式绝对化：`projects` 里的相对路径是**按当前工作目录（CWD）解析**的。
 * 曾经这里写的是裸相对路径 `'apps/server'`，于是从任何子目录（例如
 * `plugins/aijade-plugin-web-extension`）执行 `vitest run` 时，vitest 会去找
 * `plugins/aijade-plugin-web-extension/apps/server` 并直接报
 * `Startup Error: Projects definition references a non-existing file or a directory`
 * ——测试连启动都启动不了。用 `import.meta.url` 派生绝对路径后，
 * 从任何 CWD 运行都解析到同一组项目。
 */
const repoRoot = dirname(fileURLToPath(import.meta.url))

/**
 * 纳入统一测试的 workspace。
 *
 * 注意：这里必须与「实际存在测试的包」保持同步 —— 一个包只要**不在**此列表中，
 * 它的测试就永远不会在任何自动化运行里被执行（`plugins/aijade-plugin-web-extension`
 * 曾有 77 个测试长期游离于本列表之外，就是这么发生的）。
 */
const projects = [
  'apps/server',
  'apps/ui-server-auth',
  'apps/stage-tamagotchi',
  'packages/audio-pipelines-transcribe',
  'packages/cap-vite',
  'packages/core-agent',
  'packages/memory-pgvector',
  // 记忆生物学包（检索打分 / 记忆动力学 / 固化 / 评测脚本）。
  // 此前不在列表中，本包 723 个测试（含 `eval/**`）全部游离于统一 CI 之外。
  'packages/memory-biomimetic',
  // 转向评测 harness（度保持随机化 + 扰动恢复 PRR/RC）。
  // 与上面同源的问题：新建包若不登记，其 vitest 用例永远不会在统一运行里执行。
  'packages/steering-benchmark',
  'packages/vishot-runner-browser',
  'packages/plugin-sdk',
  'packages/plugin-sdk-tamagotchi',
  'packages/server-runtime',
  'packages/server-sdk',
  'packages/stage-shared',
  'packages/stage-ui-three',
  // v10 浏览器侧（侧边栏 / 网页助手 / 证据归约 / OIDC PKCE）——
  // 此前不在列表内，77 个测试无人执行。
  'plugins/aijade-plugin-web-extension',
]

export default defineConfig({
  test: {
    projects: projects.map(dir => resolve(repoRoot, dir)),
  },
})
