import type { ExtensionStatus } from './types'

import { defineInvoke } from '@moeru/eventa'

import { backgroundStatusChanged } from './eventa'
import { createRuntimeEventaContext } from './eventa-runtime'
import { sidepanelRequestEvidence } from './eventa-sidepanel'

/**
 * 侧边栏的 eventa 桥接：完全复用既有的 `createRuntimeEventaContext()` 运行时
 * （基于 `browser.runtime.sendMessage` / `onMessage` 的同源通道），与 popup 同机制。
 * 不新造通信层。
 */
const { context } = createRuntimeEventaContext()

export const requestEvidence = defineInvoke(context, sidepanelRequestEvidence)

/** 订阅 background 推送的状态变更（复用既有 `backgroundStatusChanged` 事件）。 */
export function onBackgroundStatus(callback: (status: ExtensionStatus) => void) {
  const off = context.on(backgroundStatusChanged, (event) => {
    callback(event.body!)
  })

  return () => off()
}
