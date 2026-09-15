/**
 * WebGL capability detection.
 *
 * The avatar renderers (VRM / MMD) need WebGL. Without an explicit check an
 * unsupported browser fails somewhere inside three.js and the user is left with
 * a blank stage and no explanation — which is the failure mode this module
 * exists to prevent.
 *
 * The canvas factory is injectable so the detection can be tested without a
 * real browser.
 */

export type WebGLUnsupportedReason
  = | 'no-canvas'
    | 'no-webgl'
    | 'context-creation-failed'
    | 'context-lost'

export interface WebGLSupport {
  supported: boolean
  reason?: WebGLUnsupportedReason
  /** Human-readable Chinese explanation, ready to show to the user. */
  message?: string
  /** `WEBGL_debug_renderer_info` value, when the browser exposes it. */
  renderer?: string
}

const MESSAGES: Record<WebGLUnsupportedReason, string> = {
  'no-canvas': '当前环境不支持创建画布（canvas），无法渲染 3D 模型。',
  'no-webgl': '当前浏览器不支持 WebGL，无法渲染 3D 模型。请更新浏览器或启用硬件加速后重试。',
  'context-creation-failed': 'WebGL 上下文创建失败，可能是显卡驱动或硬件加速被禁用。无法渲染 3D 模型。',
  'context-lost': 'WebGL 上下文已丢失（通常是显卡驱动重置或显存不足）。请刷新页面后重试。',
}

export function createWebGLCanvas(): HTMLCanvasElement | null {
  if (typeof document === 'undefined')
    return null
  try {
    return document.createElement('canvas')
  }
  catch {
    return null
  }
}

/**
 * Probe for WebGL support.
 *
 * Tries WebGL 2 first and falls back to WebGL 1, because three.js prefers 2 but
 * still runs on 1.
 */
export function detectWebGLSupport(canvasFactory: () => HTMLCanvasElement | null = createWebGLCanvas): WebGLSupport {
  const canvas = canvasFactory()
  if (!canvas)
    return { supported: false, reason: 'no-canvas', message: MESSAGES['no-canvas'] }

  const gl = (canvas.getContext('webgl2') ?? canvas.getContext('webgl')) as WebGLRenderingContext | null
  if (!gl) {
    return { supported: false, reason: 'no-webgl', message: MESSAGES['no-webgl'] }
  }

  // `isContextLost()` can already be true on a freshly created context when the
  // GPU process is unavailable, so check it before declaring success.
  if (typeof gl.isContextLost === 'function' && gl.isContextLost()) {
    return { supported: false, reason: 'context-lost', message: MESSAGES['context-lost'] }
  }

  // The renderer name is a nice-to-have for diagnostics. A context that does
  // not expose `getExtension` (or that throws from it) is still perfectly
  // usable, so this must never be the reason detection fails.
  let renderer: string | undefined
  try {
    const debugInfo = typeof gl.getExtension === 'function'
      ? gl.getExtension('WEBGL_debug_renderer_info')
      : null
    if (debugInfo) {
      const value = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
      if (typeof value === 'string')
        renderer = value
    }
  }
  catch {
    // Diagnostics only — ignore.
  }

  return { supported: true, renderer }
}

/** Convert an unsupported result into a message safe to show directly. */
export function describeWebGLSupport(support: WebGLSupport): string {
  if (support.supported)
    return ''
  return support.message ?? MESSAGES[support.reason ?? 'no-webgl']
}
