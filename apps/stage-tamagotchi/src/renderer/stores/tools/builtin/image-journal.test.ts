import { resolveArtistryConfigFromStore } from '@proj-aijade/stage-ui/stores/modules/artistry'
import { describe, expect, it, vi } from 'vitest'

import { installStrictToolSchemaMatchers } from '../testing/strict-tool-schema'

installStrictToolSchemaMatchers()

describe('image_journal config snapshot', () => {
  it('uses required nullable fields for strict provider schemas', async () => {
    const mockLocation = {
      origin: 'http://localhost',
      hash: '',
      search: '',
      pathname: '/',
      href: 'http://localhost/',
    }
    vi.stubGlobal('window', {
      location: mockLocation,
    })
    vi.stubGlobal('location', mockLocation)

    const { imageJournalTools } = await import('./image-journal')
    const tools = await imageJournalTools()

    expect(tools).toSatisfyStrictToolSchemas()
    // 预算放宽到 60s：本用例通过 `await import('./image-journal')` 动态加载
    // ComfyUI/Replicate 等 provider 的完整模块图，单跑约 6s；但在全量并行
    // （178 个测试文件同时调度）下 Vite 冷转换 + CPU 争用会把它推到 15s 以上，
    // 曾因此出现非逻辑性的超时抖动。60s 只放宽等待预算，不改变断言语义。
  }, 60_000)

  it('extracts plain values instead of leaking Ref objects', () => {
    const config = resolveArtistryConfigFromStore({
      activeProvider: { value: 'comfyui' },
      activeModel: { value: 'flux' },
      defaultPromptPrefix: { value: 'anime style' },
      providerOptions: { value: { seed: 42 } },
      comfyuiServerUrl: { value: 'http://localhost:8188' },
      comfyuiSavedWorkflows: { value: [{ id: 'wf-1' }] },
      comfyuiActiveWorkflow: { value: 'wf-1' },
      replicateApiKey: { value: 'r8_xxx' },
      replicateDefaultModel: { value: 'black-forest-labs/flux-schnell' },
      replicateAspectRatio: { value: '16:9' },
      replicateInferenceSteps: { value: 4 },
      nanobananaApiKey: { value: 'AIza-test' },
      nanobananaModel: { value: 'gemini-3.1-flash-image-preview' },
      nanobananaResolution: { value: '1K' },
    })

    expect(config).toEqual({
      provider: 'comfyui',
      model: 'flux',
      promptPrefix: 'anime style',
      options: { seed: 42 },
      globals: {
        comfyuiServerUrl: 'http://localhost:8188',
        comfyuiSavedWorkflows: [{ id: 'wf-1' }],
        comfyuiActiveWorkflow: 'wf-1',
        replicateApiKey: 'r8_xxx',
        replicateDefaultModel: 'black-forest-labs/flux-schnell',
        replicateAspectRatio: '16:9',
        replicateInferenceSteps: 4,
        nanobananaApiKey: 'AIza-test',
        nanobananaModel: 'gemini-3.1-flash-image-preview',
        nanobananaResolution: '1K',
      },
    })
  })
})
