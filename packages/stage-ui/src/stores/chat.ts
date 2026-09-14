import type { ComputerUseBackend, McpComputerUseClient } from '@proj-aijade/agent-computer-use'
import type { ChatOrchestratorRuntimeDeps, ChatOrchestratorRuntimeState, ChatOrchestratorSendOptions, StreamEvent, StreamOptions } from '@proj-aijade/core-agent'
import type { PerformanceState } from '@proj-aijade/memory-pgvector/performance'
import type { ChatProvider } from '@xsai-ext/providers/utils'
import type { Message } from '@xsai/shared-chat'

import type { ChatHistoryItem } from '../types/chat'

import { createAgentCapabilitiesBridge } from '@proj-aijade/agent-capabilities'
import {

  createComputerUseCapability,
  createComputerUseMcpTransport,
  createHermesBackend,

  SAFE_ACTIONS,
} from '@proj-aijade/agent-computer-use'
// Agent capabilities: autonomous skill creation + continuous learning + computer control (Hermes-fused)
import { createOllamaClient } from '@proj-aijade/agent-llm-client'
import { createChatOrchestratorRuntime } from '@proj-aijade/core-agent'
import { createPerformanceDirector } from '@proj-aijade/memory-pgvector/performance'
import { createDefaultLayeredMemory, createLayeredMemoryPort } from '@proj-aijade/memory-pgvector/port'
import { IOAttributes, IOEvents, IOSpanNames, IOSubsystems } from '@proj-aijade/stage-shared'
import { nanoid } from 'nanoid'
import { defineStore, storeToRefs } from 'pinia'
import { onScopeDispose, ref, toRaw, watch } from 'vue'

import { useAnalytics } from '../composables'
import { activeTurnSpan, startSpan } from '../composables/use-io-tracer'
import { extractMessageText, isCloudSyncableMessage } from '../libs/chat-sync'
import { systemPromptEmotionSupplement } from '../libs/speech/speech-facade'
import { createMinecraftContext } from './chat/context-providers'
import { useChatContextStore } from './chat/context-store'
import { createMemoryBridge, createPerformanceBridge } from './chat/memory-performance'
import { useChatSessionStore } from './chat/session-store'
import { useChatStreamStore } from './chat/stream-store'
import { useContextObservabilityStore } from './devtools/context-observability'
import { useLLM } from './llm'
import { useLlmToolsetPromptsStore } from './llm-toolset-prompts'
import { getMcpToolBridge } from './mcp-tool-bridge'
import { useAijadeCardStore } from './modules/aijade-card'
import { useAutonomousArtistryStore } from './modules/artistry-autonomous'
import { useConsciousnessStore } from './modules/consciousness'

interface ForkOptions {
  fromSessionId?: string
  atIndex?: number
  reason?: string
  hidden?: boolean
}

type ProviderHistoryMessage = Exclude<ChatHistoryItem, { role: 'error' }>

function toProviderHistory(messages: ChatHistoryItem[]): Message[] {
  return messages.filter((message): message is ProviderHistoryMessage => message.role !== 'error')
}

function isTextDelta(event: StreamEvent): event is Extract<StreamEvent, { type: 'text-delta' }> {
  return event.type === 'text-delta'
}

export type { QueuedSendSnapshot, ChatOrchestratorSendOptions as SendOptions } from '@proj-aijade/core-agent'

