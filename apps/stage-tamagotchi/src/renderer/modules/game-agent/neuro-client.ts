import type { NeuroServerOptions, NeuroServerStatus } from './types'

/**
 * Neuro SDK 服务器客户端（渲染端）—— 控制主进程里的 VedalAI neuro-game-sdk 服务器。
 *
 * 通过 window.electron.ipcRenderer.invoke 与主进程通信；useNeuroServer() 提供响应式状态，
 * 并在服务器运行期间轮询状态（连接到的游戏、AI 旁白 say、日志）。
 *
 * 参考：https://github.com/VedalAI/neuro-game-sdk
 */
import { onUnmounted, ref, shallowRef } from 'vue'

export function useNeuroServer() {
  const running = ref(false)
  const port = ref(8000)
  const baseUrl = ref('http://localhost:11434')
  const model = ref('qwen2.5-vl')
  const systemPrompt = ref('你是一个 AI 游戏玩家（参考 Neuro-sama 风格）。根据游戏上报的状态与已注册动作，选择最合理的动作，并给出一句简短的旁白（say）。')
  const goal = ref('')
  const status = shallowRef<NeuroServerStatus | null>(null)

  let timer: ReturnType<typeof setInterval> | null = null

  async function refresh() {
    try {
      status.value = await window.electron.ipcRenderer.invoke('game-agent:neuro-server:status') as NeuroServerStatus
      running.value = status.value.running
    }
    catch {
      /* 忽略轮询错误 */
    }
  }

  async function start() {
    const opts: NeuroServerOptions = {
      port: port.value,
      baseUrl: baseUrl.value,
      model: model.value,
      systemPrompt: systemPrompt.value,
      goal: goal.value,
    }
    status.value = await window.electron.ipcRenderer.invoke('game-agent:neuro-server:start', opts) as NeuroServerStatus
    running.value = true
    startPolling()
  }

  async function stop() {
    status.value = await window.electron.ipcRenderer.invoke('game-agent:neuro-server:stop') as NeuroServerStatus
    running.value = false
    stopPolling()
  }

  function startPolling() {
    if (timer)
      return
    timer = setInterval(refresh, 1000)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  onUnmounted(stopPolling)

  return {
    running,
    port,
    baseUrl,
    model,
    systemPrompt,
    goal,
    status,
    start,
    stop,
    refresh,
  }
}
