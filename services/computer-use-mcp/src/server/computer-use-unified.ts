/**
 * Unified `computer_use` tool — the single contract the LLM faces.
 *
 * `@proj-aijade/agent-computer-use` exposes one consolidated `computer_use` tool
 * (see `COMPUTER_USE_TOOL_SCHEMA`) and its Hermes-fusion transport
 * (`createComputerUseMcpTransport`) calls `${serverName}::computer_use` — i.e.
 * it expects this server to register a tool literally named `computer_use`.
 *
 * Until this module existed the server only exposed granular `desktop_*` tools,
 * so the unified LLM contract resolved to nothing and real control was only
 * reachable through the granular tools directly. This module closes that gap:
 * it maps the Hermes-style `action` discriminator onto the server's internal
 * `ActionInvocation` kinds and dispatches through the same `executeAction`
 * engine the granular tools use, so the LLM path reaches the real executor
 * (e.g. `win32-local` on Windows).
 */
import type {
  ActionInvocation,
  ClickActionInput,
  FocusAppActionInput,
  ObserveWindowsRequest,
  PressKeysActionInput,
  ScreenshotRequest,
  TypeTextActionInput,
  WaitActionInput,
} from '../types'

import { z } from 'zod'

/** Mirrors `@proj-aijade/agent-computer-use` `COMPUTER_USE_ACTIONS`. */
export const COMPUTER_USE_UNIFIED_ACTIONS = [
  'capture',
  'click',
  'double_click',
  'right_click',
  'middle_click',
  'drag',
  'scroll',
  'type',
  'key',
  'set_value',
  'wait',
  'list_apps',
  'focus_app',
] as const

export type ComputerUseUnifiedAction = typeof COMPUTER_USE_UNIFIED_ACTIONS[number]

/** Raw zod shape passed to `server.tool('computer_use', …)`. */
export const unifiedComputerUseParamsSchema = {
  action: z.enum(COMPUTER_USE_UNIFIED_ACTIONS),
  mode: z.enum(['som', 'vision', 'ax']).optional(),
  app: z.string().optional(),
  max_elements: z.number().int().min(1).max(1000).optional(),
  element: z.number().int().optional(),
  coordinate: z.tuple([z.number(), z.number()]).optional(),
  button: z.enum(['left', 'right', 'middle']).optional(),
  modifiers: z
    .array(z.enum(['cmd', 'shift', 'option', 'alt', 'ctrl', 'fn', 'win', 'windows', 'super', 'meta']))
    .optional(),
  from_element: z.number().int().optional(),
  to_element: z.number().int().optional(),
  from_coordinate: z.tuple([z.number(), z.number()]).optional(),
  to_coordinate: z.tuple([z.number(), z.number()]).optional(),
  direction: z.enum(['up', 'down', 'left', 'right']).optional(),
  amount: z.number().int().optional(),
  value: z.string().optional(),
  text: z.string().optional(),
  keys: z.string().optional(),
  seconds: z.number().optional(),
  raise_window: z.boolean().optional(),
  capture_after: z.boolean().optional(),
}

export type UnifiedComputerUseParams = Record<string, unknown>

export type MappedAction = ActionInvocation | { unsupported: true, reason: string }

/** Windows wheel delta per "tick" sent by the unified contract. */
const WHEEL_DELTA = 120

function unsupported(action: string, reason: string): { unsupported: true, reason: string } {
  return { unsupported: true, reason: `${reason} (action="${action}")` }
}

/**
 * Split a Hermes-style key combo (`"cmd+s"`, `"ctrl+l"`) into the raw tokens
 * the `win32-local` / `press_keys` handler already understands. The executor
 * lowercases and maps modifiers (`ctrl`/`shift`/`alt`/`win`/`cmd`/…) to the
 * SendKeys prefix form, so we only need to split on `+` here.
 */
function parseKeyCombo(combo: string): string[] {
  return combo
    .split('+')
    .map(token => token.trim().toLowerCase())
    .filter(Boolean)
}

/**
 * Map a unified `computer_use` action + params onto an internal
 * `ActionInvocation` that `executeAction` can drive. Returns an
 * `{ unsupported }` marker for actions the executor cannot perform.
 */
