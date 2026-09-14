import { execFile } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 游戏 Agent 输入注入（主进程）—— 实操部分的"手"。
 *
 * 通过 PowerShell + user32 SendInput 注入鼠标/键盘，避免引入原生 Node 模块。
 * 脚本内嵌，首次运行时写到 userData 目录。
 *
 * 重要实现说明：
 * INPUT 是嵌套值类型（struct 里套 union）。在 PowerShell 中写
 *   $inp.data.ki.wVk = 1
 * 只会修改属性访问返回的**副本**，永远写不回原结构体——这会导致 SendInput
 * 发出一堆空事件，看起来"没报错但游戏毫无反应"。因此这里把结构体构造与
 * SendInput 调用全部下沉到 C#，PowerShell 只负责解析 JSON 后调用静态方法。
 *
 * 安全：本 handler 受 input-safety 的紧急停止 / 限速约束；默认渲染端走 dry-run，
 * 只有用户显式开启自主模式才会走到这里。
 */
import { app } from 'electron'

import { minimalPowerShellEnv } from './ps-env'

// 内嵌 PowerShell（SendInput P/Invoke）。本模板字符串内不得出现 ${ 或反引号。
const PS_SCRIPT = `
param(
  [Parameter(Mandatory=$true)] [string]$ActionJson
)

$ErrorActionPreference = 'Stop'
$actions = $ActionJson | ConvertFrom-Json

Add-Type @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public class GAI {
  public const uint INPUT_MOUSE = 0;
  public const uint INPUT_KEYBOARD = 1;
  public const uint MOUSEEVENTF_MOVE = 0x0001;
  public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const uint MOUSEEVENTF_RIGHTDOWN = 0x0008;
  public const uint MOUSEEVENTF_RIGHTUP = 0x0010;
  public const uint MOUSEEVENTF_MIDDLEDOWN = 0x0020;
  public const uint MOUSEEVENTF_MIDDLEUP = 0x0040;
  public const uint MOUSEEVENTF_WHEEL = 0x0800;
  public const uint KEYEVENTF_KEYUP = 0x0002;
  public const uint KEYEVENTF_SCANCODE = 0x0008;

  [StructLayout(LayoutKind.Sequential)]
  public struct INPUT { public uint type; public InputUnion data; }
  [StructLayout(LayoutKind.Explicit)]
  public struct InputUnion {
    [FieldOffset(0)] public MOUSEINPUT mi;
    [FieldOffset(0)] public KEYBDINPUT ki;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct MOUSEINPUT {
    public int dx; public int dy; public uint mouseData;
    public uint dwFlags; public uint time; public IntPtr extraInfo;
  }
  [StructLayout(LayoutKind.Sequential)]
  public struct KEYBDINPUT {
    public ushort wVk; public ushort wScan; public uint dwFlags;
    public uint time; public IntPtr extraInfo;
  }

  [DllImport("user32.dll", SetLastError=true)]
  public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int nIndex);
  [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int vKey);
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint uCode, uint uMapType);

  static int Size() { return Marshal.SizeOf(typeof(INPUT)); }

  public static Dictionary<string, int> Map() {
    Dictionary<string, int> m = new Dictionary<string, int>();
    for (int c = 0x41; c <= 0x5A; c++) m[((char)(c + 32)).ToString()] = c;
    for (int c = 0x30; c <= 0x39; c++) m[((char)c).ToString()] = c;
    for (int c = 0x70; c <= 0x7B; c++) m["f" + (c - 0x6F).ToString()] = c;
    m["space"] = 0x20; m["tab"] = 0x09; m["esc"] = 0x1B; m["escape"] = 0x1B;
    m["enter"] = 0x0D; m["return"] = 0x0D; m["backspace"] = 0x08;
    m["shift"] = 0xA0; m["lshift"] = 0xA0; m["rshift"] = 0xA1;
    m["ctrl"] = 0xA2; m["lctrl"] = 0xA2; m["rctrl"] = 0xA3; m["control"] = 0xA2;
    m["alt"] = 0xA4; m["lalt"] = 0xA4; m["ralt"] = 0xA5;
    m["left"] = 0x25; m["up"] = 0x26; m["right"] = 0x27; m["down"] = 0x28;
    return m;
  }

  public static int Vk(string name) {
    if (name == null) return -1;
    Dictionary<string, int> m = Map();
    string k = name.ToLower().Trim();
    if (m.ContainsKey(k)) return m[k];
    return -1;
  }

  /**
   * 键盘注入。使用扫描码（KEYEVENTF_SCANCODE）而非纯虚拟键：
   * 大量游戏（尤其 DirectInput / RawInput 引擎）只识别扫描码，
   * 只发 wVk 会出现"系统能收到但游戏没反应"的情况。
   */
  public static uint Key(int vk, bool down) {
    if (vk < 0) return 0;
    INPUT[] inp = new INPUT[1];
    inp[0].type = INPUT_KEYBOARD;
    inp[0].data.ki.wVk = (ushort)vk;
    inp[0].data.ki.wScan = (ushort)MapVirtualKey((uint)vk, 0);
    uint flags = KEYEVENTF_SCANCODE;
    if (!down) flags = flags | KEYEVENTF_KEYUP;
    inp[0].data.ki.dwFlags = flags;
    return SendInput(1, inp, Size());
  }

  public static uint KeyByName(string name, bool down) {
    return Key(Vk(name), down);
  }

  static uint MouseFlag(string button, bool down) {
    string b = (button == null) ? "left" : button.ToLower();
    if (b == "right") return down ? MOUSEEVENTF_RIGHTDOWN : MOUSEEVENTF_RIGHTUP;
    if (b == "middle") return down ? MOUSEEVENTF_MIDDLEDOWN : MOUSEEVENTF_MIDDLEUP;
    return down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP;
  }

  public static uint Click(string button, bool down) {
    INPUT[] inp = new INPUT[1];
    inp[0].type = INPUT_MOUSE;
    inp[0].data.mi.dwFlags = MouseFlag(button, down);
    return SendInput(1, inp, Size());
  }

  public static uint MoveRelative(int dx, int dy) {
    INPUT[] inp = new INPUT[1];
    inp[0].type = INPUT_MOUSE;
    inp[0].data.mi.dx = dx;
    inp[0].data.mi.dy = dy;
    inp[0].data.mi.dwFlags = MOUSEEVENTF_MOVE;
    return SendInput(1, inp, Size());
  }

  public static uint MoveAbsolute(int x, int y) {
    int w = GetSystemMetrics(0);
    int h = GetSystemMetrics(1);
    if (w <= 0) w = 1920;
    if (h <= 0) h = 1080;
    INPUT[] inp = new INPUT[1];
    inp[0].type = INPUT_MOUSE;
    inp[0].data.mi.dx = (int)(((long)x * 65535) / w);
    inp[0].data.mi.dy = (int)(((long)y * 65535) / h);
    inp[0].data.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE;
    return SendInput(1, inp, Size());
  }

  public static uint Wheel(int delta) {
    INPUT[] inp = new INPUT[1];
    inp[0].type = INPUT_MOUSE;
    inp[0].data.mi.dwFlags = MOUSEEVENTF_WHEEL;
    inp[0].data.mi.mouseData = unchecked((uint)delta);
    return SendInput(1, inp, Size());
  }

  /** 紧急停止时调用：把当前处于按下状态的常用键与鼠标键全部释放，避免角色"卡住一直往前跑"。 */
  public static int ReleaseAll() {
    int released = 0;
    Dictionary<string, int> m = Map();
    foreach (KeyValuePair<string, int> kv in m) {
      if ((GetAsyncKeyState(kv.Value) & 0x8000) != 0) {
        Key(kv.Value, false);
        released++;
      }
    }
    string[] buttons = new string[] { "left", "right", "middle" };
    int[] vks = new int[] { 0x01, 0x02, 0x04 };
    for (int i = 0; i < 3; i++) {
      if ((GetAsyncKeyState(vks[i]) & 0x8000) != 0) {
        Click(buttons[i], false);
        released++;
      }
    }
    return released;
  }
}
'@

function Get-Ms($value, $fallback) {
  if ($null -eq $value) { return $fallback }
  try { return [int]$value } catch { return $fallback }
}

foreach ($a in $actions) {
  switch ($a.type) {
    'move'         { [GAI]::MoveAbsolute([int]$a.x, [int]$a.y) | Out-Null }
    'moveRelative' { [GAI]::MoveRelative([int]$a.x, [int]$a.y) | Out-Null }
    'click' {
      $btn = if ($null -eq $a.button) { 'left' } else { [string]$a.button }
      [GAI]::Click($btn, $true) | Out-Null
      Start-Sleep -Milliseconds 25
      [GAI]::Click($btn, $false) | Out-Null
    }
    'key' {
      $vk = [GAI]::Vk([string]$a.key)
      if ($vk -ge 0) {
        if ($null -eq $a.down) {
          [GAI]::Key($vk, $true) | Out-Null
          Start-Sleep -Milliseconds 35
          [GAI]::Key($vk, $false) | Out-Null
        }
        elseif ($a.down -eq $true) { [GAI]::Key($vk, $true) | Out-Null }
        else { [GAI]::Key($vk, $false) | Out-Null }
      }
      else { Write-Warning ("unknown key: " + [string]$a.key) }
    }
    'hold' {
      $vk = [GAI]::Vk([string]$a.key)
      if ($vk -ge 0) {
        [GAI]::Key($vk, $true) | Out-Null
        Start-Sleep -Milliseconds (Get-Ms $a.durationMs 200)
        [GAI]::Key($vk, $false) | Out-Null
      }
    }
    'wheel'      { [GAI]::Wheel([int]$a.delta) | Out-Null }
    'wait'       { Start-Sleep -Milliseconds (Get-Ms $a.durationMs 100) }
    'releaseAll' { [GAI]::ReleaseAll() | Out-Null }
    default      { }
  }
}

Write-Output "ok"
`

