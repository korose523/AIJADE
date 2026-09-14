/**
 * 视频抽帧引擎（视频学习的"眼睛"）。
 *
 * 关键设计：离线视频不需要真的播一遍。直接 seek 到目标时间点截帧，
 * 于是一个 1 小时的教学视频几分钟就能"看"完——这是视频学习相对真机学习
 * 最大的效率优势（真机学习必须实时陪跑）。
 *
 * 直播场景没法 seek，只能实时采样，走 OBS 通道（把播放器/浏览器窗口做成 OBS 源）。
 */
import type { GameFrame } from '../types'

export interface VideoMeta {
  durationSec: number
  width: number
  height: number
}

export class VideoFrameExtractor {
  private video: HTMLVideoElement | null = null
  private canvas: HTMLCanvasElement | null = null
  private objectUrl: string | null = null

  /** 加载视频源。src 可以是 object URL（本地文件）或可直接播放的直链。 */
  async load(src: string, isObjectUrl = false): Promise<VideoMeta> {
    this.dispose()
    if (isObjectUrl)
      this.objectUrl = src

    const video = document.createElement('video')
    video.preload = 'auto'
    video.muted = true
    video.playsInline = true
    // 跨域直链需要服务端允许，否则 canvas 会被污染而无法导出像素
    if (!isObjectUrl)
      video.crossOrigin = 'anonymous'
    video.src = src
    this.video = video

    await new Promise<void>((resolve, reject) => {
      const onReady = () => {
        cleanup()
        resolve()
      }
      const onError = () => {
        cleanup()
        reject(new Error('视频加载失败：格式不支持或地址不可访问'))
      }
      function cleanup() {
        video.removeEventListener('loadedmetadata', onReady)
        video.removeEventListener('error', onError)
      }
      video.addEventListener('loadedmetadata', onReady)
      video.addEventListener('error', onError)
    })

    const canvas = document.createElement('canvas')
    canvas.width = Math.min(video.videoWidth || 1280, 1280)
    canvas.height = Math.round(canvas.width * ((video.videoHeight || 720) / (video.videoWidth || 1280)))
    this.canvas = canvas

    return {
      durationSec: Number.isFinite(video.duration) ? video.duration : 0,
      width: video.videoWidth,
      height: video.videoHeight,
    }
  }

  /** seek 到指定秒并截取一帧。 */
  async grabAt(timeSec: number): Promise<GameFrame> {
    const video = this.video
    const canvas = this.canvas
    if (!video || !canvas)
      throw new Error('视频尚未加载')

    await new Promise<void>((resolve, reject) => {
      let settled = false
      const onSeeked = () => {
        if (settled)
          return
        settled = true
        cleanup()
        resolve()
      }
      const onError = () => {
        if (settled)
          return
        settled = true
        cleanup()
        reject(new Error('seek 失败'))
      }
      const cleanup = () => {
        video.removeEventListener('seeked', onSeeked)
        video.removeEventListener('error', onError)
        clearTimeout(timeout)
      }
      const timeout = setTimeout(() => {
        // 某些编码格式 seek 事件不稳定，超时后按当前帧凑合用
        if (!settled) {
          settled = true
          cleanup()
          resolve()
        }
      }, 4000)
      video.addEventListener('seeked', onSeeked)
      video.addEventListener('error', onError)
      video.currentTime = Math.max(0, timeSec)
    })

    const ctx = canvas.getContext('2d')
    if (!ctx)
      throw new Error('无法创建 canvas 上下文')
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    let dataUrl: string
    try {
      dataUrl = canvas.toDataURL('image/jpeg', 0.7)
    }
    catch {
      throw new Error('画面被跨域策略污染，无法读取。请改用本地文件或 OBS 源')
    }

    return {
      dataUrl,
      width: canvas.width,
      height: canvas.height,
      timestamp: Math.round(timeSec * 1000),
    }
  }

  dispose(): void {
    if (this.video) {
      this.video.pause()
      this.video.removeAttribute('src')
      this.video.load()
      this.video = null
    }
    if (this.objectUrl) {
      URL.revokeObjectURL(this.objectUrl)
      this.objectUrl = null
    }
    this.canvas = null
  }
}
