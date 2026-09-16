import type { Card, ccv3 } from '@proj-aijade/ccc'

import { useLocalStorageManualReset } from '@proj-aijade/stage-shared/composables'
import { watchDebounced } from '@vueuse/core'
import { nanoid } from 'nanoid'
import { defineStore, storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { buildDefaultAijadeCard } from '../../constants/aijade-character'
import SystemPromptV2 from '../../constants/prompts/system-v2'

import { DEFAULT_ARTISTRY_WIDGET_SPAWNING_PROMPT } from '../../constants/prompts/character-defaults'
import type { ExpressionCueId } from '../../constants/expression-grammar'
import type { PersonalityLpm } from '../../constants/personality-lpm'
import { capturePosthogEvent } from '../analytics/posthog'
import { useSettingsStageModel } from '../settings/stage-model'
import { useArtistryStore } from './artistry'
import { useConsciousnessStore } from './consciousness'
import { useSpeechStore } from './speech'

export interface AijadeExtension {
  modules: {
    consciousness: {
      provider: string // Example: "openai"
      model: string // Example: "gpt-4o"
    }

    speech: {
      provider: string // Example: "elevenlabs"
      model: string // Example: "eleven_multilingual_v2"
      voice_id: string // Example: "alloy"

      pitch?: number
      rate?: number
      ssml?: boolean
      language?: string
    }

    vrm?: {
      source?: 'file' | 'url'
      file?: string // Example: "vrm/model.vrm"
      url?: string // Example: "https://example.com/vrm/model.vrm"
    }

    live2d?: {
      source?: 'file' | 'url'
      file?: string // Example: "live2d/model.json"
      url?: string // Example: "https://example.com/live2d/model.json"
    }

    // MMD renderer is already wired; mirror `vrm?`/`live2d?` so the card can carry
    // an MMD source too (this closes a consistency gap — the slot was missing).
    mmd?: {
      source?: 'file' | 'url'
      file?: string // Example: "mmd/model.pmx"
      url?: string // Example: "https://example.com/mmd/model.pmx"
    }

    // ID from display-models store (e.g. 'preset-live2d-1', 'display-model-<nanoid>')
    displayModelId?: string
    activeBackgroundId?: string

    // 超人格 LPM（设计稿产物，见 ../../constants/personality-lpm）。
    personality?: PersonalityLpm
    // 启用的表情线索 id 列表（设计稿产物，见 ../../constants/expression-grammar）。
    expressionGrammar?: ExpressionCueId[]

    artistry?: {
      enabled?: boolean
      provider?: string
      model?: string
      promptPrefix?: string
      workflowId?: string
      widgetInstruction?: string
      spawnMode?: 'bg' | 'widget' | 'inline' | 'bg_widget'
      options?: Record<string, any>
      autonomousEnabled?: boolean
      autonomousThreshold?: number
      autonomousTarget?: 'user' | 'assistant'
    }
  }

  agents: {
    [key: string]: { // example: minecraft
      prompt: string
      enabled?: boolean
    }
  }
}

export interface AijadeCard extends Card {
  extensions: {
    aijade: AijadeExtension
  } & Card['extensions']
}

/**
 * 把任意卡片解析为 AIJADE 扩展。模块级纯函数（仅依赖传入的 `defaults`，不读
 * store 状态），便于单元测试与回放。
 *
 * 关键：modules 是**逐字段重建**的——新增字段（vrm/live2d/mmd/personality/
 * expressionGrammar…）必须在此原样透传（缺失即 `undefined`，不发明默认值），
 * 否则会在 `watchDebounced(activeCard, ...)` 触发时被静默丢弃。
 */
export interface AijadeExtensionResolveDefaults {
  consciousness: { provider: string, model: string }
  speech: { provider: string, model: string, voice_id: string }
  displayModelId: string
  artistry: {
    enabled?: boolean
    provider?: string
    model?: string
    promptPrefix?: string
    widgetInstruction?: string
    spawnMode?: 'bg' | 'widget' | 'inline' | 'bg_widget'
    options?: Record<string, any>
    autonomousEnabled?: boolean
    autonomousThreshold?: number
    autonomousTarget?: 'user' | 'assistant'
  }
}

export function resolveAijadeExtension(
  card: Card | ccv3.CharacterCardV3,
  defaults: AijadeExtensionResolveDefaults,
): AijadeExtension {
  // Get existing extension if available
  const existingExtension = ('data' in card
    ? card.data?.extensions?.aijade
    : card.extensions?.aijade) as AijadeExtension

  // Create default modules config
  const defaultModules = {
    consciousness: {
      provider: defaults.consciousness.provider,
      model: defaults.consciousness.model,
    },
    speech: {
      provider: defaults.speech.provider,
      model: defaults.speech.model,
      voice_id: defaults.speech.voice_id,
    },
    displayModelId: defaults.displayModelId,
    artistry: {
      enabled: defaults.artistry.enabled ?? false,
      provider: defaults.artistry.provider,
      model: defaults.artistry.model,
      promptPrefix: defaults.artistry.promptPrefix,
      widgetInstruction: defaults.artistry.widgetInstruction ?? DEFAULT_ARTISTRY_WIDGET_SPAWNING_PROMPT,
      spawnMode: defaults.artistry.spawnMode ?? 'bg_widget',
      options: defaults.artistry.options,
      autonomousEnabled: defaults.artistry.autonomousEnabled ?? false,
      autonomousThreshold: defaults.artistry.autonomousThreshold ?? 70,
      autonomousTarget: defaults.artistry.autonomousTarget ?? 'assistant',
    },
  } as const

  // Return default if no extension exists
  if (!existingExtension) {
    return {
      modules: defaultModules,
      agents: {},
    }
  }

  // Merge existing extension with defaults
  return {
    modules: {
      consciousness: {
        provider: existingExtension.modules?.consciousness?.provider ?? defaultModules.consciousness.provider,
        model: existingExtension.modules?.consciousness?.model ?? defaultModules.consciousness.model,
      },
      speech: {
        provider: existingExtension.modules?.speech?.provider ?? defaultModules.speech.provider,
        model: existingExtension.modules?.speech?.model ?? defaultModules.speech.model,
        voice_id: existingExtension.modules?.speech?.voice_id ?? defaultModules.speech.voice_id,
        pitch: existingExtension.modules?.speech?.pitch,
        rate: existingExtension.modules?.speech?.rate,
        ssml: existingExtension.modules?.speech?.ssml,
        language: existingExtension.modules?.speech?.language,
      },
      vrm: existingExtension.modules?.vrm,
      live2d: existingExtension.modules?.live2d,
      mmd: existingExtension.modules?.mmd,
      displayModelId: existingExtension.modules?.displayModelId ?? defaultModules.displayModelId,
      activeBackgroundId: existingExtension.modules?.activeBackgroundId,
      personality: existingExtension.modules?.personality,
      expressionGrammar: existingExtension.modules?.expressionGrammar,
      artistry: {
        enabled: existingExtension.modules?.artistry?.enabled ?? (existingExtension as any).artistry?.enabled ?? defaultModules.artistry.enabled,
        provider: existingExtension.modules?.artistry?.provider ?? (existingExtension as any).artistry?.provider ?? defaultModules.artistry.provider,
        model: existingExtension.modules?.artistry?.model ?? (existingExtension as any).artistry?.model ?? defaultModules.artistry.model,
        promptPrefix: existingExtension.modules?.artistry?.promptPrefix ?? (existingExtension as any).artistry?.promptPrefix ?? (existingExtension as any).artistry?.prompt_prefix ?? defaultModules.artistry.promptPrefix,
        workflowId: existingExtension.modules?.artistry?.workflowId ?? (existingExtension as any).artistry?.workflowId ?? (existingExtension as any).artistry?.remixId,
        widgetInstruction: existingExtension.modules?.artistry?.widgetInstruction ?? (existingExtension as any).artistry?.widgetInstruction ?? defaultModules.artistry.widgetInstruction,
        spawnMode: existingExtension.modules?.artistry?.spawnMode ?? (existingExtension as any).artistry?.spawnMode ?? defaultModules.artistry.spawnMode,
        options: existingExtension.modules?.artistry?.options ?? (existingExtension as any).artistry?.options ?? defaultModules.artistry.options,
        autonomousEnabled: existingExtension.modules?.artistry?.autonomousEnabled ?? (existingExtension as any).artistry?.autonomousEnabled ?? defaultModules.artistry.autonomousEnabled,
        autonomousThreshold: existingExtension.modules?.artistry?.autonomousThreshold ?? (existingExtension as any).artistry?.autonomousThreshold ?? defaultModules.artistry.autonomousThreshold,
        autonomousTarget: existingExtension.modules?.artistry?.autonomousTarget ?? (existingExtension as any).artistry?.autonomousTarget ?? defaultModules.artistry.autonomousTarget,
      },
    },
    agents: existingExtension.agents ?? {},
  }
}

export const useAijadeCardStore = defineStore('aijade-card', () => {
  const { t } = useI18n()

  const cards = useLocalStorageManualReset<Map<string, AijadeCard>>('aijade-cards', new Map())
  const activeCardId = useLocalStorageManualReset<string>('aijade-card-active-id', 'default')

  const activeCard = computed(() => cards.value.get(activeCardId.value))

  const consciousnessStore = useConsciousnessStore()
  const speechStore = useSpeechStore()
  const artistryStore = useArtistryStore()
  const stageModelStore = useSettingsStageModel()

  const {
    activeProvider: activeConsciousnessProvider,
    activeModel: activeConsciousnessModel,
  } = storeToRefs(consciousnessStore)

  const {
    activeSpeechProvider,
    activeSpeechVoiceId,
    activeSpeechModel,
  } = storeToRefs(speechStore)

  const addCard = (card: AijadeCard | Card | ccv3.CharacterCardV3) => {
    const newCardId = nanoid()
    cards.value.set(newCardId, newAijadeCard(card))
    return newCardId
  }

  const removeCard = (id: string) => {
    cards.value.delete(id)
    capturePosthogEvent('character_deleted', { character_id: id })
  }

  const updateCard = (id: string, updates: AijadeCard | Card | ccv3.CharacterCardV3) => {
    const existingCard = cards.value.get(id)
    if (!existingCard)
      return false

    const updatedCard = {
      ...existingCard,
      ...updates,
    }

    cards.value.set(id, newAijadeCard(updatedCard))
    return true
  }

  const getCard = (id: string) => {
    return cards.value.get(id)
  }

  function updateActiveCardDisplayModel(displayModelId: string | undefined) {
    const cardId = activeCardId.value
    const card = cards.value.get(cardId)
    if (!card)
      return false

    const extension = resolveAijadeExtension(card, buildDefaults())
    const modules: AijadeExtension['modules'] = {
      ...extension.modules,
      displayModelId,
    }

    cards.value.set(cardId, {
      ...card,
      extensions: {
        ...card.extensions,
        aijade: {
          ...extension,
          modules,
        },
      },
    })

    return true
  }

  /**
   * 收集当前 store 状态作为解析默认值。把"store 状态"与模块级纯函数
   * {@link resolveAijadeExtension} 解耦，便于测试在不实例化完整 store 的情况下
   * 验证 modules 的往返透传。
   */
  function buildDefaults(): AijadeExtensionResolveDefaults {
    return {
      consciousness: {
        provider: activeConsciousnessProvider.value,
        model: activeConsciousnessModel.value,
      },
      speech: {
        provider: activeSpeechProvider.value,
        model: activeSpeechModel.value,
        voice_id: activeSpeechVoiceId.value,
      },
      displayModelId: stageModelStore.stageModelSelected,
      artistry: {
        enabled: false,
        provider: artistryStore.globalProvider,
        model: artistryStore.globalModel,
        promptPrefix: artistryStore.globalPromptPrefix,
        widgetInstruction: DEFAULT_ARTISTRY_WIDGET_SPAWNING_PROMPT,
        spawnMode: 'bg_widget',
        options: artistryStore.globalProviderOptions,
        autonomousEnabled: false,
        autonomousThreshold: 70,
        autonomousTarget: 'assistant',
      },
    }
  }

  function newAijadeCard(card: Card | ccv3.CharacterCardV3): AijadeCard {
    // Handle ccv3 format if needed
    if ('data' in card) {
      const ccv3Card = card as ccv3.CharacterCardV3
      return {
        name: ccv3Card.data.name,
        version: ccv3Card.data.character_version ?? '1.0.0',
        description: ccv3Card.data.description ?? '',
        creator: ccv3Card.data.creator ?? '',
        notes: ccv3Card.data.creator_notes ?? '',
        notesMultilingual: ccv3Card.data.creator_notes_multilingual,
        personality: ccv3Card.data.personality ?? '',
        scenario: ccv3Card.data.scenario ?? '',
        greetings: [
          ccv3Card.data.first_mes,
          ...(ccv3Card.data.alternate_greetings ?? []),
        ],
        greetingsGroupOnly: ccv3Card.data.group_only_greetings ?? [],
        systemPrompt: ccv3Card.data.system_prompt ?? '',
        postHistoryInstructions: ccv3Card.data.post_history_instructions ?? '',
        messageExample: ccv3Card.data.mes_example
          ? ccv3Card.data.mes_example
              .split('<START>\n')
              .filter(Boolean)
              .map(example => example.split('\n')
                .map((line) => {
                  if (line.startsWith('{{char}}:') || line.startsWith('{{user}}:'))
                    return line as `{{char}}: ${string}` | `{{user}}: ${string}`
                  throw new Error(`Invalid message example format: ${line}`)
                }))
          : [],
        tags: ccv3Card.data.tags ?? [],
        extensions: {
          aijade: resolveAijadeExtension(ccv3Card, buildDefaults()),
          ...ccv3Card.data.extensions,
        },
      }
    }

    return {
      ...card,
      extensions: {
        aijade: resolveAijadeExtension(card, buildDefaults()),
        ...card.extensions,
      },
    }
  }

  function initialize() {
    if (cards.value.has('default'))
      return
    // 保留 i18n 基底：SystemPromptV2(t('base.prompt.prefix'), t('base.prompt.suffix'))
    // 与艾娅德的系统提示**组合**而非丢弃（i18n 脚手架必须继续生效）。
    const baseSystemPrompt = SystemPromptV2(
      t('base.prompt.prefix'),
      t('base.prompt.suffix'),
    ).content
    cards.value.set('default', newAijadeCard(buildDefaultAijadeCard(baseSystemPrompt)))
    if (!activeCardId.value)
      activeCardId.value = 'default'
  }

  watchDebounced(activeCard, (newCard: AijadeCard | undefined) => {
    artistryStore.resetToGlobal()

    if (!newCard)
      return

    // TODO: Minecraft Agent, etc
    const extension = resolveAijadeExtension(newCard, buildDefaults())
    if (!extension)
      return

    activeConsciousnessProvider.value = extension?.modules?.consciousness?.provider
    activeConsciousnessModel.value = extension?.modules?.consciousness?.model

    activeSpeechProvider.value = extension?.modules?.speech?.provider
    activeSpeechModel.value = extension?.modules?.speech?.model
    activeSpeechVoiceId.value = extension?.modules?.speech?.voice_id

    // Apply body model if the card has a display model configured.
    // NOTICE: must set via store property directly (not storeToRefs .value) so Pinia's
    // proxy correctly calls the writable computed setter → stageModelSelectedState → updateStageModel().
    if (extension.modules?.displayModelId) {
      stageModelStore.stageModelSelected = extension.modules.displayModelId
    }

    if (extension.modules?.artistry) {
      if (extension.modules.artistry.provider)
        artistryStore.activeProvider = extension.modules.artistry.provider
      if (extension.modules.artistry.model)
        artistryStore.activeModel = extension.modules.artistry.model
      if (extension.modules.artistry.promptPrefix)
        artistryStore.defaultPromptPrefix = extension.modules.artistry.promptPrefix
      if (extension.modules.artistry.options)
        artistryStore.providerOptions = extension.modules.artistry.options
    }
  }, { debounce: 300, maxWait: 1000 })

  function resetState() {
    activeCardId.reset()
    cards.reset()
  }

  return {
    cards,
    activeCard,
    activeCardId,
    addCard,
    removeCard,
    updateCard,
    updateActiveCardDisplayModel,
    getCard,
    resetState,
    initialize,

    currentModels: computed(() => {
      return {
        consciousness: {
          provider: activeConsciousnessProvider.value,
          model: activeConsciousnessModel.value,
        },
        speech: {
          provider: activeSpeechProvider.value,
          model: activeSpeechModel.value,
          voice_id: activeSpeechVoiceId.value,
        },
        displayModelId: stageModelStore.stageModelSelected,
        activeBackgroundId: activeCard.value?.extensions?.aijade?.modules?.activeBackgroundId,
        personality: activeCard.value?.extensions?.aijade?.modules?.personality,
        expressionGrammar: activeCard.value?.extensions?.aijade?.modules?.expressionGrammar,
      } satisfies AijadeExtension['modules']
    }),

    systemPrompt: computed(() => {
      const card = activeCard.value
      if (!card)
        return ''

      const components = [
        card.systemPrompt,
        card.description,
        card.personality,
        card.extensions?.aijade?.modules?.artistry?.widgetInstruction,
      ].filter(Boolean)

      return components.join('\n\n')
    }),
  }
})
