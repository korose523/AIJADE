import type { BackgroundToContentMessage, ContentToBackgroundMessage, PageContextPayload, PageSpan, SelectionPayload, SubtitlePayload, VideoContextPayload, VideoSite, VisionFramePayload } from '../shared/types'

import { detectSiteFromUrl, extractVideoId, normalizeText } from '../shared/sites'

const VIDEO_PROGRESS_INTERVAL = 15000
const TITLE_POLL_INTERVAL = 2000
const SUBTITLE_DEDUPE_WINDOW = 2000
const SELECTION_DEBOUNCE_MS = 300

const lastPayloadByType = new Map<string, string>()

function safeSend(message: ContentToBackgroundMessage) {
  const serialized = JSON.stringify(message.payload)
  const lastSerialized = lastPayloadByType.get(message.type)
  if (serialized === lastSerialized)
    return

  lastPayloadByType.set(message.type, serialized)
  void browser.runtime.sendMessage(message).catch(() => {})
}

function buildPageContext(site: VideoSite): PageContextPayload {
  const description = normalizeText(document.querySelector('meta[name="description"]')?.getAttribute('content'))
  const ogDescription = normalizeText(document.querySelector('meta[property="og:description"]')?.getAttribute('content'))

  const payload: PageContextPayload = {
    site,
    url: location.href,
    title: normalizeText(document.title),
    description: description || ogDescription || undefined,
    language: document.documentElement.lang || undefined,
  }

  // 报告 P2-3：抽取真实正文（段落/标题/列表），产出 bodyText + 每个块的定位锚 spans。
  // 缺失（无正文块）时留空，归约器自动回退到 title + description。
  const body = extractBodyText()
  if (body) {
    payload.bodyText = body.text
    payload.spans = body.spans
  }

  return payload
}

/**
 * 报告 P2-3：从 `<article>` / `<main>`（回退 `<body>`）抽取正文块文本。
 * 逐块归约 + 记录每个块在拼接后 `bodyText` 内的字符区间（spans）。
 * 噪声标签（script/style/nav/header/footer/aside 等）被跳过；正文块取 `p/h1-h6/li` 的 innerText。
 */
function extractBodyText(): { text: string, spans: PageSpan[] } | null {
  const root = document.querySelector('article') || document.querySelector('main') || document.body
  if (!root)
    return null

  const blocks = Array.from(root.querySelectorAll('p, h1, h2, h3, h4, h5, h6, li'))
  const parts: string[] = []
  const spans: PageSpan[] = []
  let cursor = 0
  for (const block of blocks) {
    const text = normalizeText((block as HTMLElement).innerText)
    if (!text)
      continue

    parts.push(text)
    spans.push({ start_offset: cursor, end_offset: cursor + text.length, label: block.tagName.toLowerCase() })
    cursor += text.length + 1 // +1 为拼接时块间空格
  }

  if (parts.length === 0) {
    const full = normalizeText(root.innerText)
    if (!full)
      return null
    return { text: full, spans: [{ start_offset: 0, end_offset: full.length, label: 'body' }] }
  }

  return { text: parts.join(' '), spans }
}

function buildVideoContext(site: VideoSite, video: HTMLVideoElement, includeProgress = false): VideoContextPayload {
  const title = normalizeText(findVideoTitle(site))
  const channel = normalizeText(findChannelName(site))
  const url = location.href
  const videoId = extractVideoId(site, url)
  const durationSec = Number.isFinite(video.duration) ? Math.floor(video.duration) : undefined
  const currentTimeSec = includeProgress && Number.isFinite(video.currentTime) ? Math.floor(video.currentTime) : undefined
  const rect = video.getBoundingClientRect()

  return {
    site,
    url,
    title: title || normalizeText(document.title),
    channel: channel || undefined,
    videoId,
    durationSec,
    currentTimeSec,
    isPlaying: !video.paused && !video.ended,
    isMuted: video.muted,
    volume: Number.isFinite(video.volume) ? Number(video.volume.toFixed(2)) : undefined,
    playbackRate: Number.isFinite(video.playbackRate) ? Number(video.playbackRate.toFixed(2)) : undefined,
    playerSize: rect.width && rect.height ? { width: Math.round(rect.width), height: Math.round(rect.height) } : undefined,
  }
}

function findVideoTitle(site: VideoSite) {
  if (site === 'youtube') {
    return (
      document.querySelector('ytd-watch-metadata h1 yt-formatted-string')?.textContent
      || document.querySelector('h1.title yt-formatted-string')?.textContent
      || document.querySelector('h1.title')?.textContent
    )
  }

  if (site === 'bilibili') {
    return (
      document.querySelector('h1.video-title')?.textContent
      || document.querySelector('.video-title')?.textContent
      || document.querySelector('h1')?.textContent
    )
  }

  return document.querySelector('h1')?.textContent
}