let scriptPath: string | null = null

function ensureScript(): string {
  if (scriptPath)
    return scriptPath
  const dir = join(app.getPath('userData'), 'game-agent')
  mkdirSync(dir, { recursive: true })
  scriptPath = join(dir, 'send-input.ps1')
  writeFileSync(scriptPath, PS_SCRIPT, 'utf8')
  return scriptPath
}

/** 执行一组动作；返回脚本 stdout。供 input-safety 包装调用。 */
export function runInputActions(actions: unknown): Promise<string> {
  const script = ensureScript()
  return new Promise<string>((resolve, reject) => {
    execFile(
      'powershell',
      ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, '-ActionJson', JSON.stringify(actions)],
      // 精简环境块：否则脚本内 Add-Type 会因环境块超过 64KB 而失败
      { windowsHide: true, env: minimalPowerShellEnv(), maxBuffer: 1024 * 1024 },
      (err, stdout, stderr) => {
        if (err)
          reject(new Error(`${err.message}${stderr ? ` | ${String(stderr).slice(0, 300)}` : ''}`))
        else
          resolve(stdout)
      },
    )
  })
}

/** 释放所有当前按下的按键（紧急停止用）。 */
export function releaseAllKeys(): Promise<string> {
  return runInputActions([{ type: 'releaseAll' }])
}

// 注意：'game-agent:send-input' 的 IPC handler 统一由 input-safety.ts 注册，
// 以确保所有注入都经过紧急停止与限速检查，渲染进程无法绕过。
