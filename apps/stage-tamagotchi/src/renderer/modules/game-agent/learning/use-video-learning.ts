import type { GameFrame, GameProfile } from '../types'
import type { LearningEpisode, LearningKeyframe, VideoSourceKind } from './types'

/**
 * 视频学习 —— 让 AIJADE 通过"看视频"涨经验。
 *
 * 三种素材来源：
 *   file  本地录像 / 下载好的教学视频 → 直接 seek 抽帧，可快进学习
 *   url   可直接播放的视频直链       → 同上（受跨域限制）
 *   obs   OBS 源                    → 实时采样，用来"看直播"
 *
 * 与真机学习的本质区别：视频里没有键鼠标注，AIJADE 只能看到结果画面。
 * 因此这里额外支持粘贴解说/字幕文本（游戏解析视频的干货大多在解说里），
 * 与画面描述一起交给提炼器，才能还原出"为什么这么打"。
 */
import { computed, onUnmounted, ref, shallowRef } from 'vue'

import { VideoFrameExtractor } from './video-learner'

export interface VideoLearningDeps {
  profile: GameProfile
  /** obs 模式下用来实时抓帧 */
  captureObsFrame?: () => Promise<GameFrame | null>
  /** 让视觉模型描述一帧 */
  captionFrame?: (frame: GameFrame) => Promise<{ caption?: string, structured?: Record<string, unknown> }>
}

