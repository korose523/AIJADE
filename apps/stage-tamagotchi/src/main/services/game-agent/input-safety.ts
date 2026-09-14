/**
 * 实操安全网（主进程）。
 *
 * AIJADE 真实操控鼠标键盘时，人必须随时能一键夺回控制权。这里提供三层保护：
 *
 *  1. 全局紧急停止热键（默认 F9）：无论焦点在哪个窗口（包括全屏游戏），
 *     按下即进入 panic 状态——立刻释放所有被按住的键（否则角色会一直往前跑），
 *     并拒绝之后的一切注入，直到用户在面板上显式解除。
 *  2. 令牌桶限速：限制每秒最多注入多少个动作，避免模型抽风时疯狂刷屏操作。
 *  3. 单飞执行：同一时刻只允许一个注入批次在跑，避免按键交错错乱。
 *
 * 所有注入都必须经过本模块，渲染进程无法绕过。
 */
import { app, globalShortcut, ipcMain } from 'electron'

import { releaseAllKeys, runInputActions } from './send-input'

interface SafetyState {
  panic: boolean
  panicHotkey: string
  hotkeyRegistered: boolean
  injectedActions: number
  lastInjectedAt: number
  /** 每秒最多注入的动作数 */
  maxActionsPerSecond: number
  /** 令牌桶 */
  tokens: number
  lastRefill: number
  busy: boolean
  lastError: string
}

const state: SafetyState = {
  panic: false,
  panicHotkey: 'F9',
  hotkeyRegistered: false,
  injectedActions: 0,
  lastInjectedAt: 0,
  maxActionsPerSecond: 20,
  tokens: 20,
  lastRefill: Date.now(),
  busy: false,
  lastError: '',
}

function refillTokens(): void {
  const now = Date.now()
  const elapsed = (now - state.lastRefill) / 1000
  if (elapsed <= 0)
    return
  state.tokens = Math.min(state.maxActionsPerSecond, state.tokens + elapsed * state.maxActionsPerSecond)
  state.lastRefill = now
}

function publicStatus() {
  return {
    panic: state.panic,
    panicHotkey: state.panicHotkey,
    hotkeyRegistered: state.hotkeyRegistered,
    injectedActions: state.injectedActions,
    lastInjectedAt: state.lastInjectedAt,
    maxActionsPerSecond: state.maxActionsPerSecond,
    busy: state.busy,
    lastError: state.lastError || undefined,
  }
}

async function triggerPanic(reason: string): Promise<void> {
  state.panic = true
  state.lastError = ''
  try {
    // 释放所有按住的键，避免"AI 松手了但角色还在跑"
    await releaseAllKeys()
  }
  catch (err) {
    state.lastError = `释放按键失败：${err instanceof Error ? err.message : String(err)}`
  }
  console.warn(`[game-agent] 紧急停止已触发（${reason}）`)
}

function registerHotkey(accelerator: string): boolean {
  globalShortcut.unregister(state.panicHotkey)
  let ok = false
  try {
    ok = globalShortcut.register(accelerator, () => {
      void triggerPanic(`热键 ${accelerator}`)
    })
  }
  catch {
    ok = false
  }
  state.panicHotkey = accelerator
  state.hotkeyRegistered = ok
  return ok
}

export function registerInputSafety(): void {
  registerHotkey('F9')

  app.on('will-quit', () => {
    globalShortcut.unregister(state.panicHotkey)
  })

  /** 受控注入入口：渲染进程只能走这里。 */
  ipcMain.handle('game-agent:send-input', async (_event, actions: unknown) => {
    if (!Array.isArray(actions) || actions.length === 0)
      return { ok: false, reason: 'empty', status: publicStatus() }

    if (state.panic)
      return { ok: false, reason: 'panic', status: publicStatus() }

    if (state.busy)
      return { ok: false, reason: 'busy', status: publicStatus() }

    refillTokens()
    if (state.tokens < actions.length) {
      return { ok: false, reason: 'rate-limited', status: publicStatus() }
    }
    state.tokens -= actions.length

    state.busy = true
    try {
      await runInputActions(actions)
      state.injectedActions += actions.length
      state.lastInjectedAt = Date.now()
      state.lastError = ''
      return { ok: true, status: publicStatus() }
    }
    catch (err) {
      state.lastError = err instanceof Error ? err.message : String(err)
      return { ok: false, reason: 'error', error: state.lastError, status: publicStatus() }
    }
    finally {
      state.busy = false
    }
  })

  ipcMain.handle('game-agent:safety:status', () => publicStatus())

  /** 手动触发紧急停止（面板上的大红按钮）。 */
  ipcMain.handle('game-agent:safety:panic', async () => {
    await triggerPanic('面板手动触发')
    return publicStatus()
  })

  /** 解除紧急停止。 */
  ipcMain.handle('game-agent:safety:resume', () => {
    state.panic = false
    state.tokens = state.maxActionsPerSecond
    state.lastRefill = Date.now()
    return publicStatus()
  })

  ipcMain.handle('game-agent:safety:configure', (_e, opts: { maxActionsPerSecond?: number, panicHotkey?: string } = {}) => {
    if (typeof opts.maxActionsPerSecond === 'number' && opts.maxActionsPerSecond > 0)
      state.maxActionsPerSecond = Math.min(120, Math.round(opts.maxActionsPerSecond))
    if (typeof opts.panicHotkey === 'string' && opts.panicHotkey.trim())
      registerHotkey(opts.panicHotkey.trim())
    return publicStatus()
  })
}