function findChannelName(site: VideoSite) {
  if (site === 'youtube') {
    return (
      document.querySelector('#channel-name a')?.textContent
      || document.querySelector('ytd-channel-name a')?.textContent
      || document.querySelector('ytd-channel-name')?.textContent
    )
  }

  if (site === 'bilibili') {
    return (
      document.querySelector('.up-name')?.textContent
      || document.querySelector('.username')?.textContent
      || document.querySelector('.up-info .name')?.textContent
    )
  }

  return undefined
}

function observeTextTracks(site: VideoSite, video: HTMLVideoElement, onSubtitle: (payload: SubtitlePayload) => void) {
  const seen = new Map<string, number>()

  const handleCueChange = (track: TextTrack) => {
    const cues = Array.from(track.activeCues ?? []) as TextTrackCue[]
    for (const cue of cues) {
      const text = normalizeText((cue as VTTCue).text ?? '')
      if (!text)
        continue

      const key = `${text}:${Math.floor(cue.startTime * 1000)}`
      const now = Date.now()
      const lastSeen = seen.get(key)
      if (lastSeen && now - lastSeen < SUBTITLE_DEDUPE_WINDOW)
        continue

      seen.set(key, now)
      onSubtitle({
        site,
        url: location.href,
        title: normalizeText(findVideoTitle(site)) || undefined,
        videoId: extractVideoId(site, location.href),
        text,
        language: (track.language || track.label || undefined),
        startMs: Math.floor(cue.startTime * 1000),
        endMs: Math.floor(cue.endTime * 1000),
      })
    }
  }

  const attach = () => {
    const tracks = Array.from(video.textTracks ?? [])
    for (const track of tracks) {
      if (track.kind && !['subtitles', 'captions'].includes(track.kind))
        continue

      if (track.mode === 'disabled')
        track.mode = 'hidden'
      track.oncuechange = () => handleCueChange(track)
    }
  }

  attach()

  const observer = new MutationObserver(() => attach())
  observer.observe(video, { attributes: true, childList: true, subtree: true })

  return () => observer.disconnect()
}

function observeSubtitleDom(site: VideoSite, onSubtitle: (payload: SubtitlePayload) => void) {
  let selector = ''
  if (site === 'youtube')
    selector = '.caption-window .caption-window-text, .ytp-caption-segment'
  if (site === 'bilibili')
    selector = '.bpx-player-subtitle-panel-text, .bpx-player-subtitle-text'

  if (!selector)
    return () => {}

  let lastText = ''

  const read = () => {
    const nodes = Array.from(document.querySelectorAll(selector))
    const text = normalizeText(nodes.map(node => node.textContent).join(' '))
    if (!text || text === lastText)
      return

    lastText = text
    onSubtitle({
      site,
      url: location.href,
      title: normalizeText(findVideoTitle(site)) || undefined,
      videoId: extractVideoId(site, location.href),
      text,
    })
  }

  const observer = new MutationObserver(read)
  observer.observe(document.documentElement, { childList: true, subtree: true })

  const interval = window.setInterval(read, 1200)

  return () => {
    observer.disconnect()
    window.clearInterval(interval)
  }
}

function captureVisionFrame(site: VideoSite, video: HTMLVideoElement): VisionFramePayload | null {
  const canvas = document.createElement('canvas')
  const width = Math.min(480, Math.max(1, Math.floor(video.videoWidth)))
  const height = Math.min(270, Math.max(1, Math.floor(video.videoHeight)))

  if (!width || !height)
    return null

  canvas.width = width
  canvas.height = height

  const ctx = canvas.getContext('2d')
  if (!ctx)
    return null

  try {
    ctx.drawImage(video, 0, 0, width, height)
    return {
      site,
      url: location.href,
      videoId: extractVideoId(site, location.href),
      title: normalizeText(findVideoTitle(site)) || undefined,
      capturedAt: Date.now(),
      width,
      height,
      dataUrl: canvas.toDataURL('image/jpeg', 0.6),
    }
  }
  catch {
    return null
  }
}

