export type VideoSite = 'youtube' | 'bilibili' | 'unknown'

export interface PageContextPayload {
  site: VideoSite
  url: string
  title: string
  description?: string
  language?: string
}

export interface VideoContextPayload {
  site: VideoSite
  url: string
  title: string
  channel?: string
  videoId?: string
  durationSec?: number
  currentTimeSec?: number
  isPlaying?: boolean
  isMuted?: boolean
  volume?: number
  playbackRate?: number
  isLive?: boolean
  playerSize?: { width: number, height: number }
}

export interface SubtitlePayload {
  site: VideoSite
  url: string
  videoId?: string
  title?: string
  text: string
  language?: string
  startMs?: number
  endMs?: number
  isAuto?: boolean
}

export interface VisionFramePayload {
  site: VideoSite
  url: string
  videoId?: string
  title?: string
  capturedAt: number
  width: number
  height: number
  dataUrl: string
}

export type ContentToBackgroundMessage
  = | { type: 'content:page', payload: PageContextPayload }
    | { type: 'content:video', payload: VideoContextPayload }
    | { type: 'content:subtitle', payload: SubtitlePayload }
    | { type: 'content:vision:frame', payload: VisionFramePayload }

export interface ExtensionSettings {
  wsUrl: string
  token: string
  /**
   * v10 REST 事件上报通道的 base URL（不含路径），打到 `POST /api/v1/v9/events`。
   * 默认从 `wsUrl` 推导同源 HTTP 地址（见 `constants.ts` 的 `DEFAULT_REST_BASE_URL`）。
   */
  restBaseUrl: string
  /**
   * REST 端点鉴权用的 Bearer token（better-auth）。
   * 注意：与 WS 的模块 token 语义不同——REST 端点要的是 better-auth 会话
   * （cookie，靠 `credentials:'include'`）或 Bearer token；两者都没有时服务端
   * `authGuard` 返回 401，这是**预期失败而非 bug**。留空则只靠 cookie。
   */
  bearerToken: string
  enabled: boolean
  sendPageContext: boolean
  sendVideoContext: boolean
  sendSubtitles: boolean
  sendSparkNotify: boolean
  enableVision: boolean
}

export interface ExtensionStatus {
  connected: boolean
  lastError?: string
  settings: ExtensionSettings
  lastPage?: PageContextPayload
  lastVideo?: VideoContextPayload
  lastSubtitle?: SubtitlePayload
  lastVisionFrameAt?: number
}

export type BackgroundToContentMessage
  = | { type: 'background:request-vision-frame' }
