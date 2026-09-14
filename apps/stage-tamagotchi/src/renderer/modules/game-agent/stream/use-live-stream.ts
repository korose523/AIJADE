import type { StreamStatus } from '../types'
import type { InputInfo } from './obs-stream'

/**
 * useLiveStream —— AIJADE 自己开播时的「导播台」。
 *
 * 一场 AI 直播要同时管三件事：推流本身（OBS）、说话（旁白 TTS）、观众看到的字幕。
 * 这三件事节奏不同——决策循环可能一秒产出一句话，但 TTS 念完要好几秒，
 * 字幕也不能刚出现就被下一句冲掉。所以这里用一个串行队列把它们对齐：
 *
 *   旁白入队 → 取出一条 → 写 OBS 字幕 → TTS 念完（或超时）→ 停留一小会 → 取下一条
 *
 * 队列有上限，太旧的旁白会被丢弃：直播是实时的，念三十秒前的战况没有意义。
 *
 * OBS 连接独立于游戏 Agent 的感知连接（obs-websocket 支持多客户端），
 * 这样用户可以只开播不跑 AI，或者只跑 AI 不开播。
 */
import { computed, onScopeDispose, ref, shallowRef } from 'vue'

import { ObsCapture } from '../obs'
import { ObsStreamController } from './obs-stream'

export interface NarrationEntry {
  text: string
  at: number
  spoken: boolean
}

export interface LiveStreamOptions {
  url?: string
  password?: string
  /** 字幕文本源名称（OBS 里的 text 源） */
  subtitleSource?: string
}

