import type { ComputerUseParams, ComputerUseResult } from './schema'

import {
  COMPUTER_USE_TOOL_SCHEMA,

  computerUseParamsSchema,

  SAFE_ACTIONS,
} from './schema'

const log = (...args: unknown[]): void => console.info('[agent-computer-use]', ...args)

/** A computer-control implementation. Swap in a real backend (Hermes cua / AIJADE computer-use-mcp) at runtime. */
export interface ComputerUseBackend {
  execute: (params: ComputerUseParams) => Promise<ComputerUseResult>
}

/**
 * Default safe backend. Mirrors AIJADE's `computer-use-mcp` dry-run executor:
 * it records the requested action instead of touching the OS. Useful for
 * local development, tests, and as the no-op fallback before a real cua-driver
 * backend is wired in.
 */
export function createDryRunBackend(): ComputerUseBackend {
  return {
    async execute(params: ComputerUseParams): Promise<ComputerUseResult> {
      const safe = SAFE_ACTIONS.has(params.action)
      log(`[dry-run] ${params.action}`, params)
      return {
        ok: true,
        safe,
        summary: `[dry-run] ${params.action} executed (no OS effect)`,
      }
    },
  }
}

export { COMPUTER_USE_TOOL_SCHEMA, computerUseParamsSchema, SAFE_ACTIONS }
