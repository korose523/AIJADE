import { z } from 'zod'

/**
 * AIJADE's computer-control contract — a faithful TypeScript port of Hermes
 * Agent's `computer_use` tool schema (`tools/computer_use/schema.py`). The
 * single consolidated tool with an `action` discriminator keeps the per-turn
 * token cost low and works with any tool-calling model. Vision-capable models
 * prefer `capture(mode='som')` then `click(element=N)`.
 */

export const COMPUTER_USE_ACTIONS = [
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

export type ComputerUseAction = typeof COMPUTER_USE_ACTIONS[number]

export const CAPTURE_MODES = ['som', 'vision', 'ax'] as const
export type CaptureMode = typeof CAPTURE_MODES[number]

export const MOUSE_BUTTONS = ['left', 'right', 'middle'] as const
export type MouseButton = typeof MOUSE_BUTTONS[number]

export const MODIFIERS = [
  'cmd',
  'shift',
  'option',
  'alt',
  'ctrl',
  'fn',
  'win',
  'windows',
  'super',
  'meta',
] as const
export type Modifier = typeof MODIFIERS[number]

export const SCROLL_DIRECTIONS = ['up', 'down', 'left', 'right'] as const
export type ScrollDirection = typeof SCROLL_DIRECTIONS[number]

export interface ComputerUseParams {
  action: ComputerUseAction
  /**
   * Runtime-only authorization credential. This is deliberately absent from
   * COMPUTER_USE_TOOL_SCHEMA: the model must never be able to invent it.
   */
  capabilityToken?: string
  mode?: CaptureMode
  app?: string
  max_elements?: number
  element?: number
  coordinate?: [number, number]
  button?: MouseButton
  modifiers?: Modifier[]
  from_element?: number
  to_element?: number
  from_coordinate?: [number, number]
  to_coordinate?: [number, number]
  direction?: ScrollDirection
  amount?: number
  value?: string
  text?: string
  keys?: string
  seconds?: number
  raise_window?: boolean
  capture_after?: boolean
}

export interface ComputerUseResult {
  ok: boolean
  /** True for read-only actions (capture / wait / list_apps) that need no approval. */
  safe: boolean
  summary: string
  data?: unknown
}

/** Read-only actions that never mutate the desktop (Hermes `_SAFE_ACTIONS`). */
export const SAFE_ACTIONS: ReadonlySet<ComputerUseAction> = new Set<ComputerUseAction>([
  'capture',
  'wait',
  'list_apps',
])

export const computerUseParamsSchema = z.object({
  action: z.enum(COMPUTER_USE_ACTIONS),
  mode: z.enum(CAPTURE_MODES).optional(),
  app: z.string().optional(),
  max_elements: z.number().int().min(1).max(1000).optional(),
  element: z.number().int().optional(),
  coordinate: z.tuple([z.number(), z.number()]).optional(),
  button: z.enum(MOUSE_BUTTONS).optional(),
  modifiers: z.array(z.enum(MODIFIERS)).optional(),
  from_element: z.number().int().optional(),
  to_element: z.number().int().optional(),
  from_coordinate: z.tuple([z.number(), z.number()]).optional(),
  to_coordinate: z.tuple([z.number(), z.number()]).optional(),
  direction: z.enum(SCROLL_DIRECTIONS).optional(),
  amount: z.number().int().optional(),
  value: z.string().optional(),
  text: z.string().optional(),
  keys: z.string().optional(),
  seconds: z.number().optional(),
  raise_window: z.boolean().optional(),
  capture_after: z.boolean().optional(),
}).passthrough()

/**
 * The OpenAI function-calling JSON schema for `computer_use`, ready to register
 * with AIJADE's orchestrator or any MCP server. Mirrors Hermes's
 * `COMPUTER_USE_SCHEMA` verbatim.
 */
export const COMPUTER_USE_TOOL_SCHEMA: Record<string, unknown> = {
  name: 'computer_use',
  description:
    'Drive the desktop in the background via cua-driver — screenshots, mouse, '
    + 'keyboard, scroll, drag — without stealing the user\'s cursor or keyboard '
    + 'focus. Supported on macOS, Windows, and Linux. Preferred workflow: call '
    + 'with action=\'capture\' (mode=\'som\' gives numbered element overlays), '
    + 'then click by `element` index for reliability. Pixel coordinates are '
    + 'supported for models trained on them. Requires a cua-driver backend.',
  parameters: {
    type: 'object',
    properties: {
      action: {
        type: 'string',
        enum: [...COMPUTER_USE_ACTIONS],
        description: 'Which action to perform.',
      },
      mode: {
        type: 'string',
        enum: [...CAPTURE_MODES],
        description: 'Capture mode: som (numbered overlays), vision (screenshot), ax (accessibility tree).',
      },
      app: { type: 'string', description: 'Limit capture/action to a specific app by name or bundle id.' },
      max_elements: { type: 'integer', minimum: 1, maximum: 1000, default: 100, description: 'Cap on AX elements returned by capture.' },
      element: { type: 'integer', description: '1-based SOM index from the last capture(mode=\'som\').' },
      coordinate: { type: 'array', items: { type: 'integer' }, minItems: 2, maxItems: 2, description: 'Pixel [x, y] (fallback when no element index).' },
      button: { type: 'string', enum: [...MOUSE_BUTTONS], description: 'Mouse button. Defaults to left.' },
      modifiers: { type: 'array', items: { type: 'string', enum: [...MODIFIERS] }, description: 'Modifier keys held during the action.' },
      from_element: { type: 'integer', description: 'Source element index (drag).' },
      to_element: { type: 'integer', description: 'Target element index (drag).' },
      from_coordinate: { type: 'array', items: { type: 'integer' }, minItems: 2, maxItems: 2, description: 'Source [x,y] (drag).' },
      to_coordinate: { type: 'array', items: { type: 'integer' }, minItems: 2, maxItems: 2, description: 'Target [x,y] (drag).' },
      direction: { type: 'string', enum: [...SCROLL_DIRECTIONS], description: 'Scroll direction.' },
      amount: { type: 'integer', description: 'Scroll wheel ticks. Default 3.' },
      value: { type: 'string', description: 'Value for set_value (option label or slider value).' },
      text: { type: 'string', description: 'Text to type.' },
      keys: { type: 'string', description: 'Key combo, e.g. \'cmd+s\', \'escape\'.' },
      seconds: { type: 'number', description: 'Seconds to wait. Max 30.' },
      raise_window: { type: 'boolean', description: 'focus_app only: raise window (disrupts user). Default false.' },
      capture_after: { type: 'boolean', description: 'Take a follow-up capture after the action to verify its effect.' },
    },
    required: ['action'],
  },
}
