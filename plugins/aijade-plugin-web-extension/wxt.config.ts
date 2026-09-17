import type { WxtViteConfig } from 'wxt'

import UnoCSS from 'unocss/vite'

import { defineConfig } from 'wxt'

type VitePlugin = NonNullable<WxtViteConfig['plugins']>[number]

// See https://wxt.dev/api/config.html
export default defineConfig({
  modules: ['@wxt-dev/module-vue'],
  manifest: {
    name: 'AIJADE Web Extension',
    description: 'Capture web context (videos, pages, subtitles) for Project AIJADE.',
    permissions: ['storage', 'tabs', 'sidePanel', 'identity'],
    optional_host_permissions: [
      '*://*/*',
    ],
    action: {
      default_title: 'AIJADE Web Extension',
    },
    // 侧边栏入口。此处写的 default_path 只是**显式意图**：`wxt build` 实测会把它
    // 覆盖为构建产物路径 `sidepanel.html`（已在 `.output/chrome-mv3/manifest.json`
    // 中确认）。WXT 由 `entrypoints/sidepanel/index.html` 自动识别该入口并写入
    // `sidePanel` 权限，故上面 permissions 里的 `sidePanel` 是冗余但显式的双保险。
    side_panel: {
      default_path: 'entrypoints/sidepanel/index.html',
    },
  },
  vite: () => {
    return {
      plugins: [
        UnoCSS() as VitePlugin,
      ],
    }
  },
})
