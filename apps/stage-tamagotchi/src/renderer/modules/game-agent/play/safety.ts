import type { AgentAction, AgentActionType, GameProfile } from '../types'

/**
 * 实操安全层（渲染端）—— 主进程安全网的对侧。
 *
 * 主进程 input-safety.ts 是「最后一道闸」：panic 检查、令牌桶、单飞。
 * 但只有闸门是不够的——被闸门拒掉的动作对用户是静默失败，而且模型有可能
 * 产出档案根本不允许的动作（比如在只读档案里点鼠标右键）。所以渲染端再做一层：
 *
 *  1. 白名单过滤：只放行 profile.allowedActions 里声明的动作类型；
 *  2. 参数夹取：按住时长/等待时长/滚轮量都限制在合理区间，防止"按住 W 十分钟"；
 *  3. 批次上限：一次决策最多注入 N 个动作，配合主进程令牌桶避免被限速拒批；
 *  4. 人性化抖动：给坐标和时长加微小随机偏移，避免机器般整齐的输入节奏；
 *  5. panic 感知：轮询主进程状态，紧急停止时立即让上层循环停下来。
 */
import { computed, onScopeDispose, ref, shallowRef } from 'vue'

/** 主进程 publicStatus() 的完整形状（比共享类型多了运行时字段） */
export interface SafetyStatus {
  panic: boolean
  panicHotkey: string
  hotkeyRegistered: boolean
  injectedActions: number
  lastInjectedAt: number
  maxActionsPerSecond: number
  busy: boolean
  lastError?: string
}

export interface SendInputResult {
  ok: boolean
  reason?: 'empty' | 'panic' | 'busy' | 'rate-limited' | 'error'
  error?: string
  status: SafetyStatus
}

export interface SanitizeOptions {
  /** 单批最多注入多少动作 */
  maxBatch?: number
  /** hold / wait 的时长上限（毫秒） */
  maxDurationMs?: number
  /** 人性化抖动强度，0 = 关闭 */
  jitter?: number
  /** 画面尺寸，用于夹取绝对坐标 */
  screen?: { width: number, height: number }
}

const DEFAULTS: Required<Omit<SanitizeOptions, 'screen'>> = {
  maxBatch: 8,
  maxDurationMs: 3000,
  jitter: 1,
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v))
}

/** 围绕 base 的对称抖动，amount 为最大偏移量 */
function jitterAround(base: number, amount: number): number {
  if (amount <= 0)
    return base
  return base + (Math.random() * 2 - 1) * amount
}

export interface SanitizeReport {
  actions: AgentAction[]
  /** 被丢弃的动作及原因，用于在面板上给用户解释"为什么没动" */
  dropped: { action: AgentAction, reason: string }[]
}

/**
 * 清洗一批动作：白名单 + 夹取 + 抖动 + 截断。
 * 返回值一定是可以安全交给主进程的动作数组。
 */
export function sanitizeActions(
  actions: AgentAction[],
  profile: GameProfile,
  options: SanitizeOptions = {},
): SanitizeReport {
  const opts = { ...DEFAULTS, ...options }
  const allowed = new Set<AgentActionType>(profile.allowedActions)
  const out: AgentAction[] = []
  const dropped: SanitizeReport['dropped'] = []

  for (const raw of actions) {
    if (out.length >= opts.maxBatch) {
      dropped.push({ action: raw, reason: `超出单批上限 ${opts.maxBatch}` })
      continue
    }
    if (!raw || typeof raw.type !== 'string') {
      dropped.push({ action: raw, reason: '动作格式非法' })
      continue
    }
    if (raw.type === 'noop')
      continue
    if (!allowed.has(raw.type)) {
      dropped.push({ action: raw, reason: `档案未允许的动作类型：${raw.type}` })
      continue
    }

    const a: AgentAction = { ...raw }

    switch (a.type) {
      case 'move': {
        if (typeof a.x !== 'number' || typeof a.y !== 'number') {
          dropped.push({ action: raw, reason: 'move 缺少坐标' })
          continue
        }
        const w = options.screen?.width ?? 3840
        const h = options.screen?.height ?? 2160
        a.x = Math.round(clamp(jitterAround(a.x, opts.jitter * 2), 0, w))
        a.y = Math.round(clamp(jitterAround(a.y, opts.jitter * 2), 0, h))
        break
      }
      case 'moveRelative': {
        if (typeof a.x !== 'number' || typeof a.y !== 'number') {
          dropped.push({ action: raw, reason: 'moveRelative 缺少位移' })
          continue
        }
        a.x = Math.round(clamp(jitterAround(a.x, opts.jitter), -2000, 2000))
        a.y = Math.round(clamp(jitterAround(a.y, opts.jitter), -2000, 2000))
        break
      }
      case 'click': {
        a.button = a.button === 'right' || a.button === 'middle' ? a.button : 'left'
        break
      }
      case 'key': {
        if (!a.key) {
          dropped.push({ action: raw, reason: 'key 缺少键名' })
          continue
        }
        a.key = String(a.key).trim()
        break
      }
      case 'hold': {
        if (!a.key) {
          dropped.push({ action: raw, reason: 'hold 缺少键名' })
          continue
        }
        a.key = String(a.key).trim()
        a.durationMs = Math.round(clamp(jitterAround(a.durationMs ?? 200, opts.jitter * 12), 20, opts.maxDurationMs))
        break
      }
      case 'wheel': {
        a.delta = Math.round(clamp(a.delta ?? 0, -1200, 1200))
        if (a.delta === 0) {
          dropped.push({ action: raw, reason: 'wheel delta 为 0' })
          continue
        }
        break
      }
      case 'wait': {
        a.durationMs = Math.round(clamp(jitterAround(a.durationMs ?? 100, opts.jitter * 8), 10, opts.maxDurationMs))
        break
      }
    }

    out.push(a)
  }

  return { actions: out, dropped }
}

