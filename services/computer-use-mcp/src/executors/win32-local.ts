import type {
  ClickActionInput,
  ComputerUseConfig,
  DesktopExecutor,
  DisplayInfo,
  ExecutionTarget,
  ExecutorActionResult,
  FocusAppActionInput,
  ForegroundContext,
  ObserveWindowsRequest,
  OpenAppActionInput,
  PermissionInfo,
  PointerTracePoint,
  PressKeysActionInput,
  ScrollActionInput,
  TypeTextActionInput,
  WaitActionInput,
  WindowInfo,
  WindowObservation,
} from '../types'

import { hostname } from 'node:os'
import { platform } from 'node:process'

import { parsePowerShellJson, runPowerShell } from '../utils/powershell'
import { writeScreenshotArtifact } from '../utils/screenshot'

const WIN32_PAYLOAD_HEADER = `$payloadJson = [Console]::In.ReadToEnd()\n$p = if ($payloadJson) { $payloadJson | ConvertFrom-Json } else { $null }\n`

function createExecutionTarget(config: ComputerUseConfig): ExecutionTarget {
  return {
    mode: 'local-windowed',
    transport: 'local',
    hostName: hostname(),
    sessionTag: config.sessionTag,
    isolated: false,
    tainted: false,
    note: 'local Windows desktop automation via PowerShell + user32/GDI',
  }
}

function result(notes: string[], executionTarget: ExecutionTarget): ExecutorActionResult {
  return {
    performed: true,
    backend: 'win32-local',
    notes,
    executionTarget,
  }
}

function fallbackContext(reason: string): ForegroundContext {
  return {
    available: false,
    platform,
    unavailableReason: reason,
  }
}

function ensureWindows() {
  if (platform !== 'win32') {
    throw new Error(`win32-local executor requires a Windows host, current platform is ${platform}`)
  }
}

