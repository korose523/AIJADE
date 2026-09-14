import type { LearningEpisode } from './learning/types'
import type { GameFrame, ObservationBox, ObservationState } from './types'

/**
 * useGameStudio —— 游戏工作室总控。
 *
 * 把「学习」「实操」「直播」三条链路装配到一起，并解决它们之间的三个共享问题：
 *
 *  1. 共享一条 OBS 采集连接。真机学习抓帧、视频学习看直播、实操感知画面，
 *     如果各开各的 WebSocket，OBS 侧会同时跑多路截图，白白浪费性能。
 *  2. 共享一个经验库实例。学习端刚提炼出的经验，实操端下一轮决策就该能用上，
 *     两边各自 useKnowledgeBase 会导致内存里两份数据不同步。
 *  3. 打通「AI 说话 → 观众听见」。决策器产出的 say 自动送进导播台念出来并上字幕，
 *     这才是"自己直播打游戏"而不是"自己打游戏"。
 *
 * 页面只消费这一个 composable，各 Tab 组件通过 props 拿到对应分片。
 */
import { computed, ref, shallowRef, watch } from 'vue'

import { distillEpisode } from './learning/distill'
import { useRealMachineLearning } from './learning/use-real-machine-learning'
import { useVideoLearning } from './learning/use-video-learning'
import { ObsCapture } from './obs'
import { ObsOverlayController, pushObservationToHud } from './stream/obs-overlay'
import { useLiveStream } from './stream/use-live-stream'
import { useGameAgent } from './use-game-agent'
import { OllamaVisionBackend } from './vision'

/** 像人类主播一样"边看边解说"的视觉指令：让模型额外给出聚焦/意图/旁白/注意力框。 */
const OBSERVE_INSTRUCTION = [
  '请用"像人类玩家一样观察并解说"的视角，在上面的 JSON 里额外补充这些字段：',
  'focus=此刻你最关注画面里的什么（例如"左前方 2 个敌人正在逼近"）；',
  'goal=你接下来最想做的意图（例如"拉开距离再丢技能"）；',
  'narration=一句像主播的口头解说（20 字内，可带口语）；',
  'confidence=你判断的置信度 0~1；',
  'boxes=你确实在关注的 1~3 个目标，每个含 {label, x, y, w, h}，坐标 x/y/w/h 为相对画面左上角的归一化值（0~1）。',
  '只输出 JSON，不要 markdown 代码块、不要解释。',
].join('\n')

function ipc() {
  return window.electron.ipcRenderer
}

