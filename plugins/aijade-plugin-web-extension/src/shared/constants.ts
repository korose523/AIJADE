import type { ExtensionSettings } from './types'

export const DEFAULT_WS_URL = 'ws://localhost:6121/ws'

/**
 * 默认 REST base URL：从 `wsUrl` 推导同源 HTTP 地址。
 * 例：`ws://localhost:6121/ws` → `http://localhost:6121`；
 *     `wss://host/ws` → `https://host`。
 * 浏览器扩展默认与 dev server 同源（同 host:port），故直接复用 ws:// 的 host:port
 * 拼 http(s)://。端点路径 `/api/v1/v9/events` 由 `postV9Event` 自行拼接。
 */
export const DEFAULT_REST_BASE_URL = (() => {
  try {
    const ws = new URL(DEFAULT_WS_URL)
    const scheme = ws.protocol === 'wss:' ? 'https' : 'http'
    return `${scheme}://${ws.host}`
  }
  catch {
    return 'http://localhost:6121'
  }
})()

export const DEFAULT_SETTINGS: ExtensionSettings = {
  wsUrl: DEFAULT_WS_URL,
  token: '',
  restBaseUrl: DEFAULT_REST_BASE_URL,
  bearerToken: '',
  enabled: true,
  sendPageContext: true,
  sendVideoContext: true,
  sendSubtitles: true,
  sendSparkNotify: true,
  enableVision: false,
}

export const STORAGE_KEY = 'aijade:web-extension:settings'
