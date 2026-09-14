import { mergeConfigs, presetWebFonts } from 'unocss'

import { presetWebFontsFonts, sharedUnoConfig } from '../../uno.config'

export default mergeConfigs([
  sharedUnoConfig(),
  {
    presets: [
      presetWebFonts({
        // 不在构建期内联字体（fontsource provider 会在 build 时请求 api.fontsource.org）。
        // inlineImports:false -> 由浏览器运行时按需 @import 加载，取不到自动回退系统字体。
        inlineImports: false,
        // 关键修复：默认 fetcher 在网络失败时会 reject，而 preset-web-fonts 内部用
        // Promise.race(timeout) 包裹它——超时 reject 后，那个还在 pending 的 fetch
        // 变成 unhandledRejection，直接把 Vite 进程干掉(ELIFECYCLE / 0xC000013A)。
        // 这里用「永不 reject」的 customFetch 兜住：任何网络异常都返回空 Response，
        // 构建期再也不会崩溃；字体在运行时由浏览器按需加载(失败自动回退系统字体)。
        customFetch: async (url: string) => {
          try {
            // 自带 8s 中止：网络黑洞时 fetch 不会无限挂起；超时/异常一律被 catch 兜住，
            // 返回字段齐全的最小合法对象，getPreflight 据此跳过该字体预生成(运行时浏览器按需加载)。
            const res = await fetch(url, { signal: AbortSignal.timeout(8000) })
            if (!res.ok)
              throw new Error(`HTTP ${res.status}`)
            return await res.json()
          }
          catch {
            return { subsets: [], weights: [], unicodeRange: {}, variants: {}, family: '' }
          }
        },
        fonts: {
          ...presetWebFontsFonts('fontsource'),
        },
        // 关掉 preset 内部的 Promise.race 超时 reject（那个 reject 绕过了上面的 customFetch，
        // 被 getPreflight 捕获后打出 "Failed to fetch font" 警告）。超时保护已交给 customFetch
        // 的 AbortSignal，所以这里设为 false 既不会崩、也不再有超时警告。
        timeouts: false,
      }),
    ],
    rules: [
      ['transition-colors-none', {
        'transition-property': 'color, background-color, border-color, text-color',
        'transition-duration': '0s',
      }],
    ],
  },
])
