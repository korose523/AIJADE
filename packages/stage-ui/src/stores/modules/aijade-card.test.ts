import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { Card } from '@proj-aijade/ccc'

import { AIJADE_EXPRESSION_GRAMMAR } from '../../constants/expression-grammar'
import { AIJADE_BUILTIN_MODULES, buildDefaultAijadeCard } from '../../constants/aijade-character'
import { useSettingsStageModel } from '../settings/stage-model'
import {
  resolveAijadeExtension,
  useAijadeCardStore,
  type AijadeExtensionResolveDefaults,
} from './aijade-card'

vi.mock('./artistry', async () => {
  const { defineStore } = await import('pinia')

  return {
    useArtistryStore: defineStore('artistry', {
      state: () => ({
        globalProvider: 'mock-artistry-provider',
        globalModel: 'mock-artistry-model',
        globalPromptPrefix: 'mock-artistry-prefix',
        globalProviderOptions: {},
        activeProvider: 'mock-artistry-provider',
        activeModel: 'mock-artistry-model',
        defaultPromptPrefix: 'mock-artistry-prefix',
        providerOptions: {},
      }),
      actions: {
        resetToGlobal() {},
      },
    }),
  }
})

vi.mock('./consciousness', async () => {
  const { defineStore } = await import('pinia')

  return {
    useConsciousnessStore: defineStore('consciousness', {
      state: () => ({
        activeProvider: 'mock-consciousness-provider',
        activeModel: 'mock-consciousness-model',
      }),
    }),
  }
})

vi.mock('./speech', async () => {
  const { defineStore } = await import('pinia')

  return {
    useSpeechStore: defineStore('speech', {
      state: () => ({
        activeSpeechProvider: 'mock-speech-provider',
        activeSpeechModel: 'mock-speech-model',
        activeSpeechVoiceId: 'mock-speech-voice',
      }),
    }),
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

/**
 * @example
 * describe('aijade-card store', () => {})
 */
describe('aijade-card store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  /**
   * @example
   * it('persists selected display model on active card', () => {})
   */
  it('persists selected display model on active card', () => {
    const stageModelStore = useSettingsStageModel()
    stageModelStore.stageModelSelected = 'preset-live2d-1'

    const cardStore = useAijadeCardStore()
    cardStore.initialize()

    const updated = cardStore.updateActiveCardDisplayModel('display-model-iru-v2')

    expect(updated).toBe(true)
    expect(cardStore.activeCard?.extensions.aijade.modules.displayModelId).toBe('display-model-iru-v2')
    expect(stageModelStore.stageModelSelected).toBe('preset-live2d-1')
  })
})

/** 测试用的解析默认值（与 store 实际默认值同形，仅用于透传逻辑验证）。 */
const dummyDefaults: AijadeExtensionResolveDefaults = {
  consciousness: { provider: 'openai', model: 'gpt-4o' },
  speech: { provider: 'elevenlabs', model: 'eleven_multilingual_v2', voice_id: 'alloy' },
  displayModelId: 'preset-live2d-1',
  artistry: { enabled: false, provider: 'x', model: 'y' },
}

describe('aijade-card · extension 往返透传', () => {
  it('含 mmd + personality + expressionGrammar 的 extension 经 resolveAijadeExtension 往返后三字段都还在', () => {
    const card = {
      name: 'test',
      version: '1.0.0',
      extensions: {
        aijade: {
          modules: {
            mmd: { source: 'url' as const, url: 'https://example.com/m.mpmx' },
            personality: {
              languageTone: 0.5,
              expressivenessBudget: 0.5,
              riskTruthfulness: 0.5,
              autonomyRespect: 0.5,
              replayability: 0.5,
              curiosityLimits: 0.5,
            },
            expressionGrammar: ['confirm_smile', 'gaze_down'] as const,
          },
        },
      },
    } as unknown as Card

    const resolved = resolveAijadeExtension(card, dummyDefaults)

    expect(resolved.modules.mmd).toEqual({ source: 'url', url: 'https://example.com/m.mpmx' })
    expect(resolved.modules.personality).toEqual({
      languageTone: 0.5,
      expressivenessBudget: 0.5,
      riskTruthfulness: 0.5,
      autonomyRespect: 0.5,
      replayability: 0.5,
      curiosityLimits: 0.5,
    })
    expect(resolved.modules.expressionGrammar).toEqual(['confirm_smile', 'gaze_down'])
  })

  it('缺失新字段时不发明默认值（回落 undefined）', () => {
    const card = { name: 'x', version: '1.0.0' } as unknown as Card
    const resolved = resolveAijadeExtension(card, dummyDefaults)
    expect(resolved.modules.mmd).toBeUndefined()
    expect(resolved.modules.personality).toBeUndefined()
    expect(resolved.modules.expressionGrammar).toBeUndefined()
  })

  it('ccv3 形状卡片也能透传 mmd / personality / expressionGrammar', () => {
    const card = {
      data: {
        name: 'v3',
        character_version: '1.0',
        extensions: {
          aijade: {
            modules: {
              mmd: { source: 'file' as const, file: 'mmd/model.pmx' },
              expressionGrammar: ['head_tilt'] as const,
            },
          },
        },
      },
    } as unknown as Card

    const resolved = resolveAijadeExtension(card, dummyDefaults)
    expect(resolved.modules.mmd).toEqual({ source: 'file', file: 'mmd/model.pmx' })
    expect(resolved.modules.expressionGrammar).toEqual(['head_tilt'])
  })

  it('内置卡引用的每个 ExpressionCueId 都真实存在于 AIJADE_EXPRESSION_GRAMMAR', () => {
    const ids = AIJADE_BUILTIN_MODULES.expressionGrammar ?? []
    expect(ids.length).toBeGreaterThan(0)
    const valid = new Set(AIJADE_EXPRESSION_GRAMMAR.map(c => c.id))
    for (const id of ids)
      expect(valid.has(id), `内置卡引用了不存在的线索 id: ${id}`).toBe(true)
  })
})

describe('aijade-card · 内置卡内容回归锁', () => {
  const card = buildDefaultAijadeCard('')

  it('systemPrompt 逐字包含 §6.3 三条表达模板原文（防改写/漏条）', () => {
    const sp = card.systemPrompt
    expect(sp).toContain('复述确认：「我听到两类信息：一类是你的感受；另一类是你观察到的情况。我们先分开处理。」')
    expect(sp).toContain('澄清提问：「如果用可验证的方式描述，你希望我更关注哪一个信号？A 还是 B？」')
    expect(sp).toContain('行动收束：「我们先做一个小实验：你给我 X 的反馈；下次我用同样结构复核。」')
  })

  it('systemPrompt 逐字包含 §13 三句主题句原文（防自造句/错引）', () => {
    const sp = card.systemPrompt
    expect(sp).toContain('「我会把你的情绪当作信号，把你的话当作证据。」')
    expect(sp).toContain('「我们不急着下结论，只做可回放的小实验。」')
    expect(sp).toContain('「陪伴不是替你选择，是陪你把选择变得更清晰。」')
  })

  it('description 不含代码侧免责声明（防治理语汇泄漏进模型提示词）', () => {
    expect(card.description).not.toMatch(/设计产物|实验证据/)
  })
})
