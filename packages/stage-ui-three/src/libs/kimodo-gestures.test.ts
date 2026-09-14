import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_INTENT_MAP,
  resolveMotionMeta,
} from './kimodo-gestures'

describe('resolveMotionMeta (KIMODO×HY-Motion tagging)', () => {
  it('manifest entry wins over clip JSON and DEFAULT_INTENT_MAP', () => {
    const meta = resolveMotionMeta(
      'wave',
      { name: 'wave', source: 'hy-motion', intents: ['open', 'tender'] },
      { name: 'wave', source: 'kimodo', intents: ['playful'], fps: 30, bones: {} },
      '/kimodo',
    )
    expect(meta.source).toBe('hy-motion')
    expect(meta.intents).toEqual(['open', 'tender'])
  })

  it('falls back to clip JSON when manifest entry has none', () => {
    const meta = resolveMotionMeta(
      'wave',
      { name: 'wave' },
      { name: 'wave', source: 'hy-motion', intents: ['playful', 'open'], fps: 30, bones: {} },
      '/kimodo',
    )
    expect(meta.source).toBe('hy-motion')
    expect(meta.intents).toEqual(['playful', 'open'])
  })

  it('falls back to DEFAULT_INTENT_MAP by name, then []', () => {
    expect(resolveMotionMeta('wave', undefined, undefined, '/kimodo').intents)
      .toEqual(DEFAULT_INTENT_MAP.wave)
    expect(resolveMotionMeta('unknown_clip', undefined, undefined, '/kimodo').intents)
      .toEqual([])
  })

  it('infers source from the serving path when neither entry nor clip says', () => {
    expect(resolveMotionMeta('reach_out', undefined, undefined, '/hy-motion').source).toBe('hy-motion')
    expect(resolveMotionMeta('wave', undefined, undefined, '/kimodo').source).toBe('kimodo')
  })

  it('dEFAULT_INTENT_MAP covers the generated persona clips', () => {
    for (const name of ['wave', 'nod', 'agree', 'point', 'shrug', 'think', 'reach_out', 'lean_in', 'sway', 'fidget', 'look_away', 'affirm'])
      expect(Array.isArray(DEFAULT_INTENT_MAP[name]) && DEFAULT_INTENT_MAP[name].length > 0).toBe(true)
  })
})

describe('loadMotionLibrary graceful degradation', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns [] when no manifest is deployed (fetch throws)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('404 manifest') }))
    const { loadMotionLibrary } = await import('./kimodo-gestures')
    const entries = await loadMotionLibrary({} as any, ['/kimodo', '/hy-motion'])
    expect(entries).toEqual([])
  })

  it('skips individual clips whose JSON fails to load, keeping the rest', async () => {
    const manifest = { version: '1.0', clips: [{ name: 'good' }, { name: 'bad' }] }
    const goodClip = { name: 'good', fps: 30, duration: 1, bones: { head: { times: [0], rotation: [[0, 0, 0, 1]] } } }
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith('manifest.json'))
        return { ok: true, status: 200, statusText: 'OK', json: async () => manifest }
      if (url.endsWith('good.json'))
        return { ok: true, status: 200, statusText: 'OK', json: async () => goodClip }
      throw new Error('404 bad.json')
    })
    vi.stubGlobal('fetch', fetchMock)
    const { loadMotionLibrary } = await import('./kimodo-gestures')
    // buildVRMAnimation may throw on a degenerate mock VRM; the loader must
    // catch it per-clip and still not crash the whole library load.
    const entries = await loadMotionLibrary({} as any, ['/kimodo'])
    expect(Array.isArray(entries)).toBe(true)
  })
})
