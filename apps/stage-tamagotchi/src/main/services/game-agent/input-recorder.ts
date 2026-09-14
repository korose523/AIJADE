/**
 * 真机学习 —— 真人操作录制器（主进程）。
 *
 * 目标：AIJADE 在旁边「看着人类玩」，同步记录人类按了什么键、点了哪里、鼠标怎么动，
 * 与画面关键帧配对后形成示范数据（demonstration），供后续提炼成可复用经验。
 *
 * 实现方式：启动一个常驻 PowerShell 进程，在内嵌 C# 里以 ~15ms 周期轮询
 * user32 的 GetAsyncKeyState / GetCursorPos，检测状态变化后把事件以 JSON 行
 * 写到 stdout。这样零原生依赖（不需要 uiohook 之类的 napi 模块），也不安装
 * 低级键盘钩子（WH_KEYBOARD_LL），对游戏反作弊更友好——它只是读取按键状态，
 * 和任务管理器读取系统信息属于同一层级。
 *
 * 已知限制：轮询采样无法捕获滚轮事件，极短促的连击（<15ms）可能漏采。
 * 这对「学习人类打法」的用途完全够用。
 */
import type { ChildProcess } from 'node:child_process'

import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { app, ipcMain } from 'electron'

import { minimalPowerShellEnv } from './ps-env'

export interface RecordedInputEvent {
  t: number
  kind: 'key' | 'mouse' | 'move'
  key?: string
  button?: 'left' | 'right' | 'middle'
  down?: boolean
  x?: number
  y?: number
}

// 内嵌 PowerShell + C#。注意：本模板字符串内不得出现 ${ 或反引号。
const PS_RECORDER = `
param(
  [int]$SampleMs = 15,
  [int]$MoveThrottleMs = 80,
  [int]$MoveMinDelta = 6,
  [int]$MaxMs = 0
)

$ErrorActionPreference = 'Stop'

Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;

public class HumanRecorder {
  [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vKey);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT lpPoint);

  [StructLayout(LayoutKind.Sequential)]
  public struct POINT { public int X; public int Y; }

  static Dictionary<int, string> BuildMap() {
    Dictionary<int, string> m = new Dictionary<int, string>();
    m[0x01] = "mouse:left";
    m[0x02] = "mouse:right";
    m[0x04] = "mouse:middle";
    for (int c = 0x41; c <= 0x5A; c++) m[c] = ((char)(c + 32)).ToString();
    for (int c = 0x30; c <= 0x39; c++) m[c] = ((char)c).ToString();
    for (int c = 0x70; c <= 0x7B; c++) m[c] = "f" + (c - 0x6F).ToString();
    m[0x20] = "space";
    m[0x09] = "tab";
    m[0x1B] = "esc";
    m[0x0D] = "enter";
    m[0x08] = "backspace";
    m[0x10] = "shift";
    m[0x11] = "ctrl";
    m[0x12] = "alt";
    m[0x25] = "left";
    m[0x26] = "up";
    m[0x27] = "right";
    m[0x28] = "down";
    // 不再单独映射 0xA0/0xA2/0xA4（左 shift/ctrl/alt）：它们与 0x10/0x11/0x12
    // 的通用修饰键会同时触发，导致同一次按键被记两遍。
    return m;
  }

  static string Esc(string s) {
    return s.Replace("\\\\", "\\\\\\\\").Replace("\\"", "\\\\\\"");
  }

  public static void Loop(int sampleMs, int moveThrottleMs, int moveMinDelta, int maxMs) {
    Dictionary<int, string> map = BuildMap();
    Dictionary<int, bool> prev = new Dictionary<int, bool>();
    foreach (int k in map.Keys) prev[k] = false;

    List<int> keys = new List<int>(map.Keys);
    DateTime start = DateTime.UtcNow;
    long lastMoveEmit = 0;
    int lastX = -99999, lastY = -99999;

    Console.WriteLine("{\\"kind\\":\\"ready\\"}");
    Console.Out.Flush();

    while (true) {
      long t = (long)(DateTime.UtcNow - start).TotalMilliseconds;
      if (maxMs > 0 && t >= maxMs) break;

      for (int i = 0; i < keys.Count; i++) {
        int vk = keys[i];
        bool down = (GetAsyncKeyState(vk) & 0x8000) != 0;
        if (down != prev[vk]) {
          prev[vk] = down;
          string name = map[vk];
          string line;
          if (name.StartsWith("mouse:")) {
            line = "{\\"t\\":" + t + ",\\"kind\\":\\"mouse\\",\\"button\\":\\"" + Esc(name.Substring(6)) + "\\",\\"down\\":" + (down ? "true" : "false") + "}";
          } else {
            line = "{\\"t\\":" + t + ",\\"kind\\":\\"key\\",\\"key\\":\\"" + Esc(name) + "\\",\\"down\\":" + (down ? "true" : "false") + "}";
          }
          Console.WriteLine(line);
        }
      }

      if (t - lastMoveEmit >= moveThrottleMs || lastX == -99999) {
        POINT p;
        if (GetCursorPos(out p)) {
          bool first = (lastX == -99999);
          long dx = (long)p.X - (long)lastX;
          long dy = (long)p.Y - (long)lastY;
          if (first || dx * dx + dy * dy >= (long)moveMinDelta * (long)moveMinDelta) {
            lastX = p.X; lastY = p.Y;
            Console.WriteLine("{\\"t\\":" + t + ",\\"kind\\":\\"move\\",\\"x\\":" + p.X + ",\\"y\\":" + p.Y + "}");
          }
        }
        lastMoveEmit = t;
      }

      Console.Out.Flush();
      Thread.Sleep(sampleMs);
    }
  }
}
'@

[HumanRecorder]::Loop($SampleMs, $MoveThrottleMs, $MoveMinDelta, $MaxMs)
`

