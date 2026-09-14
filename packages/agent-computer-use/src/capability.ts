import type { ComputerUseBackend } from './backend'
import type { ComputerUseParams, ComputerUseResult } from './schema'

import {
  COMPUTER_USE_TOOL_SCHEMA,

  computerUseParamsSchema,

  SAFE_ACTIONS,
} from './schema'

export interface ComputerUseCapability {
  /** OpenAI function-calling schema for agent discovery / registration. */
  readonly toolSchema: Record<string, unknown>
  /** Validate and route a `computer_use` call to the active backend. */
  call: (params: ComputerUseParams) => Promise<ComputerUseResult>
}

export interface ComputerUseCapabilityOptions {
  /**
   * Approval gate for non-safe (state-mutating) actions such as click / type /
   * key / drag. Read-only actions (capture / wait / list_apps) are always
   * allowed. Return `true` to permit the action, `false` to block it. When
   * omitted, every non-safe action is blocked (fail-closed) — the safe default.
   */
  approve?: (params: ComputerUseParams) => boolean | Promise<boolean>
}

/**
 * Wrap a {@link ComputerUseBackend} as an agent-callable capability. The
 * capability owns structural validation; the backend owns the side effects.
 */
export function createComputerUseCapability(
  backend: ComputerUseBackend,
  options: ComputerUseCapabilityOptions = {},
): ComputerUseCapability {
  return {
    toolSchema: COMPUTER_USE_TOOL_SCHEMA,
    async call(params: ComputerUseParams): Promise<ComputerUseResult> {
      const parsed = computerUseParamsSchema.safeParse(params)
      if (!parsed.success) {
        const msg = parsed.error.issues.map(i => `${i.path.join('.') || 'action'}: ${i.message}`).join('; ')
        return { ok: false, safe: false, summary: `invalid computer_use params: ${msg}` }
      }
      const data = parsed.data
      // Fail-closed: state-mutating actions require explicit approval.
      if (!SAFE_ACTIONS.has(data.action)) {
        let allowed = false
        try {
          allowed = options.approve ? await options.approve(data) : false
        }
        catch {
          allowed = false
        }
        if (!allowed) {
          return {
            ok: false,
            safe: false,
            summary: `blocked: non-safe computer_use action "${data.action}" requires approval`,
          }
        }
      }
      return backend.execute(data)
    },
  }
}