export const useChatOrchestratorStore = defineStore('chat-orchestrator', () => {
  const llmStore = useLLM()
  const llmToolsetPromptsStore = useLlmToolsetPromptsStore()
  const consciousnessStore = useConsciousnessStore()
  const artistryAutonomousStore = useAutonomousArtistryStore()
  const { activeProvider } = storeToRefs(consciousnessStore)
  const {
    trackFirstMessage,
    trackMessageSendStarted,
    trackLlmRequestStarted,
    trackLlmFirstToken,
    trackAssistantResponseRendered,
    trackMessageRound,
  } = useAnalytics()

  const chatSession = useChatSessionStore()
  const chatStream = useChatStreamStore()
  const chatContext = useChatContextStore()
  const cardStore = useAijadeCardStore()
  const contextObservability = useContextObservabilityStore()
  const { activeSessionId } = storeToRefs(chatSession)
  const { streamingMessage } = storeToRefs(chatStream)

  const sending = ref(false)
  const pendingQueuedSendCount = ref(0)
  let ownedActiveTurnSpan: typeof activeTurnSpan.value

  async function streamWithStageAdapters(
    model: string,
    chatProvider: ChatProvider,
    messages: Message[],
    options?: StreamOptions,
  ) {
    let llmTextLength = 0

    const hadExistingTurn = !!activeTurnSpan.value
    if (!hadExistingTurn) {
      const turnSpan = startSpan(IOSpanNames.InteractionTurn)
      activeTurnSpan.value = turnSpan
      ownedActiveTurnSpan = turnSpan
    }

    const llmSpan = startSpan(IOSpanNames.LLMInference, activeTurnSpan.value, {
      [IOAttributes.Subsystem]: IOSubsystems.LLM,
      [IOAttributes.GenAIRequestModel]: model,
    })
    const llmRequestTs = performance.now()
    let llmFirstTokenEmitted = false

    try {
      await llmStore.stream(model, chatProvider, messages, {
        ...options,
        onStreamEvent: async (event: StreamEvent) => {
          if (isTextDelta(event)) {
            if (!llmFirstTokenEmitted) {
              llmFirstTokenEmitted = true
              llmSpan.addEvent(IOEvents.LLMFirstToken, {
                [IOAttributes.LLM_TTFT]: performance.now() - llmRequestTs,
              })
            }
            llmTextLength += event.text.length
          }

          await options?.onStreamEvent?.(event)
        },
      })

      llmSpan.setAttribute(IOAttributes.LLMTextLength, llmTextLength)
    }
    finally {
      llmSpan.end()
    }
  }

  function syncRuntimeState(state: ChatOrchestratorRuntimeState) {
    sending.value = state.sending
    pendingQueuedSendCount.value = state.pendingQueuedSendCount
  }

  function settleOwnedActiveTurnSpan() {
    if (!ownedActiveTurnSpan)
      return

    ownedActiveTurnSpan.end()
    if (activeTurnSpan.value === ownedActiveTurnSpan)
      activeTurnSpan.value = undefined
    ownedActiveTurnSpan = undefined
  }

  // ---- Memory + structured performance: real-time pipeline integration ----
  // Memory is recalled into the prompt (via runtimeContextProviders, the same
  // hook AIJADE's Minecraft integration uses) and every turn is persisted into the
  // layered memory engine. The performance director is driven by the
  // orchestrator's token stream and surfaced through `performanceState`.
  const memoryPort = createLayeredMemoryPort(createDefaultLayeredMemory(), { scope: 'chat' })
  const memoryBridge = createMemoryBridge(memoryPort)
  const performanceDirector = createPerformanceDirector()
  const performanceState = ref<PerformanceState>(performanceDirector.snapshot())
  const performanceBridge = createPerformanceBridge(performanceDirector, (s) => {
    performanceState.value = s
  })
  // The performance bridge owns a self-driven 100ms tick loop; tear it down with the
  // store so HMR reloads don't accumulate duplicate timers (which would double-emit).
  onScopeDispose(() => performanceBridge.stop())

  // ---- Agent capabilities: skill auto-creation + continuous learning + computer control ----
  // Uses the same bridge pattern as memory/performance. The LLM runs against the
  // local Ollama instance (already on :11434) for background skill/learning work;
  // the live chat still uses the user's configured provider. `memory` is deliberately
  // NOT forwarded here so the layered memory engine (memoryBridge) isn't double-fed.
  const capabilitiesLlm = createOllamaClient({
    baseURL: 'http://localhost:11434',
    // Must match the model installed on the local Ollama (see root .env OLLAMA_MODEL).
    // The background skill-forge / continuous-learning workers call this LLM; a
    // non-installed model name makes those calls fail with "model not found".
    model: 'qwythos-9b:Q8_0',
  })

  // Real computer-control backend, wired through the Hermes fusion seam.
  // The Electron main spawns AIJADE's `computer-use-mcp` server and the renderer
  // registers it via `setMcpToolBridge(...)`; we consume that bridge lazily so
  // the backend is real whenever the bridge is available, and falls back to a
  // safe dry-run when it isn't (e.g. headless tests).
  const realComputerUseClient: McpComputerUseClient = {
    callTool: (name, args) => getMcpToolBridge().callTool({ name, arguments: args }),
  }
  const realComputerUseBackend: ComputerUseBackend = createHermesBackend(
    createComputerUseMcpTransport(realComputerUseClient),
  )
  const computerUseBackend: ComputerUseBackend = {
    async execute(params) {
      try {
        return await realComputerUseBackend.execute(params)
      }
      catch {
        // Bridge unset or transport call failed → safe actions still "succeed"
        // as a dry-run; state-mutating actions are blocked until the bridge is up.
        const safe = SAFE_ACTIONS.has(params.action)
        return {
          ok: safe,
          safe,
          summary: safe
            ? `[dry-run fallback] ${params.action}`
            : 'blocked: computer-use backend unavailable',
        }
      }
    },
  }
  // Approval gate: read-only actions are always allowed; non-safe actions defer
  // to an app-supplied hook (e.g. a confirm dialog). The desktop pet / settings
  // UI can set `globalThis.__AIJADE_COMPUTER_USE_APPROVE__` to enable real control.
  const computerUseApprover = (params: { action: string }): boolean => {
    if (SAFE_ACTIONS.has(params.action as never))
      return true
    const hook = (globalThis as Record<string, unknown>).__AIJADE_COMPUTER_USE_APPROVE__ as
      | ((p: { action: string }) => boolean)
      | undefined
    return hook ? hook(params) : false
  }
  const computerUse = createComputerUseCapability(computerUseBackend, { approve: computerUseApprover })
  const capabilities = createAgentCapabilitiesBridge({
    llm: capabilitiesLlm,
    computerUse,
  })
  // Reactive projection of the continuous-learning persona so UI surfaces
  // (e.g. the desktop-pet mode) can show live mood / intimacy.
  const personaState = ref(capabilities.learning.getPersona())

  const baseDeps: ChatOrchestratorRuntimeDeps = {
    session: {
      ensureSession: sessionId => chatSession.ensureSession(sessionId),
      getSessionMessages: sessionId => chatSession.getSessionMessages(sessionId).map(message => toRaw(message)),
      appendSessionMessage: (sessionId, message) => chatSession.appendSessionMessage(sessionId, message),
      getSessionGeneration: sessionId => chatSession.getSessionGeneration(sessionId),
    },
    context: {
      ingest: envelope => chatContext.ingestContextMessage(envelope),
      snapshot: () => chatContext.getContextsSnapshot(),
    },
    foregroundStream: {
      patch: (message) => {
        streamingMessage.value = message
      },
      reset: () => {
        streamingMessage.value = { role: 'assistant', content: '', slices: [], tool_results: [] }
      },
    },
    llm: {
      stream: streamWithStageAdapters,
    },
    getActiveSessionId: () => activeSessionId.value,
    getActiveProvider: () => activeProvider.value,
    getSystemPromptSupplement: () => {
      const base = llmToolsetPromptsStore.activeToolsetPrompt
      return systemPromptEmotionSupplement(base)
    },
    runtimeContextProviders: [
      createMinecraftContext,
    ],
    createId: nanoid,
    unwrapMessage: message => toRaw(message),
    onStateChange: syncRuntimeState,
    onSendSettled: settleOwnedActiveTurnSpan,
    onTrackFirstMessage: trackFirstMessage,
    onMessageSendStarted: ({ source, model }) => trackMessageSendStarted({
      source,
      model,
    }),
    onLlmRequestStarted: ({ model, provider, hasVoice }) => trackLlmRequestStarted({
      model,
      provider,
      has_voice: hasVoice,
    }),
    onLlmFirstToken: ({ model, ttfbMs }) => trackLlmFirstToken({
      model,
      ttfb_ms: ttfbMs,
    }),
    onAssistantResponseRendered: ({ model, latencyMs }) => trackAssistantResponseRendered({
      model,
      latency_ms: latencyMs,
    }),
    onMessageRound: ({ durationMs, hasVoice, model }) => trackMessageRound({
      duration_ms: durationMs,
      has_voice: hasVoice,
      model,
    }),
    onLifecycle: record => contextObservability.recordLifecycle(record),
    onPromptProjection: payload => contextObservability.capturePromptProjection(payload),
    onUserMessageAppended: ({ sessionId, message, messageText }) => {
      if (isCloudSyncableMessage(message)) {
        void chatSession.pushMessageToCloud(sessionId, {
          id: message.id,
          role: 'user',
          content: messageText,
        })
      }
    },
    onAssistantMessageAppended: ({ sessionId, message }) => {
      if (isCloudSyncableMessage(message) && message.id) {
        void chatSession.pushMessageToCloud(sessionId, {
          id: message.id,
          role: 'assistant',
          content: extractMessageText(message),
        })
      }
    },
    onUserTurnReady: ({ messageText, sessionMessages }) => {
      const autonomousTarget = cardStore.activeCard?.extensions?.aijade?.modules?.artistry?.autonomousTarget || 'user'
      if (autonomousTarget === 'user')
        void artistryAutonomousStore.runArtistTask(messageText, toProviderHistory(sessionMessages))
    },
    onAssistantTurnReady: ({ messageText, sessionMessages }) => {
      const artistry = cardStore.activeCard?.extensions?.aijade?.modules?.artistry
      if (artistry?.autonomousEnabled && artistry?.autonomousTarget === 'assistant')
        void artistryAutonomousStore.runArtistTask(messageText, toProviderHistory(sessionMessages))
    },
  }

  const runtime = createChatOrchestratorRuntime(
    capabilities.wrapDeps(performanceBridge.wrapDeps(memoryBridge.wrapDeps(baseDeps))),
  )
  performanceBridge.registerHooks(runtime)
  capabilities.registerHooks(runtime)
  // Keep the reactive persona projection in sync after every completed turn.
  runtime.hooks.onChatTurnComplete(async () => {
    personaState.value = capabilities.learning.getPersona()
  })

  watch(sending, (next) => {
    if (runtime.getSending() !== next)
      runtime.setSending(next)
  })

  async function ingest(
    sendingMessage: string,
    options: ChatOrchestratorSendOptions,
    targetSessionId?: string,
  ) {
    await memoryBridge.prepareSend(sendingMessage)
    return runtime.ingest(sendingMessage, options, targetSessionId)
  }

  async function ingestOnFork(
    sendingMessage: string,
    options: ChatOrchestratorSendOptions,
    forkOptions?: ForkOptions,
  ) {
    const baseSessionId = forkOptions?.fromSessionId ?? activeSessionId.value
    if (!forkOptions)
      return ingest(sendingMessage, options, baseSessionId)

    const forkSessionId = await chatSession.forkSession({
      fromSessionId: baseSessionId,
      atIndex: forkOptions.atIndex,
      reason: forkOptions.reason,
      hidden: forkOptions.hidden,
    })
    return ingest(sendingMessage, options, forkSessionId || baseSessionId)
  }

  function cancelPendingSends(sessionId?: string) {
    runtime.cancelPendingSends(sessionId)
  }

  function getPendingQueuedSendSnapshot() {
    return runtime.getPendingQueuedSendSnapshot()
  }

  return {
    sending,
    pendingQueuedSendCount,

    ingest,
    ingestOnFork,
    cancelPendingSends,
    getPendingQueuedSendSnapshot,

    performanceState,
    /** LPM dual-stream "listen audio branch" entry — wired from the hearing pipeline (ASR emotion + mic RMS). */
    feedUserAudio: performanceBridge.feedUserAudio,

    capabilities,
    personaState,

    clearHooks: runtime.hooks.clearHooks,

    emitBeforeMessageComposedHooks: runtime.hooks.emitBeforeMessageComposedHooks,
    emitAfterMessageComposedHooks: runtime.hooks.emitAfterMessageComposedHooks,
    emitBeforeSendHooks: runtime.hooks.emitBeforeSendHooks,
    emitAfterSendHooks: runtime.hooks.emitAfterSendHooks,
    emitTokenLiteralHooks: runtime.hooks.emitTokenLiteralHooks,
    emitTokenSpecialHooks: runtime.hooks.emitTokenSpecialHooks,
    emitStreamEndHooks: runtime.hooks.emitStreamEndHooks,
    emitAssistantResponseEndHooks: runtime.hooks.emitAssistantResponseEndHooks,
    emitAssistantMessageHooks: runtime.hooks.emitAssistantMessageHooks,
    emitChatTurnCompleteHooks: runtime.hooks.emitChatTurnCompleteHooks,

    onBeforeMessageComposed: runtime.hooks.onBeforeMessageComposed,
    onAfterMessageComposed: runtime.hooks.onAfterMessageComposed,
    onBeforeSend: runtime.hooks.onBeforeSend,
    onAfterSend: runtime.hooks.onAfterSend,
    onTokenLiteral: runtime.hooks.onTokenLiteral,
    onTokenSpecial: runtime.hooks.onTokenSpecial,
    onStreamEnd: runtime.hooks.onStreamEnd,
    onAssistantResponseEnd: runtime.hooks.onAssistantResponseEnd,
    onAssistantMessage: runtime.hooks.onAssistantMessage,
    onChatTurnComplete: runtime.hooks.onChatTurnComplete,
  }
})
