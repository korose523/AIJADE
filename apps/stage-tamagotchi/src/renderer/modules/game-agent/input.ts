/**
 * 输入后端：把决策动作落到系统。
 *
 * - DryRunInputBackend：只打印动作，不实际按键（默认，安全）。
 * - IpcInputBackend：经主进程 ipc 调用 PowerShell SendInput，真实注入鼠标/键盘。
 *   仅在用户于 UI 中显式开启「自主模式」时才使用。
 */
import type { AgentAction, InputBackend } from './types'

export class DryRunInputBackend implements InputBackend {
  id = 'dry-run'
  name = '演练（不实际按键）'
  readonly safe = true

  async execute(actions: AgentAction[]): Promise<void> {
    for (const a of actions)
      console.info('[game-agent][dry-run]', a.type, a.key ?? a.button ?? '', a.reason ?? '')
  }
}

export class IpcInputBackend implements InputBackend {
  id = 'ipc'
  name = '真实注入（经主进程 SendInput）'
  readonly safe = false

  async execute(actions: AgentAction[]): Promise<void> {
    await window.electron.ipcRenderer.invoke('game-agent:send-input', actions)
  }
}