const OBSERVE_WINDOWS_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
public class Win32Win {
  public delegate bool EnumWnd(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWnd e, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
  $limit = if ($p -and $p.limit) { [int]$p.limit } else { 12 }
  $appFilter = if ($p -and $p.app) { $p.app.ToString().ToLowerInvariant() } else { '' }
  $list = [System.Collections.Generic.List[object]]::new()
  $sb = New-Object System.Text.StringBuilder 1024
  $enum = [Win32Win+EnumWnd]{
    param($h, $l)
    if (-not [Win32Win]::IsWindowVisible($h)) { return $true }
    $len = [Win32Win]::GetWindowTextLength($h)
    if ($len -le 0) { return $true }
    $sb.Clear() > $null
    [void][Win32Win]::GetWindowText($h, $sb, $len + 1)
    $title = $sb.ToString()
    if ([string]::IsNullOrWhiteSpace($title)) { return $true }
    $wpid = 0
    [void][Win32Win]::GetWindowThreadProcessId($h, [ref]$wpid)
    $appName = 'Unknown'
    try {
      $proc = Get-Process -Id $wpid -ErrorAction SilentlyContinue
      if ($proc -and $proc.MainModule -and $proc.MainModule.FileName) {
        $appName = [System.IO.Path]::GetFileNameWithoutExtension($proc.MainModule.FileName)
      }
    } catch {}
    if ($appFilter -and -not $appName.ToLowerInvariant().Contains($appFilter) -and -not $title.ToLowerInvariant().Contains($appFilter)) { return $true }
    $rect = New-Object Win32Win+RECT
    $bounds = $null
    if ([Win32Win]::GetWindowRect($h, [ref]$rect)) {
      $bounds = @{ x = $rect.Left; y = $rect.Top; width = [Math]::Max(0, $rect.Right - $rect.Left); height = [Math]::Max(0, $rect.Bottom - $rect.Top) }
    }
    $entry = @{ id = "win-$wpid-$title"; appName = $appName; title = $title; ownerPid = [int]$wpid; layer = 0; isOnScreen = $true }
    if ($bounds) { $entry.bounds = $bounds }
    $list.Add($entry)
    if ($list.Count -ge $limit) { return $false }
    return $true
  }
  [void][Win32Win]::EnumWindows($enum, [IntPtr]::Zero)
  $fg = [Win32Win]::GetForegroundWindow()
  $fgTitle = ''
  $fgApp = $null
  if ($fg -ne [IntPtr]::Zero) {
    $sb.Clear() > $null
    [void][Win32Win]::GetWindowText($fg, $sb, 1024)
    $fgTitle = $sb.ToString()
    $fgpid = 0
    [void][Win32Win]::GetWindowThreadProcessId($fg, [ref]$fgpid)
    try {
      $fgProc = Get-Process -Id $fgpid -ErrorAction SilentlyContinue
      if ($fgProc -and $fgProc.MainModule) { $fgApp = [System.IO.Path]::GetFileNameWithoutExtension($fgProc.MainModule.FileName) }
    } catch {}
  }
  $out = @{
    ok = $true
    frontmostAppName = $fgApp
    frontmostWindowTitle = $fgTitle
    windows = $list.ToArray()
    observedAt = [DateTime]::UtcNow.ToString('o')
  }
  $out | ConvertTo-Json -Compress -Depth 4
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const DISPLAY_INFO_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  $screens = [System.Windows.Forms.Screen]::AllScreens
  $displays = @()
  $i = 0
  $minX = 0; $minY = 0; $maxX = 0; $maxY = 0; $first = $true
  foreach ($s in $screens) {
    $b = $s.Bounds
    $sf = $s.ScaleFactor
    $displays += @{
      displayId = $i
      isMain = $s.Primary
      isBuiltIn = $false
      bounds = @{ x = $b.X; y = $b.Y; width = $b.Width; height = $b.Height }
      visibleBounds = @{ x = $b.X; y = $b.Y; width = $b.Width; height = $b.Height }
      scaleFactor = $sf
      pixelWidth = [int]($b.Width * $sf)
      pixelHeight = [int]($b.Height * $sf)
    }
    if ($first) { $minX = $b.X; $minY = $b.Y; $maxX = $b.Right; $maxY = $b.Bottom; $first = $false }
    else {
      if ($b.X -lt $minX) { $minX = $b.X }
      if ($b.Y -lt $minY) { $minY = $b.Y }
      if ($b.Right -gt $maxX) { $maxX = $b.Right }
      if ($b.Bottom -gt $maxY) { $maxY = $b.Bottom }
    }
    $i++
  }
  $out = @{
    ok = $true
    logicalWidth = $screens[0].Bounds.Width
    logicalHeight = $screens[0].Bounds.Height
    scaleFactor = $screens[0].ScaleFactor
    isRetina = ($screens[0].ScaleFactor -gt 1)
    displayCount = $displays.Count
    displays = $displays
    combinedBounds = @{ x = $minX; y = $minY; width = ($maxX - $minX); height = ($maxY - $minY) }
    capturedAt = [DateTime]::UtcNow.ToString('o')
  }
  $out | ConvertTo-Json -Compress -Depth 5
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const SCREENSHOT_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
  $screens = [System.Windows.Forms.Screen]::AllScreens
  $minX = [int]($screens | ForEach-Object { $_.Bounds.X } | Measure-Object -Minimum).Minimum
  $minY = [int]($screens | ForEach-Object { $_.Bounds.Y } | Measure-Object -Minimum).Minimum
  $maxX = [int]($screens | ForEach-Object { $_.Bounds.Right } | Measure-Object -Maximum).Maximum
  $maxY = [int]($screens | ForEach-Object { $_.Bounds.Bottom } | Measure-Object -Maximum).Maximum
  $w = $maxX - $minX
  $h = $maxY - $minY
  if ($w -le 0 -or $h -le 0) { throw ("invalid virtual screen size " + $w + "x" + $h) }
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($minX, $minY, 0, 0, (New-Object System.Drawing.Size($w, $h)))
  $g.Dispose()
  $ms = New-Object System.IO.MemoryStream
  $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  $bytes = $ms.ToArray()
  $ms.Dispose()
  @{ ok = $true; dataBase64 = [Convert]::ToBase64String($bytes); width = $w; height = $h } | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const CLICK_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinMouse {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(int dwFlags, int dx, int dy, int dwData, int dwExtraInfo);
}
"@
  $x = [int]$p.x; $y = [int]$p.y
  [WinMouse]::SetCursorPos($x, $y)
  $btn = ($p.button -as [string]).ToLowerInvariant()
  if ($btn -eq 'right') { $down = 0x0008; $up = 0x0010 }
  elseif ($btn -eq 'middle') { $down = 0x0020; $up = 0x0040 }
  else { $down = 0x0002; $up = 0x0004 }
  $cnt = if ($p.clickCount) { [int]$p.clickCount } else { 1 }
  for ($i = 0; $i -lt $cnt; $i++) {
    [WinMouse]::mouse_event($down, 0, 0, 0, 0)
    [WinMouse]::mouse_event($up, 0, 0, 0, 0)
  }
  @{ ok = $true } | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const TYPE_TEXT_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Windows.Forms
  $text = [string]$p.text
  $special = [char[]]@('+','^','%','~','(',')','[',']','{','}')
  $sb = New-Object System.Text.StringBuilder
  foreach ($ch in $text.ToCharArray()) {
    $c = [string]$ch
    if ($special -contains $c) { [void]$sb.Append('{' + $c + '}') }
    elseif ($c -eq [char]13 -or $c -eq [char]10) { [void]$sb.Append('{ENTER}') }
    else { [void]$sb.Append($c) }
  }
  $out = $sb.ToString()
  if ($p.pressEnter) { $out = $out + '{ENTER}' }
  [System.Windows.Forms.SendKeys]::SendWait($out)
  @{ ok = $true } | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const PRESS_KEYS_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  Add-Type -AssemblyName System.Windows.Forms
  $keys = @($p.keys)
  $prefix = ''
  $main = $null
  foreach ($k in $keys) {
    $k2 = ($k -as [string]).ToLowerInvariant()
    if ($k2 -eq 'ctrl' -or $k2 -eq 'control') { $prefix += '^'; continue }
    if ($k2 -eq 'shift') { $prefix += '+'; continue }
    if ($k2 -eq 'alt') { $prefix += '%'; continue }
    if ($k2 -eq 'win' -or $k2 -eq 'meta' -or $k2 -eq 'cmd' -or $k2 -eq 'super') { $prefix += '#'; continue }
    $main = $k2
  }
  if ($null -eq $main) { throw 'press_keys requires a non-modifier key' }
  $send = $prefix
  switch ($main) {
    'enter' { $send += '{ENTER}' }
    'return' { $send += '{ENTER}' }
    'tab' { $send += '{TAB}' }
    'escape' { $send += '{ESC}' }
    'esc' { $send += '{ESC}' }
    'space' { $send += ' ' }
    'backspace' { $send += '{BACKSPACE}' }
    'delete' { $send += '{DELETE}' }
    'up' { $send += '{UP}' }
    'down' { $send += '{DOWN}' }
    'left' { $send += '{LEFT}' }
    'right' { $send += '{RIGHT}' }
    'home' { $send += '{HOME}' }
    'end' { $send += '{END}' }
    default { $send += $main }
  }
  [System.Windows.Forms.SendKeys]::SendWait($send)
  @{ ok = $true } | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const SCROLL_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class WinWheel {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(int dwFlags, int dx, int dy, int dwData, int dwExtraInfo);
}
"@
  if ($p.x -ne $null -and $p.y -ne $null) { [WinWheel]::SetCursorPos([int]$p.x, [int]$p.y) }
  $dy = if ($p.deltaY) { [int]$p.deltaY } else { 0 }
  $wheel = 0x0800
  [WinWheel]::mouse_event($wheel, 0, 0, $dy, 0)
  @{ ok = $true } | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const OPEN_APP_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  $app = [string]$p.app
  $map = @{
    'visual studio code' = 'code'; 'vscode' = 'code'; 'code' = 'code'
    'google chrome' = 'chrome'; 'chrome' = 'chrome'
    'windows terminal' = 'wt'; 'wt' = 'wt'
    'notepad' = 'notepad'; 'edge' = 'msedge'; 'microsoft edge' = 'msedge'; 'explorer' = 'explorer'
  }
  $key = $app.ToLowerInvariant()
  $cmd = if ($map.ContainsKey($key)) { $map[$key] } else { $app }
  Start-Process $cmd -ErrorAction Stop
  @{ ok = $true; launched = $cmd } | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

const FOCUS_APP_SCRIPT = `
$ErrorActionPreference = 'Stop'
try {
  $app = [string]$p.app
  $sh = New-Object -ComObject Shell.Application
  $ok = $sh.AppActivate($app)
  @{ ok = $true; activated = [bool]$ok } | ConvertTo-Json -Compress
} catch {
  @{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress
}
`

async function runJsonScript(script: string, payload?: unknown): Promise<Record<string, unknown>> {
  const stdout = await runPowerShell(WIN32_PAYLOAD_HEADER + script, payload, { timeoutMs: 30_000 })
  const parsed = parsePowerShellJson(stdout)
  if (!parsed.ok) {
    throw new Error(parsed.error || 'windows powershell action failed')
  }
  return parsed as Record<string, unknown>
}

function observationFromJson(value: Record<string, unknown>): WindowObservation {
  return {
    frontmostAppName: typeof value.frontmostAppName === 'string' ? value.frontmostAppName : undefined,
    frontmostWindowTitle: typeof value.frontmostWindowTitle === 'string' ? value.frontmostWindowTitle : undefined,
    windows: Array.isArray(value.windows)
      ? (value.windows as Record<string, unknown>[]).map((w) => {
          const win: WindowInfo = {
            id: String(w.id ?? ''),
            appName: String(w.appName ?? 'Unknown'),
            title: typeof w.title === 'string' ? w.title : undefined,
            ownerPid: typeof w.ownerPid === 'number' ? w.ownerPid : undefined,
            layer: typeof w.layer === 'number' ? w.layer : undefined,
            isOnScreen: w.isOnScreen === undefined ? true : Boolean(w.isOnScreen),
          }
          if (w.bounds && typeof w.bounds === 'object') {
            const b = w.bounds as Record<string, number>
            win.bounds = { x: b.x ?? 0, y: b.y ?? 0, width: b.width ?? 0, height: b.height ?? 0 }
          }
          return win
        })
      : [],
    observedAt: typeof value.observedAt === 'string' ? value.observedAt : new Date().toISOString(),
  }
}

function displayInfoFromJson(value: Record<string, unknown>): DisplayInfo {
  const displays = Array.isArray(value.displays)
    ? (value.displays as Record<string, unknown>[]).map((d, index) => {
        const bounds = (d.bounds ?? {}) as Record<string, number>
        const visibleBounds = (d.visibleBounds ?? bounds) as Record<string, number>
        return {
          displayId: typeof d.displayId === 'number' ? d.displayId : index,
          isMain: Boolean(d.isMain),
          isBuiltIn: Boolean(d.isBuiltIn),
          bounds: { x: bounds.x ?? 0, y: bounds.y ?? 0, width: bounds.width ?? 0, height: bounds.height ?? 0 },
          visibleBounds: { x: visibleBounds.x ?? 0, y: visibleBounds.y ?? 0, width: visibleBounds.width ?? 0, height: visibleBounds.height ?? 0 },
          scaleFactor: typeof d.scaleFactor === 'number' ? d.scaleFactor : 1,
          pixelWidth: typeof d.pixelWidth === 'number' ? d.pixelWidth : (bounds.width ?? 0),
          pixelHeight: typeof d.pixelHeight === 'number' ? d.pixelHeight : (bounds.height ?? 0),
        }
      })
    : []

  const combined = (value.combinedBounds ?? {}) as Record<string, number>

  return {
    available: true,
    platform: 'win32',
    logicalWidth: typeof value.logicalWidth === 'number' ? value.logicalWidth : undefined,
    logicalHeight: typeof value.logicalHeight === 'number' ? value.logicalHeight : undefined,
    scaleFactor: typeof value.scaleFactor === 'number' ? value.scaleFactor : undefined,
    isRetina: Boolean(value.isRetina),
    displayCount: displays.length,
    displays,
    combinedBounds: {
      x: combined.x ?? 0,
      y: combined.y ?? 0,
      width: combined.width ?? 0,
      height: combined.height ?? 0,
    },
    capturedAt: typeof value.capturedAt === 'string' ? value.capturedAt : new Date().toISOString(),
  }
}

export function createWin32LocalExecutor(config: ComputerUseConfig): DesktopExecutor {
  const executionTarget = createExecutionTarget(config)

  return {
    kind: 'win32-local',
    describe: () => ({
      kind: 'win32-local',
      notes: [
        'desktop actions run on the current Windows host',
        'window observation uses EnumWindows + GetWindowRect',
        'input injection uses user32 SetCursorPos/mouse_event and System.Windows.Forms.SendKeys',
        'screenshots use GDI Graphics.CopyFromScreen across the virtual screen',
      ],
    }),
    getExecutionTarget: async () => executionTarget,
    getForegroundContext: async () => {
      try {
        ensureWindows()
        const observation = observationFromJson(await runJsonScript(OBSERVE_WINDOWS_SCRIPT, { limit: 8 }))
        const frontmost = observation.windows.find(window => window.appName === observation.frontmostAppName)
        return {
          available: Boolean(observation.frontmostAppName),
          appName: observation.frontmostAppName,
          windowTitle: observation.frontmostWindowTitle,
          windowBounds: frontmost?.bounds,
          platform,
          unavailableReason: observation.frontmostAppName ? undefined : 'foreground window unavailable',
        }
      }
      catch (error) {
        return fallbackContext(error instanceof Error ? error.message : String(error))
      }
    },
    getDisplayInfo: async () => {
      try {
        ensureWindows()
        return displayInfoFromJson(await runJsonScript(DISPLAY_INFO_SCRIPT))
      }
      catch (error) {
        return {
          available: false,
          platform,
          note: error instanceof Error ? error.message : String(error),
        }
      }
    },
    getPermissionInfo: async (): Promise<PermissionInfo> => ({
      screenRecording: {
        status: 'unsupported',
        target: 'powershell.exe',
        note: 'Windows captures the interactive desktop via GDI CopyFromScreen without a TCC-style prompt',
      },
      accessibility: {
        status: 'unsupported',
        target: 'user32',
        note: 'Windows input injection uses user32 SendInput/mouse_event without an AXTrusted prompt',
      },
      automationToSystemEvents: {
        status: 'unsupported',
        target: 'Shell.Application',
        note: 'Windows app activation uses Shell.Application AppActivate',
      },
    }),
    observeWindows: async (request: ObserveWindowsRequest) => {
      ensureWindows()
      return observationFromJson(await runJsonScript(OBSERVE_WINDOWS_SCRIPT, request))
    },
    takeScreenshot: async (request) => {
      ensureWindows()
      const shot = await runJsonScript(SCREENSHOT_SCRIPT)
      const dataBase64 = typeof shot.dataBase64 === 'string' ? shot.dataBase64 : ''
      return await writeScreenshotArtifact({
        label: request.label,
        screenshotsDir: config.screenshotsDir,
        dataBase64,
        executionTarget,
      })
    },
    openApp: async (input: OpenAppActionInput) => {
      ensureWindows()
      const res = await runJsonScript(OPEN_APP_SCRIPT, { app: input.app })
      return result([`opened app ${input.app}${res.launched ? ` (launched ${res.launched})` : ''}`], executionTarget)
    },
    focusApp: async (input: FocusAppActionInput) => {
      ensureWindows()
      await runJsonScript(FOCUS_APP_SCRIPT, { app: input.app })
      return result([`focused app ${input.app}`], executionTarget)
    },
    click: async (input: ClickActionInput & { pointerTrace: PointerTracePoint[] }) => {
      ensureWindows()
      await runJsonScript(CLICK_SCRIPT, {
        x: input.x,
        y: input.y,
        button: input.button ?? 'left',
        clickCount: input.clickCount ?? 1,
      })
      return {
        ...result(['clicked on local Windows desktop'], executionTarget),
        pointerTrace: input.pointerTrace,
      }
    },
    typeText: async (input: TypeTextActionInput) => {
      ensureWindows()
      await runJsonScript(TYPE_TEXT_SCRIPT, { text: input.text, pressEnter: input.pressEnter ?? false })
      return result(['typed text on local Windows desktop'], executionTarget)
    },
    pressKeys: async (input: PressKeysActionInput) => {
      ensureWindows()
      await runJsonScript(PRESS_KEYS_SCRIPT, { keys: input.keys })
      return result([`pressed keys ${input.keys.join('+')}`], executionTarget)
    },
    scroll: async (input: ScrollActionInput) => {
      ensureWindows()
      await runJsonScript(SCROLL_SCRIPT, {
        x: input.x,
        y: input.y,
        deltaX: input.deltaX ?? 0,
        deltaY: input.deltaY,
      })
      return result(['scrolled on local Windows desktop'], executionTarget)
    },
    wait: async (input: WaitActionInput) => {
      await new Promise(resolve => setTimeout(resolve, Math.max(input.durationMs, 0)))
      return result(['waited on local Windows desktop'], executionTarget)
    },
  }
}