export function useGameStudio() {
  const agent = useGameAgent()
  const profile = agent.profile
  const knowledge = agent.knowledge

  // —— 学习用的 OBS 采集连接（与实操循环分离，避免相互打断）——
  const learnObs = shallowRef<ObsCapture | null>(null)
  const learnObsStatus = ref<string>('disconnected')

  async function ensureLearnObs(): Promise<ObsCapture | null> {
    if (learnObs.value)
      return learnObs.value
    const client = new ObsCapture({
      url: agent.obsUrl.value,
      password: agent.obsPassword.value || undefined,
      sourceName: agent.obsSource.value,
      imageFormat: 'jpg',
      quality: 70,
      width: 960,
    })
    client.onStatus = (s) => {
      learnObsStatus.value = s
      if (s === 'disconnected' || s === 'error')
        learnObs.value = null
    }
    try {
      await client.connect()
      learnObs.value = client
      return client
    }
    catch {
      learnObsStatus.value = 'error'
      return null
    }
  }

  function disconnectLearnObs() {
    learnObs.value?.disconnect()
    learnObs.value = null
    learnObsStatus.value = 'disconnected'
  }

  /** 学习子系统统一的抓帧入口：演示模式下返回 null（学习必须看真画面才有意义） */
  async function captureFrame(): Promise<GameFrame | null> {
    const client = await ensureLearnObs()
    if (!client)
      return null
    try {
      return await client.capture()
    }
    catch {
      return null
    }
  }

  /** 可选的画面理解：复用实操侧配置的 Ollama 视觉模型 */
  async function captionFrame(frame: GameFrame): Promise<{ caption?: string, structured?: Record<string, unknown> }> {
    if (agent.visionBackendId.value !== 'ollama-vision')
      return {}
    const vision = new OllamaVisionBackend({
      baseUrl: agent.ollamaBaseUrl.value,
      model: agent.visionModel.value,
    })
    const state = await vision.analyze({ frame, profile })
    return { caption: state.raw, structured: state.structured }
  }

  const realMachine = useRealMachineLearning({ profile, captureFrame, captionFrame })
  const video = useVideoLearning({ profile, captureObsFrame: captureFrame, captionFrame })
  const live = useLiveStream({ url: agent.obsUrl.value, password: agent.obsPassword.value })

  // —— 观察叠层（OBS 作为 AIJADE 的"眼睛"，参考 obs-urlsource 的 URL→场景 渲染模式）——
  const hudPort = ref<number | null>(null)
  const hudEnabled = ref(false)
  const overlayKind = ref<'browser_source' | 'url_source'>('browser_source')
  const overlayName = ref<string | null>(null)
  const overlayStatus = ref('disconnected')
  const observing = ref(false)
  const obsFps = ref(0)
  /** 观察循环已启动却长时间收不到 OBS 画面时的明确提示（避免"观察中 0fps"却无反馈） */
  const obsHint = ref('')
  const observation = shallowRef<ObservationState>({
    ts: 0,
    observing: false,
    game: profile.name,
    source: agent.obsSource.value,
    focus: '',
    goal: '',
    narration: '',
    confidence: 0,
    fps: 0,
    boxes: [],
  })

  let overlayObs: ObsCapture | null = null
  let overlayCtl: ObsOverlayController | null = null
  let obsTimer: ReturnType<typeof setInterval> | null = null
  let obsHintTimer: ReturnType<typeof setTimeout> | null = null

  /** 让视觉模型以"观察解说"视角理解当前帧，产出聚焦/意图/旁白/注意力框。 */
  async function observeFrame(frame: GameFrame): Promise<{
    focus: string
    goal: string
    narration: string
    confidence: number
    boxes: ObservationBox[]
  }> {
    if (agent.visionBackendId.value !== 'ollama-vision') {
      return { focus: '', goal: '', narration: '', confidence: 0, boxes: [] }
    }
    try {
      const vision = new OllamaVisionBackend({
        baseUrl: agent.ollamaBaseUrl.value,
        model: agent.visionModel.value,
      })
      const state = await vision.analyze({ frame, profile, instruction: OBSERVE_INSTRUCTION })
      const s = (state.structured || {}) as Record<string, unknown>
      const boxes = Array.isArray(s.boxes)
        ? (s.boxes as any[])
            .filter(b => b && typeof b.x === 'number' && typeof b.y === 'number')
            .map(b => ({
              label: String(b.label ?? '目标'),
              x: Number(b.x),
              y: Number(b.y),
              w: Number(b.w ?? 0.1),
              h: Number(b.h ?? 0.1),
              color: typeof b.color === 'string' ? b.color : undefined,
            }))
        : []
      return {
        focus: typeof s.focus === 'string' ? s.focus : (state.raw || '').slice(0, 80),
        goal: typeof s.goal === 'string' ? s.goal : '',
        narration: typeof s.narration === 'string' ? s.narration : '',
        confidence: typeof s.confidence === 'number' ? s.confidence : 0.5,
        boxes,
      }
    }
    catch {
      return { focus: '', goal: '', narration: '', confidence: 0, boxes: [] }
    }
  }

  /** 抓一帧 → 理解 → 更新观察状态 → 推给 HUD 服务（供 OBS 叠层渲染）。 */
  async function observeOnce(): Promise<void> {
    const frame = await captureFrame()
    if (!frame)
      return
    const cap = await observeFrame(frame)
    const st: ObservationState = {
      ts: Date.now(),
      observing: true,
      game: profile.name,
      source: agent.obsSource.value,
      focus: cap.focus,
      goal: cap.goal,
      narration: cap.narration,
      confidence: cap.confidence,
      fps: obsFps.value,
      boxes: cap.boxes,
    }
    observation.value = st
    observing.value = true
    if (hudEnabled.value && hudPort.value)
      pushObservationToHud(st)
  }

  /** 以指定 fps 持续观察（默认 1 帧/秒，足够"看懂画面"且省算力）。 */
  function startObservationLoop(fps = 1) {
    stopObservationLoop()
    obsHint.value = ''
    const interval = Math.max(200, 1000 / Math.max(0.2, fps))
    let count = 0
    let windowStart = Date.now()
    obsTimer = setInterval(() => {
      observeOnce().then(() => {
        const now = Date.now()
        count++
        if (now - windowStart >= 1000) {
          obsFps.value = Math.round((count * 1000) / (now - windowStart))
          count = 0
          windowStart = now
          if (obsFps.value > 0)
            obsHint.value = ''
        }
      })
    }, interval)
    // 启动数秒后若仍无画面且 OBS 未连接，给出明确指引，而不是静默停在"观察中 0fps"
    if (obsHintTimer)
      clearTimeout(obsHintTimer)
    obsHintTimer = setTimeout(() => {
      if (observing.value && obsFps.value === 0 && learnObsStatus.value !== 'connected')
        obsHint.value = '未检测到 OBS 画面：请确认 OBS 已启动、WebSocket 地址正确、且「源名称」与「实操」页填写的一致。'
    }, 2500)
  }

  function stopObservationLoop() {
    if (obsTimer) {
      clearInterval(obsTimer)
      obsTimer = null
    }
    if (obsHintTimer) {
      clearTimeout(obsHintTimer)
      obsHintTimer = null
    }
    observing.value = false
    obsHint.value = ''
  }

  async function startHud(): Promise<void> {
    if (hudPort.value)
      return
    hudPort.value = await ipc().invoke('game-agent:hud:start') as number
    hudEnabled.value = true
  }

  async function stopHud(): Promise<void> {
    if (overlayName.value)
      await removeOverlay()
    await ipc().invoke('game-agent:hud:stop')
    hudEnabled.value = false
    hudPort.value = null
  }

  /** 在 OBS 当前场景创建一个"观察叠层"源（覆盖在游戏画面上）。 */
  async function ensureOverlay(): Promise<void> {
    if (!hudPort.value)
      await startHud()
    if (!hudPort.value)
      return
    const client = new ObsCapture({
      url: agent.obsUrl.value,
      password: agent.obsPassword.value || undefined,
      sourceName: agent.obsSource.value,
    })
    client.onStatus = (s) => {
      overlayStatus.value = s
    }
    try {
      await client.connect()
    }
    catch {
      overlayStatus.value = 'error'
      return
    }
    overlayObs = client
    const ctl = new ObsOverlayController(client)
    try {
      const info = await ctl.ensureOverlay({
        port: hudPort.value,
        kind: overlayKind.value,
        gameSource: agent.obsSource.value,
        width: 960,
        height: 540,
      })
      overlayCtl = ctl
      overlayName.value = info.name
    }
    catch (err) {
      overlayStatus.value = 'error'
      client.disconnect()
      overlayObs = null
      console.warn(`创建 OBS 观察叠层失败：${err instanceof Error ? err.message : String(err)}`)
    }
  }

  async function removeOverlay(): Promise<void> {
    if (overlayCtl && overlayName.value) {
      try {
        await overlayCtl.removeOverlay({
          name: overlayName.value,
          scene: '',
          kind: overlayKind.value,
        })
      }
      catch {
        // 源可能已被手动删除
      }
    }
    overlayObs?.disconnect()
    overlayObs = null
    overlayCtl = null
    overlayName.value = null
  }

  async function toggleOverlay(): Promise<void> {
    if (overlayName.value)
      await removeOverlay()
    else
      await ensureOverlay()
  }

  // —— 提炼 ——
  const distilling = ref(false)
  const useLLMDistill = ref(false)
  const distillMaxItems = ref(8)
  const distillLogs = ref<string[]>([])

  function pushDistillLog(msg: string) {
    distillLogs.value.push(`[${new Date().toLocaleTimeString()}] ${msg}`)
    if (distillLogs.value.length > 80)
      distillLogs.value.shift()
  }

  /** 把一份素材提炼成经验并入库 */
  async function distillAndStore(ep: LearningEpisode): Promise<number> {
    distilling.value = true
    try {
      const { items, llmError } = await distillEpisode(ep, profile, {
        useLLM: useLLMDistill.value,
        baseUrl: agent.ollamaBaseUrl.value,
        model: agent.plannerModel.value,
        maxItems: distillMaxItems.value,
      })
      if (llmError)
        pushDistillLog(`语言模型提炼失败，已回退启发式：${llmError}`)
      if (!items.length) {
        pushDistillLog('未提炼出经验（素材可能太短或没有有效操作）')
        return 0
      }
      await knowledge.add(items)
      pushDistillLog(`已从《${ep.title}》提炼 ${items.length} 条经验并入库`)
      return items.length
    }
    catch (err) {
      pushDistillLog(`提炼失败：${err instanceof Error ? err.message : String(err)}`)
      return 0
    }
    finally {
      distilling.value = false
    }
  }

  /** 从磁盘取回素材再提炼（经验库 Tab 的「重新提炼」） */
  async function distillById(episodeId: string): Promise<number> {
    const ep = await knowledge.getEpisode(episodeId)
    if (!ep) {
      pushDistillLog('素材不存在或已被删除')
      return 0
    }
    return await distillAndStore(ep)
  }

  /** 真机学习：停止 → 落盘 → 立刻提炼入库，一步到位 */
  async function finishRealMachineAndLearn(): Promise<number> {
    const ep = await realMachine.stopAndSave()
    await knowledge.loadEpisodes()
    if (!ep)
      return 0
    return await distillAndStore(ep)
  }

  async function finishVideoAndLearn(): Promise<number> {
    const ep = await video.stop()
    await knowledge.loadEpisodes()
    if (!ep)
      return 0
    return await distillAndStore(ep)
  }

  // —— 旁白直达直播间 ——
  const autoNarrate = ref(true)
  watch(() => agent.lastSay.value, (say) => {
    if (autoNarrate.value && say && live.connected.value)
      live.narrate(say)
  })

  /** 一键开播：连 OBS → 开推流 → 启动 Agent 循环 */
  async function goLive(): Promise<void> {
    if (!live.connected.value) {
      const ok = await live.connect()
      if (!ok)
        return
    }
    if (!live.status.value.streaming)
      await live.startStreaming()
    if (!agent.running.value)
      await agent.start()
  }

  /** 一键下播：停 Agent → 停推流 */
  async function endLive(): Promise<void> {
    agent.stop()
    live.clearNarrations()
    if (live.status.value.streaming)
      await live.stopStreaming()
  }

  const busy = computed(() =>
    agent.running.value || realMachine.recording.value || video.learning.value || distilling.value,
  )

  return {
    profile,
    agent,
    knowledge,
    realMachine,
    video,
    live,
    learnObsStatus,
    ensureLearnObs,
    disconnectLearnObs,
    captureFrame,
    distilling,
    useLLMDistill,
    distillMaxItems,
    distillLogs,
    distillAndStore,
    distillById,
    finishRealMachineAndLearn,
    finishVideoAndLearn,
    autoNarrate,
    goLive,
    endLive,
    busy,
    // —— 观察叠层（OBS 作为眼睛 + obs-urlsource 式渲染）——
    hudPort,
    hudEnabled,
    overlayKind,
    overlayName,
    overlayStatus,
    observing,
    observation,
    obsFps,
    obsHint,
    observeOnce,
    startObservationLoop,
    stopObservationLoop,
    startHud,
    stopHud,
    toggleOverlay,
  }
}

/** 各 Tab 组件通过 props 接收的总控句柄 */
export type GameStudio = ReturnType<typeof useGameStudio>
