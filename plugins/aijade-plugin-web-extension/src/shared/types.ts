export type VideoSite = 'youtube' | 'bilibili' | 'unknown'

/** 网页正文片段定位锚（报告 P2-3）：相对 `PageContextPayload.bodyText` 的字符区间。 */
export interface PageSpan {
  start_offset: number
  end_offset: number
  label: string
}

export interface PageContextPayload {
  site: VideoSite
  url: string
  title: string
  description?: string
  language?: string
  /**
   * 真实正文抽取（报告 P2-3）：从 `<article>/<main>` 的段落/标题/列表块拼接，
   * 配合 `spans` 给出每个块在 `bodyText` 内的字符定位锚。缺省（未采集到正文）时，
   * 归约器回退到 `title + description` 的确定性口径，行为与改动前一致。
   */
  bodyText?: string
  spans?: PageSpan[]
}

/** 用户选区（报告 P2-4）：`window.getSelection()` 采集，偏移相对 `document.body` 文本。 */
export interface SelectionPayload {
  site: VideoSite
  url: string
  selected_text: string
  start_offset: number
  end_offset: number
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
    | { type: 'content:selection', payload: SelectionPayload }
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
  /**
   * LLM 摘要端点 base URL（不含路径），打到 `POST /api/v1/openai/chat/completions`。
   * 默认从 `wsUrl` 同源推导（与 `DEFAULT_REST_BASE_URL` 一致：`http://localhost:6121`）。
   * 与 REST 上报同源，故复用同一个 dev server。缺省时回落到 `DEFAULT_REST_BASE_URL`。
   */
  llmBaseUrl?: string
  /**
   * 摘要用模型名；`'auto'` 走服务端 `DEFAULT_CHAT_MODEL`（见 chat-completions 路由）。
   * 余额不足时服务端计费闸会返回 402——这是**预期失败**，调用方据此回退确定性兜底。
   * 缺省时回落到 `'auto'`。
   */
  llmModel?: string
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
  lastSelection?: SelectionPayload
  lastVisionFrameAt?: number
  /**
   * v10 REST 上报通道的可观测遥测（报告 P3-6）。此前上报失败被静默 `console.warn`，
   * "上报成功"无法证明；现在把成功/失败计数与最近一次失败原因暴露给状态面板，
   * 让失败可见、可证明。
   */
  restReport?: {
    successes: number
    failures: number
    consecutiveFailures: number
    lastSuccessAt?: number
    lastFailureAt?: number
    lastFailureReason?: string
  }
}

export type BackgroundToContentMessage
  = | { type: 'background:request-vision-frame' }