interface RecorderState {
  proc: ChildProcess | null
  events: RecordedInputEvent[]
  startedAt: number
  error: string
  ready: boolean
  /** 已被渲染进程拉取到的事件游标 */
  cursor: number
}

const state: RecorderState = {
  proc: null,
  events: [],
  startedAt: 0,
  error: '',
  ready: false,
  cursor: 0,
}

export interface RecorderStartOptions {
  /** 采样周期，默认 15ms */
  sampleMs?: number
  /** 鼠标位置最小上报间隔，默认 80ms */
  moveThrottleMs?: number
  /** 鼠标最小位移阈值（像素），默认 6 */
  moveMinDelta?: number
  /** 事件缓冲上限，默认 200000 */
  maxEvents?: number
}

let maxEvents = 200000
let scriptPath: string | null = null

function ensureScript(): string {
  if (scriptPath)
    return scriptPath
  const dir = join(app.getPath('userData'), 'game-agent')
  mkdirSync(dir, { recursive: true })
  scriptPath = join(dir, 'input-recorder.ps1')
  writeFileSync(scriptPath, PS_RECORDER, 'utf8')
  return scriptPath
}

function stopProcess(): void {
  if (state.proc) {
    try {
      state.proc.kill()
    }
    catch {
      // ignore
    }
    state.proc = null
  }
}

function startRecorder(opts: RecorderStartOptions): void {
  stopProcess()
  state.events = []
  state.cursor = 0
  state.error = ''
  state.ready = false
  state.startedAt = Date.now()
  maxEvents = opts.maxEvents ?? 200000

  const sampleMs = opts.sampleMs ?? 15
  const moveThrottleMs = opts.moveThrottleMs ?? 80
  const moveMinDelta = opts.moveMinDelta ?? 6

  const script = ensureScript()
  const proc = spawn('powershell', [
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    script,
    '-SampleMs',
    String(sampleMs),
    '-MoveThrottleMs',
    String(moveThrottleMs),
    '-MoveMinDelta',
    String(moveMinDelta),
  ], {
    windowsHide: true,
    // 必须精简环境块，否则 Add-Type 拉起 csc.exe 会因环境块 >64KB 失败
    env: minimalPowerShellEnv(),
  })
  state.proc = proc

  let buffer = ''
  proc.stdout?.setEncoding('utf8')
  proc.stdout?.on('data', (chunk: string) => {
    buffer += chunk
    let idx = buffer.indexOf('\n')
    while (idx >= 0) {
      const line = buffer.slice(0, idx).trim()
      buffer = buffer.slice(idx + 1)
      idx = buffer.indexOf('\n')
      if (!line)
        continue
      try {
        // 脚本除了事件行还会先发一行 {"kind":"ready"}，所以这里用宽松类型再收窄
        const ev = JSON.parse(line) as Omit<RecordedInputEvent, 'kind'> & { kind: string }
        if (ev.kind === 'ready') {
          state.ready = true
          continue
        }
        state.events.push(ev as RecordedInputEvent)
        if (state.events.length > maxEvents) {
          const overflow = state.events.length - maxEvents
          state.events.splice(0, overflow)
          state.cursor = Math.max(0, state.cursor - overflow)
        }
      }
      catch {
        // 忽略非 JSON 行（PowerShell 噪声）
      }
    }
  })

  proc.stderr?.setEncoding('utf8')
  proc.stderr?.on('data', (chunk: string) => {
    const text = String(chunk).trim()
    if (text)
      state.error = text.slice(0, 500)
  })

  proc.on('exit', (code) => {
    if (state.proc === proc) {
      state.proc = null
      if (code !== 0 && code !== null && !state.error)
        state.error = `录制进程退出，code=${code}`
    }
  })

  proc.on('error', (err) => {
    state.error = err.message
    if (state.proc === proc)
      state.proc = null
  })
}

function status() {
  return {
    running: state.proc !== null,
    ready: state.ready,
    eventCount: state.events.length,
    startedAt: state.startedAt,
    error: state.error || undefined,
  }
}

export function registerInputRecorder(): void {
  ipcMain.handle('game-agent:recorder:start', (_e, opts: RecorderStartOptions = {}) => {
    startRecorder(opts ?? {})
    return status()
  })

  ipcMain.handle('game-agent:recorder:stop', () => {
    stopProcess()
    return { ...status(), events: state.events }
  })

  /** 增量拉取：只返回上次拉取之后的新事件，避免重复传输。 */
  ipcMain.handle('game-agent:recorder:poll', () => {
    const events = state.events.slice(state.cursor)
    state.cursor = state.events.length
    return { ...status(), events }
  })

  /** 全量取回（停止后用于保存 Episode）。 */
  ipcMain.handle('game-agent:recorder:dump', () => {
    return { ...status(), events: state.events }
  })
}

export function shutdownInputRecorder(): void {
  stopProcess()
}
