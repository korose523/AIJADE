import type { AgentAction, GameFrame, GameState, InputBackend, Planner, VisionBackend } from './types'

/**
 * useGameAgent —— 游戏 Agent 编排器（感知 → 检索经验 → 决策 → 安全清洗 → 行动）。
 *
 * 默认 demoMode=true：不依赖 OBS/模型，用合成画面跑通整条链路做演示。
 * 关闭 demoMode 后连接真实 OBS 源；视觉/决策后端可在 Mock 与 Ollama 间切换。
 * mode='copilot'（默认）只分析不注入；mode='autonomous' 才经主进程真实按键。
 *
 * 相比最初版本，这里多了两条支线：
 *  - 决策前从经验库检索相关知识注入提示词（学习成果 → 实操）；
 *  - 注入前经渲染端安全层清洗，并感知主进程 panic 状态（F9 一键夺回控制权）。
 */
import { computed, onUnmounted, ref, shallowRef } from 'vue'

import { DryRunInputBackend } from './input'
import { useKnowledgeBase } from './learning/knowledge-base'
import { ObsCapture } from './obs'
import { MockPlanner, OllamaPlanner } from './planner'
import { describeRejection, SafeIpcInputBackend, sanitizeActions, useInputSafety } from './play/safety'
import { torchlightProfile } from './profiles/torchlight'
import { MockVisionBackend, OllamaVisionBackend } from './vision'

