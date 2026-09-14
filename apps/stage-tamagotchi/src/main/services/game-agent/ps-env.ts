/**
 * 为 PowerShell 子进程构造「精简环境变量块」。
 *
 * 背景：Windows 的 CreateProcess 环境块上限约 64KB。Electron 进程（尤其被 IDE /
 * 终端 / 各类工具链启动时）常常继承几百 KB 的环境变量，此时 PowerShell 里的
 * Add-Type 需要再拉起 csc.exe 编译器子进程，会直接失败并报：
 *   「用于启动进程的环境块不能多于 65535 个字节」
 *
 * 因此所有需要 Add-Type（P/Invoke user32）的脚本，spawn 时都应传本函数返回的
 * 精简环境，只保留 PowerShell 与 csc 必需的变量。
 */

const KEEP_KEYS = [
  'SystemRoot',
  'windir',
  'SystemDrive',
  'COMSPEC',
  'PATHEXT',
  'TEMP',
  'TMP',
  'USERPROFILE',
  'USERNAME',
  'HOMEDRIVE',
  'HOMEPATH',
  'APPDATA',
  'LOCALAPPDATA',
  'ProgramData',
  'ProgramFiles',
  'ProgramFiles(x86)',
  'CommonProgramFiles',
  'NUMBER_OF_PROCESSORS',
  'PROCESSOR_ARCHITECTURE',
  'OS',
]

/** PATH 里只保留系统目录，避免把巨大的开发者 PATH 也带进去。 */
function minimalPath(): string {
  const root = process.env.SystemRoot ?? process.env.windir ?? 'C:\\Windows'
  return [
    `${root}\\system32`,
    root,
    `${root}\\System32\\Wbem`,
    `${root}\\System32\\WindowsPowerShell\\v1.0`,
    `${root}\\Microsoft.NET\\Framework64\\v4.0.30319`,
  ].join(';')
}

export function minimalPowerShellEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {}
  for (const key of KEEP_KEYS) {
    const value = process.env[key]
    if (typeof value === 'string' && value.length < 4096)
      env[key] = value
  }
  env.PATH = minimalPath()
  env.Path = env.PATH
  // 显式清掉可能干扰 Electron/Node 子进程语义的变量
  delete env.NODE_OPTIONS
  delete env.ELECTRON_RUN_AS_NODE
  return env
}
