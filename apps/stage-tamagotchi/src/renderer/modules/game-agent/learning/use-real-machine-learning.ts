import type { GameFrame, GameProfile } from '../types'
import type { InputEvent, LearningEpisode, LearningKeyframe, RealMachineStats } from './types'

/**
 * 真机学习 —— 在旁边看真人玩，边看边记。
 *
 * 同时跑两条采集流水线，并按时间轴对齐：
 *   - 操作流：主进程全局采样真人的键鼠事件（毫秒级）
 *   - 画面流：按固定间隔从 OBS 抓取游戏画面关键帧（秒级）
 *
 * 对齐后每个关键帧都带上「这一刻前后人类做了什么操作」，
 * 于是就得到了「看到什么 → 该怎么做」的成对示范数据，
 * 这正是后续 distill 提炼经验条目所需要的输入。
 */
import { computed, onUnmounted, ref, shallowRef } from 'vue'

import { describeEvents, dumpRecorder, pollRecorder, startRecorder, stopRecorder } from './recorder'

export interface RealMachineDeps {
  profile: GameProfile
  /** 抓取一帧游戏画面；返回 null 表示当前不可用（例如未连 OBS） */
  captureFrame: () => Promise<GameFrame | null>
  /** 可选：让视觉模型描述这一帧，得到 caption / structured */
  captionFrame?: (frame: GameFrame) => Promise<{ caption?: string, structured?: Record<string, unknown> }>
}

