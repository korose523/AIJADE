import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { runProcess } from './process'

export interface RunPowerShellOptions {
  timeoutMs?: number
  cwd?: string
}

/**
 * Builds a curated environment for the PowerShell child.
 *
 * Windows rejects a process whose environment block exceeds 65535 bytes.
 * Some hosts (CI agents, remote desktops) carry an enormous inherited
 * environment, so we forward only the variables PowerShell and the
 * computer-use tooling actually need instead of the full `process.env`.
 */
function buildMinimalEnv(): NodeJS.ProcessEnv {
  const allowed = new Set([
    'PATH',
    'Path',
    'SystemRoot',
    'SystemDrive',
    'windir',
    'TEMP',
    'TMP',
    'USERPROFILE',
    'USERNAME',
    'HOMEDRIVE',
    'HOMEPATH',
    'HOME',
    'COMSPEC',
    'PATHEXT',
    'OS',
    'TERM',
    'LANG',
    'LC_ALL',
    'NUMBER_OF_PROCESSORS',
    'PROCESSOR_ARCHITECTURE',
    'PROCESSOR_IDENTIFIER',
    'PROCESSOR_LEVEL',
    'PROCESSOR_REVISION',
    'POWERSHELL_TELEMETRY_OPTOUT',
    'DOTNET_CLI_TELEMETRY_OPTOUT',
    'POWERSHELL_DISTRIBUTION_CHANNEL',
  ])
  const env: NodeJS.ProcessEnv = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined)
      continue
    if (allowed.has(key) || key.startsWith('COMPUTER_USE_')) {
      env[key] = value
    }
  }
  return env
}

/**
 * Runs a PowerShell 7/5 script on the local Windows host.
 *
 * The script receives an optional JSON payload on stdin; read it with
 * `[Console]::In.ReadToEnd() | ConvertFrom-Json`. Scripts SHOULD wrap their
 * body in try/catch and always emit a single JSON object (including `error`
 * on failure) so callers can distinguish business failures from process
 * crashes. Each script MUST end with `Exit 0` (runProcess rejects on a
 * non-zero exit and discards stdout).
 */
export async function runPowerShell(script: string, payload?: unknown, options: RunPowerShellOptions = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'airi-ps-'))
  const file = join(dir, 'script.ps1')
  await writeFile(file, `${script}\nExit 0\n`, 'utf-8')
  try {
    const { stdout } = await runProcess(
      'powershell.exe',
      ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', file],
      {
        stdin: payload === undefined ? undefined : JSON.stringify(payload),
        timeoutMs: options.timeoutMs,
        cwd: options.cwd,
        env: buildMinimalEnv(),
      },
    )
    return stdout
  }
  finally {
    await rm(dir, { recursive: true, force: true })
  }
}

export interface PowerShellJsonResult {
  ok: boolean
  error?: string
  [key: string]: unknown
}

/** Parses the JSON object emitted by a runPowerShell script. */
export function parsePowerShellJson(stdout: string): PowerShellJsonResult {
  const trimmed = stdout.trim()
  if (!trimmed) {
    throw new Error('powershell returned empty output')
  }
  try {
    return JSON.parse(trimmed) as PowerShellJsonResult
  }
  catch {
    throw new Error(`powershell returned non-JSON output: ${trimmed.slice(0, 200)}`)
  }
}
