/**
 * 真人操作录制器（渲染端封装）。
 *
 * 与主进程 input-recorder 通信：主进程负责真正的全局键鼠采样，
 * 这里只做 IPC 调用与增量拉取。
 */
import type { InputEvent, RecorderPollResult, RecorderStatus } from './types'

export interface RecorderStartOptions {
  sampleMs?: number
  moveThrottleMs?: number
  moveMinDelta?: number
  maxEvents?: number
}

function ipc() {
  return window.electron.ipcRenderer
}

export async function startRecorder(opts: RecorderStartOptions = {}): Promise<RecorderStatus> {
  return await ipc().invoke('game-agent:recorder:start', opts) as RecorderStatus
}

export async function stopRecorder(): Promise<RecorderPollResult> {
  return await ipc().invoke('game-agent:recorder:stop') as RecorderPollResult
}

/** 增量拉取自上次调用以来的新事件。 */
export async function pollRecorder(): Promise<RecorderPollResult> {
  return await ipc().invoke('game-agent:recorder:poll') as RecorderPollResult
}

export async function dumpRecorder(): Promise<RecorderPollResult> {
  return await ipc().invoke('game-agent:recorder:dump') as RecorderPollResult
}

/** 把一段时间窗内的事件压缩成人类可读的操作串，例如 "w↓ 左键 space w↑"。 */
export function describeEvents(events: InputEvent[]): string[] {
  const out: string[] = []
  for (const ev of events) {
    if (ev.kind === 'key' && ev.key)
      out.push(ev.down ? `${ev.key}↓` : `${ev.key}↑`)
    else if (ev.kind === 'mouse' && ev.button)
      out.push(`${ev.button === 'left' ? '左键' : ev.button === 'right' ? '右键' : '中键'}${ev.down ? '↓' : '↑'}`)
  }
  return out
}