export function useRealMachineLearning(deps: RealMachineDeps) {
  // —— 配置 ——
  /** 关键帧抓取间隔 */
  const frameIntervalMs = ref(2000)
  /** 是否边录边让视觉模型描述画面（更慢但知识更丰富） */
  const captionWhileRecording = ref(false)
  /** 关键帧前后多少毫秒内的操作算作"与这一帧相关" */
  const actionWindowMs = ref(1500)
  /** 最多保留多少关键帧 */
  const maxFrames = ref(300)
  const title = ref('')
  const notes = ref('')

  // —— 运行时状态 ——
  const recording = ref(false)
  const startedAt = ref(0)
  const elapsedMs = ref(0)
  const events = shallowRef<InputEvent[]>([])
  const keyframes = shallowRef<LearningKeyframe[]>([])
  const lastFrame = shallowRef<GameFrame | null>(null)
  const recentActions = ref<string[]>([])
  const logs = ref<string[]>([])
  const error = ref('')
  const lastEpisode = shallowRef<LearningEpisode | null>(null)

  const keyCounts = ref<Record<string, number>>({})
  const clickCounts = ref<Record<string, number>>({})

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let frameTimer: ReturnType<typeof setInterval> | null = null
  let tickTimer: ReturnType<typeof setInterval> | null = null

  function pushLog(msg: string) {
    logs.value.push(`[${new Date().toLocaleTimeString()}] ${msg}`)
    if (logs.value.length > 200)
      logs.value.shift()
  }

  const stats = computed<RealMachineStats>(() => {
    const minutes = Math.max(elapsedMs.value / 60000, 1 / 60)
    let actionCount = 0
    for (const n of Object.values(keyCounts.value))
      actionCount += n
    for (const n of Object.values(clickCounts.value))
      actionCount += n
    return {
      apm: Math.round(actionCount / minutes),
      keyCounts: keyCounts.value,
      clickCounts: clickCounts.value,
      frameCount: keyframes.value.length,
      elapsedMs: elapsedMs.value,
    }
  })

  /** 使用频率最高的按键，用于快速看出这局主要在按什么。 */
  const topKeys = computed(() => {
    return Object.entries(keyCounts.value)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 10)
  })

  function ingest(newEvents: InputEvent[]) {
    if (!newEvents.length)
      return
    events.value = events.value.concat(newEvents)
    const keys = { ...keyCounts.value }
    const clicks = { ...clickCounts.value }
    for (const ev of newEvents) {
      if (ev.kind === 'key' && ev.down && ev.key)
        keys[ev.key] = (keys[ev.key] ?? 0) + 1
      else if (ev.kind === 'mouse' && ev.down && ev.button)
        clicks[ev.button] = (clicks[ev.button] ?? 0) + 1
    }
    keyCounts.value = keys
    clickCounts.value = clicks
    recentActions.value = describeEvents(newEvents.filter(e => e.kind !== 'move')).slice(-12)
  }

  /** 取某个时间点附近的操作，用于给关键帧打动作标注。 */
  function actionsNear(t: number): string[] {
    const w = actionWindowMs.value
    const near = events.value.filter(e => e.kind !== 'move' && e.t >= t - w && e.t <= t + w)
    return describeEvents(near).slice(0, 24)
  }

  async function grabFrame() {
    if (!recording.value)
      return
    try {
      const frame = await deps.captureFrame()
      if (!frame)
        return
      lastFrame.value = frame
      const t = Date.now() - startedAt.value
      const kf: LearningKeyframe = {
        t,
        thumbnail: frame.dataUrl,
        nearbyActions: actionsNear(t),
      }
      if (captionWhileRecording.value && deps.captionFrame) {
        try {
          const desc = await deps.captionFrame(frame)
          kf.caption = desc.caption
          kf.structured = desc.structured
        }
        catch (err) {
          pushLog(`画面描述失败：${err instanceof Error ? err.message : String(err)}`)
        }
      }
      const next = keyframes.value.concat(kf)
      keyframes.value = next.length > maxFrames.value ? next.slice(next.length - maxFrames.value) : next
    }
    catch (err) {
      pushLog(`抓帧失败：${err instanceof Error ? err.message : String(err)}`)
    }
  }

  async function start() {
    if (recording.value)
      return
    error.value = ''
    events.value = []
    keyframes.value = []
    keyCounts.value = {}
    clickCounts.value = {}
    recentActions.value = []
    elapsedMs.value = 0

    try {
      const status = await startRecorder({ sampleMs: 15, moveThrottleMs: 80, moveMinDelta: 6 })
      if (status.error)
        pushLog(`录制器警告：${status.error}`)
    }
    catch (err) {
      error.value = `无法启动录制器：${err instanceof Error ? err.message : String(err)}`
      pushLog(error.value)
      return
    }

    recording.value = true
    startedAt.value = Date.now()
    pushLog('开始真机学习：正在观察真人的操作与画面')

    pollTimer = setInterval(async () => {
      try {
        const res = await pollRecorder()
        ingest(res.events ?? [])
        if (res.error)
          error.value = res.error
      }
      catch {
        // 忽略单次拉取失败
      }
    }, 300)

    frameTimer = setInterval(() => void grabFrame(), frameIntervalMs.value)
    tickTimer = setInterval(() => {
      elapsedMs.value = Date.now() - startedAt.value
    }, 500)

    void grabFrame()
  }

  function clearTimers() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (frameTimer) {
      clearInterval(frameTimer)
      frameTimer = null
    }
    if (tickTimer) {
      clearInterval(tickTimer)
      tickTimer = null
    }
  }

  async function stop(): Promise<LearningEpisode | null> {
    if (!recording.value)
      return null
    clearTimers()
    recording.value = false

    let allEvents: InputEvent[] = events.value
    try {
      const res = await stopRecorder()
      if (Array.isArray(res.events) && res.events.length >= allEvents.length)
        allEvents = res.events
    }
    catch {
      try {
        const res = await dumpRecorder()
        if (Array.isArray(res.events))
          allEvents = res.events
      }
      catch {
        // 用已增量拉取到的事件兜底
      }
    }

    const endedAt = Date.now()
    // 补齐关键帧的动作标注（录制中可能有帧在事件到达前就生成了）
    events.value = allEvents
    const frames = keyframes.value.map(kf => ({
      ...kf,
      nearbyActions: kf.nearbyActions?.length ? kf.nearbyActions : actionsNear(kf.t),
    }))

    const episode: LearningEpisode = {
      id: `rm-${endedAt}-${Math.random().toString(36).slice(2, 8)}`,
      source: 'real-machine',
      profileId: deps.profile.id,
      title: title.value.trim() || `真机学习 ${new Date(startedAt.value).toLocaleString()}`,
      startedAt: startedAt.value,
      endedAt,
      durationMs: endedAt - startedAt.value,
      events: allEvents,
      keyframes: frames,
      notes: notes.value.trim() || undefined,
    }
    lastEpisode.value = episode
    pushLog(`录制结束：${allEvents.length} 个操作事件、${frames.length} 个关键帧`)
    return episode
  }

  /** 停止并直接落盘。 */
  async function stopAndSave(): Promise<LearningEpisode | null> {
    const ep = await stop()
    if (!ep)
      return null
    try {
      await window.electron.ipcRenderer.invoke('game-agent:episode:save', JSON.parse(JSON.stringify(ep)), 40)
      pushLog(`已保存学习素材：${ep.title}`)
    }
    catch (err) {
      pushLog(`保存失败：${err instanceof Error ? err.message : String(err)}`)
    }
    return ep
  }

  onUnmounted(() => {
    clearTimers()
    if (recording.value)
      void stopRecorder().catch(() => undefined)
  })

  return {
    frameIntervalMs,
    captionWhileRecording,
    actionWindowMs,
    maxFrames,
    title,
    notes,
    recording,
    startedAt,
    elapsedMs,
    events,
    keyframes,
    lastFrame,
    recentActions,
    logs,
    error,
    lastEpisode,
    stats,
    topKeys,
    start,
    stop,
    stopAndSave,
  }
}
