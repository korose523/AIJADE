import type { ExtensionSettings } from '../shared/types'

import { DEFAULT_SETTINGS, STORAGE_KEY } from '../shared/constants'
import { uuid } from '../shared/v9-rest'

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

/**
 * 扩展级持久化安装身份（观察「归属哪个会话」的真源）。
 *
 * 扩展首次运行时铸造一个 UUID，写入 `browser.storage.local`，此后每次返回**同一个**值。
 * 它跨标签页、跨 service worker 重启稳定——因为就存在持久化存储里，SW 重启后从落盘读回，
 * 不会像 `nanoid()` 那样每次进程启动重新随机。本 id 同时用作两个身份（见 client.ts 的真实不变量）：
 *   1. tick 计数器的会话键（`advanceTick`）；
 *   2. 观察事件 payload 的 `session_id`（v10-evidence 归约器注入）。
 *
 * 用 `uuid()`（来自 v9-rest，内部优先 `crypto.randomUUID()`，绝不用 `Date.now()`）。
 * 绝不在每次调用时重铸：先读、无则写、再返回。并发调用共享同一 promise，
 * 避免首跑窗口内两个 handler 各自铸出不同 id、破坏"tick 键 === session_id"不变量。
 */
const INSTALL_ID_STORAGE_KEY = 'aijade:web-extension:install-id'

let installIdPromise: Promise<string> | null = null

export function getOrCreateInstallId(): Promise<string> {
  if (installIdPromise)
    return installIdPromise

  installIdPromise = (async () => {
    const stored = await browser.storage.local.get(INSTALL_ID_STORAGE_KEY)
    const existing = stored[INSTALL_ID_STORAGE_KEY]
    if (typeof existing === 'string' && existing.length > 0)
      return existing

    const id = uuid()
    await browser.storage.local.set({ [INSTALL_ID_STORAGE_KEY]: id })
    return id
  })()

  return installIdPromise
}