function makeDemoFrame(): GameFrame {
  const canvas = document.createElement('canvas')
  canvas.width = 640
  canvas.height = 360
  const ctx = canvas.getContext('2d')
  if (ctx) {
    ctx.fillStyle = '#16203a'
    ctx.fillRect(0, 0, 640, 360)
    ctx.fillStyle = '#e0c060'
    ctx.font = '20px sans-serif'
    ctx.fillText('TORCHLIGHT INFINITE (demo frame)', 20, 40)
    ctx.fillStyle = '#c0392b'
    ctx.beginPath()
    ctx.arc(220, 200, 16, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = '#27ae60'
    ctx.fillText('HP 80%  EN 60%', 20, 340)
  }
  return {
    dataUrl: canvas.toDataURL('image/png'),
    width: 640,
    height: 360,
    timestamp: Date.now(),
  }
}

export function useGameAgent() {
  const profile = torchlightProfile

  // —— OBS 连接配置 ——
  const obsUrl = ref('ws://localhost:4455')
  const obsPassword = ref('')
  const obsSource = ref(profile.defaultObsSource ?? '火炬之光无限')
  const demoMode = ref(true)

  // —— 模型后端配置 ——
  const ollamaBaseUrl = ref('http://localhost:11434')
  const visionModel = ref('qwen2.5-vl')
  const plannerModel = ref('qwen3.6-35b-a3b')
  const visionBackendId = ref('mock-vision')
  const plannerBackendId = ref('mock-planner')

  // —— 输入与节奏 ——
  const inputBackendId = ref('dry-run')
  // 运行模式（参考 super-agent-party 的模式系统）：
  // copilot=只分析；read=每步列出动作、需用户确认才注入；autonomous=直接注入；goal=自主+目标驱动。
  const mode = ref<string>('copilot')
  const goal = ref('')
  const loopIntervalMs = ref(1500)

  // —— 经验注入配置 ——
  const useKnowledge = ref(true)
  const knowledgeTopK = ref(5)

  // —— 安全层配置 ——
  const maxBatch = ref(6)
  const jitter = ref(1)

  // —— 运行时状态 ——
  const running = ref(false)
  const obsStatus = ref<string>('disconnected')
  const lastFrame = shallowRef<GameFrame | null>(null)
  const lastState = shallowRef<GameState | null>(null)
  const lastActions = ref<AgentAction[]>([])
  const lastSay = ref('')
  const lastKnowledge = ref('')
  const lastDropped = ref<string[]>([])
  const logs = ref<string[]>([])
  /** 最近一次「开始」失败的原因，供面板在醒目位置展示（避免只藏在底部日志） */
  const error = ref('')

  const knowledge = useKnowledgeBase(profile.id)
  const safety = useInputSafety()

  let obs: ObsCapture | null = null
  let timer: ReturnType<typeof setTimeout> | null = null
  let tickCount = 0
  const history: GameState[] = []

  /** 面板上「AI 是否真的在按键」的综合判断 */
  const injecting = computed(() =>
    running.value
    && inputBackendId.value === 'ipc'
    && (mode.value === 'autonomous' || mode.value === 'goal')
    && !safety.panic.value,
  )

  function pushLog(msg: string) {
    logs.value.push(`[${new Date().toLocaleTimeString()}] ${msg}`)
    if (logs.value.length > 200)
      logs.value.shift()
  }

  function pickVision(): VisionBackend {
    if (visionBackendId.value === 'ollama-vision') {
      return new OllamaVisionBackend({ baseUrl: ollamaBaseUrl.value, model: visionModel.value })
    }
    return new MockVisionBackend()
  }

  function pickPlanner(): Planner {
    if (plannerBackendId.value === 'ollama-planner') {
      return new OllamaPlanner({ baseUrl: ollamaBaseUrl.value, model: plannerModel.value })
    }
    return new MockPlanner()
  }

  function onInjectResult(result: { ok: boolean, reason?: string }) {
    if (!result.ok) {
      const msg = describeRejection(result as Parameters<typeof describeRejection>[0])
      if (msg)
        pushLog(`⚠ ${msg}`)
    }
  }

  function pickInput(): InputBackend {
    if (inputBackendId.value === 'ipc' && (mode.value === 'autonomous' || mode.value === 'goal'))
      return new SafeIpcInputBackend(onInjectResult)
    return new DryRunInputBackend()
  }

  /** 决策前检索经验，渲染为提示词片段 */
  function buildKnowledgeBlock(state: GameState): string {
    if (!useKnowledge.value || !knowledge.items.value.length)
      return ''
    let stateText = state.raw
    try {
      stateText = `${state.raw}\n${JSON.stringify(state.structured)}`
    }
    catch {
      // structured 可能含循环引用，忽略即可
    }
    return knowledge.toPromptBlock(stateText, goal.value, knowledgeTopK.value)
  }

  async function tick() {
    if (!running.value)
      return
    try {
      // 紧急停止：立刻停循环，避免继续消耗模型算力和刷日志
      if (safety.panic.value) {
        pushLog(`已触发紧急停止（${safety.hotkey.value}），循环停止。解除后可重新开始`)
        stop()
        return
      }

      const frame = demoMode.value ? makeDemoFrame() : await obs!.capture()
      lastFrame.value = frame

      const state = await pickVision().analyze({ frame, profile, history })
      lastState.value = state
      history.push(state)
      if (history.length > 8)
        history.shift()

      const knowledgeBlock = buildKnowledgeBlock(state)
      lastKnowledge.value = knowledgeBlock

      const raw = await pickPlanner().plan({
        state,
        profile,
        history,
        goal: goal.value,
        knowledge: knowledgeBlock || undefined,
      })

      // 安全清洗：白名单 + 参数夹取 + 抖动 + 批次截断
      const { actions, dropped } = sanitizeActions(raw, profile, {
        maxBatch: maxBatch.value,
        jitter: jitter.value,
        screen: { width: frame.width, height: frame.height },
      })
      lastActions.value = actions
      lastDropped.value = dropped.map(d => `${d.action?.type ?? '?'}：${d.reason}`)
      lastSay.value = raw.map(a => a.say).find(Boolean) ?? ''

      if (dropped.length)
        pushLog(`安全层过滤掉 ${dropped.length} 个动作（${dropped[0].reason}${dropped.length > 1 ? ' 等' : ''}）`)

      // read 模式：列出动作但不自动注入，待用户在 UI 点「确认执行」。
      const effectiveMode = mode.value === 'goal' ? 'autonomous' : mode.value
      if (effectiveMode === 'autonomous' && actions.length) {
        const input = pickInput()
        await input.execute(actions)
        pushLog(`执行 ${actions.length} 个动作（${input.name}）${lastSay.value ? ` · 旁白：${lastSay.value.slice(0, 40)}` : ''}`)
      }
      else if (mode.value === 'read' && actions.length) {
        pushLog(`建议 ${actions.length} 个动作，等待确认（read 模式）`)
      }
      else {
        pushLog(`分析完成，建议 ${actions.length} 个动作（副驾驶模式不注入）${knowledgeBlock ? ' · 已注入经验' : ''}`)
      }

      // 每 20 轮把经验使用计数落一次盘，避免每次决策都写文件
      tickCount++
      if (tickCount % 20 === 0)
        void knowledge.persistUsage().catch(() => {})
    }
    catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      pushLog(`循环错误：${msg}`)
      // 把视觉/决策后端失败也提到顶部红条，避免只在底部日志刷屏而不易察觉
      error.value = msg
    }
    finally {
      if (running.value)
        timer = setTimeout(tick, loopIntervalMs.value)
    }
  }

  async function start() {
    if (running.value)
      return
    error.value = ''

    safety.startPolling()
    await safety.refresh()
    if (safety.panic.value) {
      error.value = '紧急停止仍生效，请先点「解除」再开始'
      pushLog(error.value)
      return
    }

    if (useKnowledge.value && !knowledge.items.value.length) {
      try {
        await knowledge.load()
        if (knowledge.items.value.length)
          pushLog(`已载入 ${knowledge.items.value.length} 条学习经验`)
      }
      catch (err) {
        // 经验库加载失败不应阻断演示模式：只记录，继续往下跑
        pushLog(`经验库加载失败（演示不受影响）：${err instanceof Error ? err.message : String(err)}`)
      }
    }

    running.value = true

    if (!demoMode.value) {
      obs = new ObsCapture({
        url: obsUrl.value,
        password: obsPassword.value || undefined,
        sourceName: obsSource.value,
      })
      obs.onStatus = (s, d) => {
        obsStatus.value = s
        pushLog(d ? `OBS: ${s} (${d})` : `OBS: ${s}`)
      }
      pushLog('正在连接 OBS…')
      try {
        await obs.connect()
      }
      catch (err) {
        error.value = `OBS 连接失败：${err instanceof Error ? err.message : String(err)}`
        pushLog(error.value)
        running.value = false
        obs = null
        return
      }
    }
    else {
      pushLog('演示模式：使用合成画面，无需 OBS/模型')
    }

    if (inputBackendId.value === 'ipc' && (mode.value === 'autonomous' || mode.value === 'goal'))
      pushLog(`⚠ 真实注入已启用，随时按 ${safety.hotkey.value} 紧急停止`)

    pushLog('开始感知-决策循环')
    tick()
  }

  function stop() {
    running.value = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    obs?.disconnect()
    obs = null
    void knowledge.persistUsage().catch(() => {})
    pushLog('已停止')
  }

  // read 模式：用户确认后，把最近一次建议动作注入系统。
  async function confirmLastActions() {
    if (!lastActions.value.length)
      return
    if (safety.panic.value) {
      pushLog('紧急停止生效中，无法执行')
      return
    }
    const input = new SafeIpcInputBackend(onInjectResult)
    await input.execute(lastActions.value)
    pushLog(`已确认执行 ${lastActions.value.length} 个动作（${input.name}）`)
  }

  /** 面板上的大红按钮：立即停手并释放所有按键 */
  async function emergencyStop() {
    await safety.panicNow()
    stop()
    pushLog('已紧急停止：所有按键已释放')
  }

  async function resumeFromPanic() {
    await safety.resume()
    pushLog('紧急停止已解除')
  }

  onUnmounted(() => {
    stop()
    safety.stopPolling()
  })

  return {
    profile,
    obsUrl,
    obsPassword,
    obsSource,
    demoMode,
    ollamaBaseUrl,
    visionModel,
    plannerModel,
    visionBackendId,
    plannerBackendId,
    inputBackendId,
    mode,
    goal,
    loopIntervalMs,
    useKnowledge,
    knowledgeTopK,
    maxBatch,
    jitter,
    running,
    injecting,
    obsStatus,
    lastFrame,
    lastState,
    lastActions,
    lastSay,
    lastKnowledge,
    lastDropped,
    logs,
    error,
    knowledge,
    safety,
    start,
    stop,
    confirmLastActions,
    emergencyStop,
    resumeFromPanic,
  }
}