function ipc() {
  return window.electron.ipcRenderer
}

/**
 * 安全网状态 composable：轮询 panic / 限速 / 注入计数，并提供手动控制。
 * 上层循环每一 tick 前应检查 `panic.value`。
 */
export function useInputSafety(pollMs = 1200) {
  const status = shallowRef<SafetyStatus | null>(null)
  const error = ref('')
  let timer: ReturnType<typeof setInterval> | null = null

  const panic = computed(() => status.value?.panic ?? false)
  const hotkey = computed(() => status.value?.panicHotkey ?? 'F9')
  const hotkeyRegistered = computed(() => status.value?.hotkeyRegistered ?? false)
  const injectedActions = computed(() => status.value?.injectedActions ?? 0)
  const maxActionsPerSecond = computed(() => status.value?.maxActionsPerSecond ?? 20)

  async function refresh() {
    try {
      status.value = await ipc().invoke('game-agent:safety:status') as SafetyStatus
      error.value = ''
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function panicNow() {
    status.value = await ipc().invoke('game-agent:safety:panic') as SafetyStatus
  }

  async function resume() {
    status.value = await ipc().invoke('game-agent:safety:resume') as SafetyStatus
  }

  async function configure(opts: { maxActionsPerSecond?: number, panicHotkey?: string }) {
    status.value = await ipc().invoke('game-agent:safety:configure', opts) as SafetyStatus
  }

  function startPolling() {
    if (timer)
      return
    void refresh()
    timer = setInterval(() => void refresh(), pollMs)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onScopeDispose(stopPolling)

  return {
    status,
    error,
    panic,
    hotkey,
    hotkeyRegistered,
    injectedActions,
    maxActionsPerSecond,
    refresh,
    panicNow,
    resume,
    configure,
    startPolling,
    stopPolling,
  }
}

/**
 * 经安全网注入的输入后端。
 * 与旧的 IpcInputBackend 走同一 IPC 通道，但会解析主进程返回的拒绝原因，
 * 通过 onResult 回调告诉上层（避免"点了没反应还不知道为什么"）。
 */
export class SafeIpcInputBackend {
  id = 'ipc'
  name = '真实注入（安全网受控）'
  readonly safe = false

  constructor(private readonly onResult?: (result: SendInputResult) => void) {}

  async execute(actions: AgentAction[]): Promise<void> {
    if (!actions.length)
      return
    const payload = JSON.parse(JSON.stringify(actions))
    const result = await ipc().invoke('game-agent:send-input', payload) as SendInputResult
    this.onResult?.(result)
  }
}

/** 把主进程拒绝原因翻译成人话 */
export function describeRejection(result: SendInputResult): string {
  switch (result.reason) {
    case 'panic':
      return '紧急停止生效中，注入已被拦截'
    case 'busy':
      return '上一批动作仍在执行，本批已跳过'
    case 'rate-limited':
      return '触发限速保护，本批已跳过'
    case 'error':
      return `注入失败：${result.error ?? '未知错误'}`
    case 'empty':
      return '动作为空'
    default:
      return ''
  }
}