export function useVideoLearning(deps: VideoLearningDeps) {
  // —— 配置 ——
  const kind = ref<VideoSourceKind>('file')
  const url = ref('')
  const obsSampleIntervalMs = ref(3000)
  /** 离线视频按素材时间轴每隔多少秒抽一帧 */
  const sampleIntervalSec = ref(5)
  const maxFrames = ref(80)
  const captionFrames = ref(true)
  /** 解说 / 字幕 / 攻略文本，可留空 */
  const transcript = ref('')
  const title = ref('')
  const notes = ref('')

  // —— 运行时 ——
  const learning = ref(false)
  const progress = ref(0)
  const processed = ref(0)
  const total = ref(0)
  const durationSec = ref(0)
  const originLabel = ref('')
  const keyframes = shallowRef<LearningKeyframe[]>([])
  const lastFrame = shallowRef<GameFrame | null>(null)
  const logs = ref<string[]>([])
  const error = ref('')
  const lastEpisode = shallowRef<LearningEpisode | null>(null)

  const extractor = new VideoFrameExtractor()
  let cancelled = false
  let obsTimer: ReturnType<typeof setInterval> | null = null
  let obsStartedAt = 0
  let selectedObjectUrl: string | null = null

  function pushLog(msg: string) {
    logs.value.push(`[${new Date().toLocaleTimeString()}] ${msg}`)
    if (logs.value.length > 200)
      logs.value.shift()
  }

  const canStart = computed(() => {
    if (learning.value)
      return false
    if (kind.value === 'file')
      return !!selectedObjectUrl
    if (kind.value === 'url')
      return !!url.value.trim()
    return true
  })

  /** 由 <input type="file"> 调用 */
  function selectFile(file: File) {
    if (selectedObjectUrl)
      URL.revokeObjectURL(selectedObjectUrl)
    selectedObjectUrl = URL.createObjectURL(file)
    originLabel.value = file.name
    if (!title.value.trim())
      title.value = `视频学习 · ${file.name}`
    pushLog(`已选择视频：${file.name}（${(file.size / 1024 / 1024).toFixed(1)} MB）`)
  }

  async function describe(frame: GameFrame): Promise<Partial<LearningKeyframe>> {
    if (!captionFrames.value || !deps.captionFrame)
      return {}
    try {
      const d = await deps.captionFrame(frame)
      return { caption: d.caption, structured: d.structured }
    }
    catch (err) {
      pushLog(`画面理解失败：${err instanceof Error ? err.message : String(err)}`)
      return {}
    }
  }

  /** 离线视频：seek 抽帧，可快进 */
  async function learnOffline(src: string, isObjectUrl: boolean) {
    const meta = await extractor.load(src, isObjectUrl)
    durationSec.value = meta.durationSec
    if (!meta.durationSec) {
      pushLog('无法读取视频时长，可能是流式地址；建议改用 OBS 源实时学习')
    }

    const step = Math.max(1, sampleIntervalSec.value)
    const planned = meta.durationSec > 0
      ? Math.min(maxFrames.value, Math.max(1, Math.floor(meta.durationSec / step)))
      : maxFrames.value
    total.value = planned
    pushLog(`开始学习：时长 ${meta.durationSec.toFixed(0)}s，计划抽取 ${planned} 帧（每 ${step}s 一帧）`)

    const collected: LearningKeyframe[] = []
    for (let i = 0; i < planned; i++) {
      if (cancelled)
        break
      const t = i * step
      try {
        const frame = await extractor.grabAt(t)
        lastFrame.value = frame
        const desc = await describe(frame)
        collected.push({
          t: Math.round(t * 1000),
          thumbnail: frame.dataUrl,
          caption: desc.caption,
          structured: desc.structured,
        })
        keyframes.value = collected.slice()
      }
      catch (err) {
        pushLog(`第 ${i + 1} 帧失败：${err instanceof Error ? err.message : String(err)}`)
        // 连续失败大概率是源本身有问题，早点停
        if (i === 0)
          throw err
      }
      processed.value = i + 1
      progress.value = planned ? (i + 1) / planned : 0
    }
  }

  /** 直播：实时采样 */
  function learnLive() {
    obsStartedAt = Date.now()
    total.value = maxFrames.value
    pushLog(`开始观看直播：每 ${obsSampleIntervalMs.value}ms 采样一帧，上限 ${maxFrames.value} 帧`)

    obsTimer = setInterval(async () => {
      if (cancelled || !learning.value)
        return
      try {
        const frame = await deps.captureObsFrame?.()
        if (!frame)
          return
        lastFrame.value = frame
        const desc = await describe(frame)
        const kf: LearningKeyframe = {
          t: Date.now() - obsStartedAt,
          thumbnail: frame.dataUrl,
          caption: desc.caption,
          structured: desc.structured,
        }
        keyframes.value = keyframes.value.concat(kf)
        processed.value = keyframes.value.length
        progress.value = Math.min(1, processed.value / maxFrames.value)
        if (keyframes.value.length >= maxFrames.value) {
          pushLog('已达帧数上限，自动结束')
          void stop()
        }
      }
      catch (err) {
        pushLog(`采样失败：${err instanceof Error ? err.message : String(err)}`)
      }
    }, obsSampleIntervalMs.value)
  }

  async function start() {
    if (learning.value)
      return
    error.value = ''
    cancelled = false
    processed.value = 0
    progress.value = 0
    keyframes.value = []
    learning.value = true

    try {
      if (kind.value === 'obs') {
        originLabel.value = 'OBS 直播源'
        learnLive()
        return
      }
      if (kind.value === 'file') {
        if (!selectedObjectUrl)
          throw new Error('请先选择本地视频文件')
        await learnOffline(selectedObjectUrl, true)
      }
      else {
        const target = url.value.trim()
        if (!target)
          throw new Error('请填写视频地址')
        originLabel.value = target
        await learnOffline(target, false)
      }
      await finish()
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
      pushLog(`学习失败：${error.value}`)
      learning.value = false
    }
  }

  async function finish(): Promise<LearningEpisode | null> {
    if (obsTimer) {
      clearInterval(obsTimer)
      obsTimer = null
    }
    learning.value = false
    extractor.dispose()

    if (!keyframes.value.length) {
      pushLog('没有抽到任何画面，未生成学习素材')
      return null
    }

    const endedAt = Date.now()
    const frames = keyframes.value
    const episode: LearningEpisode = {
      id: `vd-${endedAt}-${Math.random().toString(36).slice(2, 8)}`,
      source: 'video',
      profileId: deps.profile.id,
      title: title.value.trim() || `视频学习 ${new Date().toLocaleString()}`,
      startedAt: endedAt - (frames[frames.length - 1]?.t ?? 0),
      endedAt,
      durationMs: frames[frames.length - 1]?.t ?? 0,
      events: [],
      keyframes: frames,
      origin: originLabel.value,
      notes: [notes.value.trim(), transcript.value.trim() ? `【解说/字幕】\n${transcript.value.trim()}` : '']
        .filter(Boolean)
        .join('\n\n') || undefined,
    }
    lastEpisode.value = episode
    pushLog(`学习完成：共 ${frames.length} 帧`)

    try {
      await window.electron.ipcRenderer.invoke('game-agent:episode:save', JSON.parse(JSON.stringify(episode)), 40)
      pushLog(`已保存学习素材：${episode.title}`)
    }
    catch (err) {
      pushLog(`保存失败：${err instanceof Error ? err.message : String(err)}`)
    }
    return episode
  }

  async function stop(): Promise<LearningEpisode | null> {
    cancelled = true
    return await finish()
  }

  onUnmounted(() => {
    cancelled = true
    if (obsTimer)
      clearInterval(obsTimer)
    extractor.dispose()
    if (selectedObjectUrl)
      URL.revokeObjectURL(selectedObjectUrl)
  })

  return {
    kind,
    url,
    obsSampleIntervalMs,
    sampleIntervalSec,
    maxFrames,
    captionFrames,
    transcript,
    title,
    notes,
    learning,
    progress,
    processed,
    total,
    durationSec,
    originLabel,
    keyframes,
    lastFrame,
    logs,
    error,
    lastEpisode,
    canStart,
    selectFile,
    start,
    stop,
  }
}