function observeVideo(site: VideoSite) {
  let video: HTMLVideoElement | null = null
  let stopTracks: (() => void) | null = null
  let stopDomSubtitles: (() => void) | null = null
  let listenersAttached = false

  const sendVideo = (includeProgress: boolean) => {
    if (!video)
      return

    safeSend({ type: 'content:video', payload: buildVideoContext(site, video, includeProgress) })
  }

  const sendPage = () => {
    safeSend({ type: 'content:page', payload: buildPageContext(site) })
  }

  const onPlayback = () => sendVideo(true)

  const attach = () => {
    const found = document.querySelector('video') as HTMLVideoElement | null
    if (!found || found === video)
      return

    if (video && listenersAttached) {
      video.removeEventListener('play', onPlayback)
      video.removeEventListener('pause', onPlayback)
      video.removeEventListener('loadedmetadata', onPlayback)
      listenersAttached = false
    }

    video = found
    stopTracks?.()
    stopDomSubtitles?.()

    stopTracks = observeTextTracks(site, video, payload => safeSend({ type: 'content:subtitle', payload }))
    stopDomSubtitles = observeSubtitleDom(site, payload => safeSend({ type: 'content:subtitle', payload }))

    sendPage()
    sendVideo(false)
  }

  const interval = window.setInterval(attach, 1000)

  const progressInterval = window.setInterval(() => {
    if (!video)
      return
    sendVideo(true)
  }, VIDEO_PROGRESS_INTERVAL)

  const titleInterval = window.setInterval(() => {
    sendPage()
    sendVideo(false)
  }, TITLE_POLL_INTERVAL)

  const cleanup = () => {
    window.clearInterval(interval)
    window.clearInterval(progressInterval)
    window.clearInterval(titleInterval)
    if (video) {
      video.removeEventListener('play', onPlayback)
      video.removeEventListener('pause', onPlayback)
      video.removeEventListener('loadedmetadata', onPlayback)
      listenersAttached = false
    }
    stopTracks?.()
    stopDomSubtitles?.()
  }

  const attachListeners = () => {
    if (!video)
      return
    if (listenersAttached)
      return

    video.addEventListener('play', onPlayback)
    video.addEventListener('pause', onPlayback)
    video.addEventListener('loadedmetadata', onPlayback)
    listenersAttached = true
  }

  const observer = new MutationObserver(() => {
    attach()
    attachListeners()
  })

  observer.observe(document.documentElement, { childList: true, subtree: true })

  attach()
  attachListeners()

  return () => {
    cleanup()
    observer.disconnect()
  }
}

/**
 * 报告 P2-4：把 DOM 节点 + 偏移映射到相对 `document.body` 文本的字符偏移。
 * 用 `Range` 从 body 起点 setEnd 到目标点，`range.toString().length` 即字符数——
 * 对文本节点与元素节点的子索引偏移都稳健。返回的是"定位锚"，权威内容仍是 `selected_text`。
 */
function offsetWithin(root: Node, container: Node, offset: number): number {
  try {
    const range = document.createRange()
    range.setStart(root, 0)
    range.setEnd(container, offset)
    return range.toString().length
  }
  catch {
    return 0
  }
}

/** 报告 P2-4：`window.getSelection()` 采集用户选区，带 start/end 定位锚。 */
function buildSelectionPayload(site: VideoSite): SelectionPayload | null {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || sel.rangeCount === 0)
    return null

  const selectedText = sel.toString()
  if (!selectedText.trim())
    return null

  const range = sel.getRangeAt(0)
  const start = offsetWithin(document.body, range.startContainer, range.startOffset)
  const end = offsetWithin(document.body, range.endContainer, range.endOffset)

  return {
    site,
    url: location.href,
    selected_text: selectedText,
    start_offset: Math.min(start, end),
    end_offset: Math.max(start, end),
  }
}

export function startContentObserver() {
  const site = detectSiteFromUrl(location.href)
  safeSend({ type: 'content:page', payload: buildPageContext(site) })
  const stopVideo = observeVideo(site)

  browser.runtime.onMessage.addListener((message: BackgroundToContentMessage) => {
    if (message.type === 'background:request-vision-frame') {
      const video = document.querySelector('video') as HTMLVideoElement | null
      if (!video)
        return

      const frame = captureVisionFrame(site, video)
      if (frame)
        safeSend({ type: 'content:vision:frame', payload: frame })
    }
  })

  // 报告 P2-4：监听选区变化（防抖），有非空选区则采集并上报。
  let selectionTimer: number | undefined
  const onSelectionChange = () => {
    if (selectionTimer !== undefined)
      window.clearTimeout(selectionTimer)
    selectionTimer = window.setTimeout(() => {
      const selection = buildSelectionPayload(site)
      if (selection)
        safeSend({ type: 'content:selection', payload: selection })
    }, SELECTION_DEBOUNCE_MS)
  }
  document.addEventListener('selectionchange', onSelectionChange)

  return () => {
    stopVideo?.()
    document.removeEventListener('selectionchange', onSelectionChange)
    if (selectionTimer !== undefined)
      window.clearTimeout(selectionTimer)
  }
}