function formatDuration(ms: number): string {
  const total = Math.floor(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

export function useLiveStream(options: LiveStreamOptions = {}) {
  // —— 连接配置 ——
  const obsUrl = ref(options.url ?? 'ws://localhost:4455')
  const obsPassword = ref(options.password ?? '')
  const connected = ref(false)
  const connecting = ref(false)
  const error = ref('')

  // —— 直播状态 ——
  const status = shallowRef<StreamStatus>({
    streaming: false,
    recording: false,
    durationMs: 0,
    kbitsPerSec: 0,
    skippedFrames: 0,
    totalFrames: 0,
  })
  const scenes = ref<string[]>([])
  const currentScene = ref('')
  const textInputs = ref<InputInfo[]>([])

  // —— 旁白配置 ——
  const subtitleSource = ref(options.subtitleSource ?? '')
  const enableTts = ref(true)
  const ttsVoice = ref('')
  const ttsRate = ref(1.1)
  const ttsPitch = ref(1.05)
  const subtitleHoldMs = ref(900)
  const maxQueue = ref(3)

  const narrations = ref<NarrationEntry[]>([])
  const speaking = ref(false)
  const currentText = ref('')
  const logs = ref<string[]>([])

  const durationText = computed(() => formatDuration(status.value.durationMs))
  const dropRate = computed(() => {
    const total = status.value.totalFrames
    if (!total)
      return 0
    return Math.round((status.value.skippedFrames / total) * 10000) / 100
  })
  const health = computed<'good' | 'warning' | 'bad' | 'idle'>(() => {
    if (!status.value.streaming)
      return 'idle'
    if (dropRate.value > 5)
      return 'bad'
    if (dropRate.value > 1)
      return 'warning'
    return 'good'
  })

  let obs: ObsCapture | null = null
  let controller: ObsStreamController | null = null
  let statusTimer: ReturnType<typeof setInterval> | null = null
  const queue: string[] = []
  let draining = false
  let disposed = false

  function pushLog(msg: string) {
    logs.value.push(`[${new Date().toLocaleTimeString()}] ${msg}`)
    if (logs.value.length > 120)
      logs.value.shift()
  }

  async function connect(): Promise<boolean> {
    if (connected.value)
      return true
    connecting.value = true
    error.value = ''
    const client = new ObsCapture({
      url: obsUrl.value,
      password: obsPassword.value || undefined,
      // 直播控制不抓图，源名只是占位
      sourceName: '',
    })
    client.onStatus = (s, d) => {
      if (s === 'disconnected' || s === 'error') {
        connected.value = false
        if (d)
          pushLog(`OBS: ${s} (${d})`)
      }
    }
    try {
      await client.connect()
      obs = client
      controller = new ObsStreamController(client)
      connected.value = true
      pushLog('已连接 OBS 导播')
      await Promise.all([refreshStatus(), refreshScenes(), refreshTextInputs()])
      startStatusPolling()
      return true
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      pushLog(`OBS 连接失败：${error.value}`)
      connected.value = false
      obs = null
      controller = null
      return false
    }
    finally {
      connecting.value = false
    }
  }

  function disconnect() {
    stopStatusPolling()
    obs?.disconnect()
    obs = null
    controller = null
    connected.value = false
    pushLog('已断开 OBS 导播')
  }

  async function refreshStatus() {
    if (!controller)
      return
    try {
      status.value = await controller.getStatus()
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function refreshScenes() {
    if (!controller)
      return
    try {
      const info = await controller.listScenes()
      scenes.value = info.scenes
      currentScene.value = info.current
    }
    catch {
      // OBS 版本差异导致的请求失败不致命，忽略
    }
  }

  async function refreshTextInputs() {
    if (!controller)
      return
    try {
      textInputs.value = await controller.listTextInputs()
      if (!subtitleSource.value && textInputs.value.length)
        subtitleSource.value = textInputs.value[0].name
    }
    catch {
      // 同上
    }
  }

  function startStatusPolling() {
    if (statusTimer)
      return
    statusTimer = setInterval(() => void refreshStatus(), 2000)
  }

  function stopStatusPolling() {
    if (statusTimer) {
      clearInterval(statusTimer)
      statusTimer = null
    }
  }

  async function startStreaming() {
    if (!controller && !(await connect()))
      return
    try {
      await controller!.startStreaming()
      pushLog('开播')
      await refreshStatus()
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      pushLog(`开播失败：${error.value}`)
    }
  }

  async function stopStreaming() {
    if (!controller)
      return
    try {
      await controller.stopStreaming()
      pushLog('已下播')
      await setSubtitle('')
      await refreshStatus()
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function toggleStreaming() {
    if (status.value.streaming)
      await stopStreaming()
    else
      await startStreaming()
  }

  async function toggleRecording() {
    if (!controller && !(await connect()))
      return
    try {
      if (status.value.recording) {
        const path = await controller!.stopRecording()
        pushLog(path ? `录制已保存：${path}` : '录制已停止')
      }
      else {
        await controller!.startRecording()
        pushLog('开始录制')
      }
      await refreshStatus()
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function switchScene(name: string) {
    if (!controller)
      return
    try {
      await controller.setScene(name)
      currentScene.value = name
      pushLog(`切换场景：${name}`)
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function setSubtitle(text: string) {
    if (!controller || !subtitleSource.value)
      return
    try {
      await controller.setText(subtitleSource.value, text)
    }
    catch {
      // 字幕写失败不应打断直播
    }
  }

  // —— TTS ——
  function listVoices(): SpeechSynthesisVoice[] {
    if (typeof window === 'undefined' || !window.speechSynthesis)
      return []
    return window.speechSynthesis.getVoices()
  }

  function speak(text: string): Promise<void> {
    return new Promise((resolve) => {
      if (!enableTts.value || typeof window === 'undefined' || !window.speechSynthesis) {
        resolve()
        return
      }
      const utter = new SpeechSynthesisUtterance(text)
      utter.rate = ttsRate.value
      utter.pitch = ttsPitch.value
      const voices = listVoices()
      const picked = ttsVoice.value
        ? voices.find(v => v.name === ttsVoice.value)
        : voices.find(v => v.lang?.toLowerCase().startsWith('zh'))
      if (picked)
        utter.voice = picked
      // 兜底超时：某些语音引擎不触发 onend，不能让队列卡死
      const timeout = setTimeout(resolve, Math.min(20000, 2500 + text.length * 260))
      const done = () => {
        clearTimeout(timeout)
        resolve()
      }
      utter.onend = done
      utter.onerror = done
      try {
        window.speechSynthesis.speak(utter)
      }
      catch {
        done()
      }
    })
  }

  async function drain() {
    if (draining)
      return
    draining = true
    try {
      while (queue.length && !disposed) {
        const text = queue.shift()!
        currentText.value = text
        speaking.value = true
        await setSubtitle(text)
        await speak(text)
        // 让字幕多停留一会，避免观众来不及读
        await new Promise(r => setTimeout(r, subtitleHoldMs.value))
        const entry = narrations.value.find(n => n.text === text && !n.spoken)
        if (entry)
          entry.spoken = true
      }
      speaking.value = false
      currentText.value = ''
      if (!disposed)
        await setSubtitle('')
    }
    finally {
      draining = false
    }
  }

  /**
   * 把一句旁白交给导播台。
   * 队列满时丢弃最旧的——直播讲的是当下，积压的解说没有价值。
   */
  function narrate(text: string) {
    const clean = text?.trim()
    if (!clean)
      return
    if (narrations.value.length && narrations.value[narrations.value.length - 1].text === clean)
      return
    queue.push(clean)
    while (queue.length > maxQueue.value)
      queue.shift()
    narrations.value.push({ text: clean, at: Date.now(), spoken: false })
    if (narrations.value.length > 60)
      narrations.value.shift()
    void drain()
  }

  function clearNarrations() {
    queue.length = 0
    narrations.value = []
    currentText.value = ''
    if (typeof window !== 'undefined' && window.speechSynthesis)
      window.speechSynthesis.cancel()
    void setSubtitle('')
  }

  onScopeDispose(() => {
    disposed = true
    queue.length = 0
    if (typeof window !== 'undefined' && window.speechSynthesis)
      window.speechSynthesis.cancel()
    disconnect()
  })

  return {
    // 连接
    obsUrl,
    obsPassword,
    connected,
    connecting,
    error,
    connect,
    disconnect,
    // 状态
    status,
    durationText,
    dropRate,
    health,
    scenes,
    currentScene,
    textInputs,
    refreshStatus,
    refreshScenes,
    refreshTextInputs,
    // 控制
    startStreaming,
    stopStreaming,
    toggleStreaming,
    toggleRecording,
    switchScene,
    // 旁白
    subtitleSource,
    enableTts,
    ttsVoice,
    ttsRate,
    ttsPitch,
    subtitleHoldMs,
    maxQueue,
    narrations,
    speaking,
    currentText,
    listVoices,
    narrate,
    clearNarrations,
    setSubtitle,
    logs,
  }
}
