import type { ExtensionSettings } from '../shared/types'

import { DEFAULT_SETTINGS, STORAGE_KEY } from '../shared/constants'

export async function loadSettings(): Promise<ExtensionSettings> {
  const stored = await browser.storage.local.get(STORAGE_KEY)
  const value = stored[STORAGE_KEY] as ExtensionSettings | undefined
  return {
    ...DEFAULT_SETTINGS,
    ...value,
  }
}

export async function saveSettings(partial: Partial<ExtensionSettings>): Promise<ExtensionSettings> {
  const next = {
    ...DEFAULT_SETTINGS,
    ...(await loadSettings()),
    ...partial,
  }

  await browser.storage.local.set({ [STORAGE_KEY]: next })
  return next
}

/**
 * v10 事件确定性排序用的每会话 tick 计数器。
 *
 * 结构：`{ [sessionKey]: nextTick }`，持久化在 `browser.storage.local`，
 * 因此跨 service worker 重启**不回退**（`advanceTick` 先读再 +1 再写回）。
 * 不"跳号到不可复现的值"：tick 只单调递增、由本函数唯一推进，不依赖 `Date.now()`
 * 之类会重排的时钟，故重启后从落盘值继续，不会重复也不会乱序。
 */
const TICKS_STORAGE_KEY = 'aijade:web-extension:v9-ticks'

type TickMap = Record<string, number>

async function readTickMap(): Promise<TickMap> {
  const stored = await browser.storage.local.get(TICKS_STORAGE_KEY)
  return (stored[TICKS_STORAGE_KEY] as TickMap | undefined) ?? {}
}

/** 读当前 nextTick（不推进）；不存在则返回 0。 */
export async function readTick(sessionKey: string): Promise<number> {
  const map = await readTickMap()
  return map[sessionKey] ?? 0
}

/** 推进并返回下一个 tick：先读、+1、写回，保证跨 SW 重启不回退。 */
export async function advanceTick(sessionKey: string): Promise<number> {
  const map = await readTickMap()
  const next = (map[sessionKey] ?? 0) + 1
  map[sessionKey] = next
  await browser.storage.local.set({ [TICKS_STORAGE_KEY]: map })
  return next
}
