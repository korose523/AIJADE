import { describe, expect, it } from 'vitest'

import { describeWebGLSupport, detectWebGLSupport } from './webgl-support'

/**
 * The canvas factory is injected so each branch can be exercised without a real
 * GPU. These are the branches the UI relies on to explain *why* an avatar did
 * not render instead of showing a blank stage.
 */
function fakeCanvas(contexts: Record<string, unknown>): () => HTMLCanvasElement {
  return () => ({
    getContext: (type: string) => contexts[type] ?? null,
  }) as unknown as HTMLCanvasElement
}

describe('detectWebGLSupport', () => {
  it('reports unsupported when no canvas can be created', () => {
    const result = detectWebGLSupport(() => null)

    expect(result.supported).toBe(false)
    expect(result.reason).toBe('no-canvas')
    expect(result.message).toContain('不支持创建画布')
  })

  it('reports unsupported when neither WebGL 2 nor WebGL 1 is available', () => {
    const result = detectWebGLSupport(fakeCanvas({}))

    expect(result.supported).toBe(false)
    expect(result.reason).toBe('no-webgl')
    expect(result.message).toContain('不支持 WebGL')
  })

  it('accepts a WebGL 1 fallback when WebGL 2 is missing', () => {
    const result = detectWebGLSupport(fakeCanvas({ webgl: { isContextLost: () => false } }))

    expect(result.supported).toBe(true)
  })

  it('reports a lost context rather than pretending it works', () => {
    const result = detectWebGLSupport(fakeCanvas({
      webgl2: { isContextLost: () => true },
    }))

    expect(result.supported).toBe(false)
    expect(result.reason).toBe('context-lost')
    expect(result.message).toContain('上下文已丢失')
  })

  it('surfaces the renderer name when the debug extension is present', () => {
    const result = detectWebGLSupport(fakeCanvas({
      webgl2: {
        isContextLost: () => false,
        getExtension: () => ({ UNMASKED_RENDERER_WEBGL: 1 }),
        getParameter: () => 'Apple M3 Pro',
      },
    }))

    expect(result.supported).toBe(true)
    expect(result.renderer).toBe('Apple M3 Pro')
  })

  it('tolerates a context that exposes no debug extension', () => {
    const result = detectWebGLSupport(fakeCanvas({
      webgl2: { isContextLost: () => false, getExtension: () => null },
    }))

    expect(result.supported).toBe(true)
    expect(result.renderer).toBeUndefined()
  })
})

describe('describeWebGLSupport', () => {
  it('returns an empty string when WebGL is available', () => {
    expect(describeWebGLSupport({ supported: true })).toBe('')
  })

  it('always returns a non-empty Chinese message when it is not', () => {
    const message = describeWebGLSupport({ supported: false, reason: 'no-webgl' })

    expect(message.length).toBeGreaterThan(0)
    expect(message).toContain('WebGL')
  })
})
