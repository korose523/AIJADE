import type { DisplayModel } from '../display-models'

import { createTestingPinia } from '@pinia/testing'
import { setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DisplayModelFormat } from '../display-models'
import { useSettingsStageModel } from './stage-model'

function model(format: DisplayModelFormat): DisplayModel {
  return {
    id: `test-${format}`,
    format,
    type: 'url',
    url: `https://example.invalid/model.${format}`,
    name: format,
    importedAt: 0,
  }
}

/**
 * This test pins the format → renderer routing.
 *
 * PMX/PMD were previously routed to the `'vrm'` renderer, which cannot parse
 * them, so an MMD model was selectable in the UI and then failed to render with
 * no explanation. That is the wiring bug this file is here to keep fixed.
 */
describe('store settings-stage-model', () => {
  beforeEach(() => {
    setActivePinia(createTestingPinia({ createSpy: vi.fn, stubActions: false }))
  })

  it('routes MMD formats to the mmd renderer, not the vrm one', () => {
    const store = useSettingsStageModel()

    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.PMXZip))).toBe('mmd')
    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.PMXDirectory))).toBe('mmd')
    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.PMD))).toBe('mmd')
  })

  it('keeps GLTF-based avatars on the vrm renderer', () => {
    const store = useSettingsStageModel()

    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.VRM))).toBe('vrm')
    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.GLB))).toBe('vrm')
  })

  it('leaves the other formats where they were', () => {
    const store = useSettingsStageModel()

    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.Live2dZip))).toBe('live2d')
    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.SpineZip))).toBe('spine')
    expect(store.resolveBuiltInStageModelRenderer(model(DisplayModelFormat.Inochi2d))).toBe('inochi2d')
  })

  it('disables rendering when there is no model', () => {
    const store = useSettingsStageModel()

    expect(store.resolveBuiltInStageModelRenderer(undefined)).toBe('disabled')
  })
})