export function mapComputerUseAction(params: UnifiedComputerUseParams): MappedAction {
  const action = params.action as ComputerUseUnifiedAction
  const captureAfter = typeof params.capture_after === 'boolean' ? params.capture_after : undefined
  const coordinate = params.coordinate as [number, number] | undefined

  switch (action) {
    case 'capture': {
      // `mode` (som/vision/ax) is a capture hint the granular executor does not
      // distinguish; a plain global screenshot is returned regardless. The
      // `executeAction` engine captures a follow-up screenshot after a
      // `screenshot` action on its own, so `captureAfter` is not forwarded here.
      const input: ScreenshotRequest = {}
      return { kind: 'screenshot', input }
    }

    case 'click':
    case 'double_click':
    case 'right_click':
    case 'middle_click': {
      if (!coordinate)
        return unsupported(action, 'coordinate [x, y] is required')
      const input: ClickActionInput = { x: coordinate[0], y: coordinate[1] }
      if (action === 'double_click')
        input.clickCount = 2
      else if (action === 'right_click')
        input.button = 'right'
      else if (action === 'middle_click')
        input.button = 'middle'
      else if (typeof params.button === 'string')
        input.button = params.button as ClickActionInput['button']
      if (captureAfter !== undefined)
        input.captureAfter = captureAfter
      return { kind: 'click', input }
    }

    case 'scroll': {
      const direction = params.direction as string | undefined
      const amount = typeof params.amount === 'number' ? params.amount : 3
      const delta = amount * WHEEL_DELTA
      const input: { x?: number, y?: number, deltaX?: number, deltaY: number, captureAfter?: boolean } = { deltaY: 0 }
      switch (direction) {
        case 'up':
          input.deltaY = -delta
          break
        case 'down':
          input.deltaY = delta
          break
        case 'left':
          input.deltaX = -delta
          break
        case 'right':
          input.deltaX = delta
          break
        default:
          input.deltaY = delta
      }
      if (coordinate) {
        input.x = coordinate[0]
        input.y = coordinate[1]
      }
      if (captureAfter !== undefined)
        input.captureAfter = captureAfter
      return { kind: 'scroll', input }
    }

    case 'type': {
      const text = params.text as string | undefined
      if (!text)
        return unsupported(action, 'text is required')
      const input: TypeTextActionInput = { text }
      if (coordinate) {
        input.x = coordinate[0]
        input.y = coordinate[1]
      }
      if (captureAfter !== undefined)
        input.captureAfter = captureAfter
      return { kind: 'type_text', input }
    }

    case 'key': {
      const keys = params.keys as string | undefined
      if (!keys)
        return unsupported(action, 'keys is required')
      const input: PressKeysActionInput = { keys: parseKeyCombo(keys) }
      if (captureAfter !== undefined)
        input.captureAfter = captureAfter
      return { kind: 'press_keys', input }
    }

    case 'set_value': {
      // No direct "set value" primitive on the executor; best-effort is to
      // focus (optional coordinate) and type the value without pressing Enter.
      const value = params.value as string | undefined
      if (!value)
        return unsupported(action, 'value is required')
      const input: TypeTextActionInput = { text: value, pressEnter: false }
      if (coordinate) {
        input.x = coordinate[0]
        input.y = coordinate[1]
      }
      return { kind: 'type_text', input }
    }

    case 'wait': {
      const seconds = typeof params.seconds === 'number' ? params.seconds : 0
      const input: WaitActionInput = { durationMs: Math.round(seconds * 1000) }
      if (captureAfter !== undefined)
        input.captureAfter = captureAfter
      return { kind: 'wait', input }
    }

    case 'list_apps': {
      const input: ObserveWindowsRequest = {}
      if (typeof params.max_elements === 'number')
        input.limit = params.max_elements
      if (typeof params.app === 'string')
        input.app = params.app
      return { kind: 'observe_windows', input }
    }

    case 'focus_app': {
      const app = params.app as string | undefined
      if (!app)
        return unsupported(action, 'app is required')
      const input: FocusAppActionInput = { app }
      return { kind: 'focus_app', input }
    }

    case 'drag':
      return unsupported(action, 'drag is not supported by this executor; use click with explicit coordinates instead')

    default:
      return unsupported(String(action), 'unknown action')
  }
}
