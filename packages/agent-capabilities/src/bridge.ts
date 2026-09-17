import type { ComputerUseCapability } from '@proj-aijade/agent-computer-use'
import type { ContinuousLearning, LearningLLM, PersonaUpdateEvent } from '@proj-aijade/agent-continuous-learning'
import type { ChatMessage } from '@proj-aijade/agent-llm-client'
import type { SkillForge } from '@proj-aijade/agent-skill-forge'
import type { ChatOrchestratorRuntime, ChatOrchestratorRuntimeDeps, ContextMessage } from '@proj-aijade/core-agent'
import type { MemoryPort } from '@proj-aijade/memory-pgvector/port'

import { createContinuousLearning, createLexiconSignalExtractor } from '@proj-aijade/agent-continuous-learning'
import { createLogger } from '@proj-aijade/agent-llm-client'
import { createSkillForge } from '@proj-aijade/agent-skill-forge'
import { ContextUpdateStrategy } from '@proj-aijade/server-sdk'
import { nanoid } from 'nanoid'

const logger = createLogger('agent-capabilities')

export interface AgentCapabilitiesOptions {
  llm: LearningLLM
  /** AIJADE's layered memory port (LPM long-term backbone). */
  memory?: MemoryPort
  /** Pre-built forge / learning (created internally when omitted). */
  skillForge?: SkillForge
  learning?: ContinuousLearning
  /** Computer-control capability (Hermes-fused). */
  computerUse?: ComputerUseCapability
  /** Runtime capability credential injected into every computer-use call. */
  capabilityToken?: string | (() => string | undefined | Promise<string | undefined>)
  /** Autonomous teachable-moment -> skill creation. Default true. */
  autoCreateSkills?: boolean
  /** Context id used for the injected `ContextMessage`. */
  contextId?: string
  /**
   * Called after every persona change. Wire this to `@proj-aijade/research-telemetry`
   * to record the longitudinal trajectory — the data backbone of the dissertation.
   */
  onPersonaUpdate?: (event: PersonaUpdateEvent) => void
}

export interface AgentCapabilitiesBridge {
  readonly skillForge: SkillForge
  readonly learning: ContinuousLearning
  readonly computerUse?: ComputerUseCapability
  /** Augment the orchestrator deps with capability providers + lifecycle hooks. */
  wrapDeps: (deps: ChatOrchestratorRuntimeDeps) => ChatOrchestratorRuntimeDeps
  /** Attach per-turn hooks (persona drift). Call after `createChatOrchestratorRuntime`. */
  registerHooks: (runtime: ChatOrchestratorRuntime) => void
}

/**
 * Fuse skill auto-creation, continuous learning and computer control into
 * AIJADE's chat pipeline — using the same extension points (runtime context
 * providers + lifecycle callbacks + hooks) as AIJADE's memory and performance
 * bridges, with no modification of the orchestrator internals.
 */
export function createAgentCapabilitiesBridge(options: AgentCapabilitiesOptions): AgentCapabilitiesBridge {
  const contextId = options.contextId ?? 'agent:capabilities'
  const autoCreate = options.autoCreateSkills ?? true

  const skillForge = options.skillForge
    ?? createSkillForge({ llm: options.llm })
  const learning = options.learning
    ?? createContinuousLearning({
      llm: options.llm,
      memory: options.memory,
      skillForge,
      // Deterministic lexicon signal keeps the interaction-driven persona path
      // live and reproducible even if a global extractor is disabled.
      signalExtractor: createLexiconSignalExtractor(),
      onPersonaUpdate: options.onPersonaUpdate,
    })
  // Keep the credential out of model-visible tool arguments while ensuring
  // every execution path receives the same runtime token.
  const computerUse = options.computerUse && options.capabilityToken !== undefined
    ? {
        ...options.computerUse,
        call: async (params: Parameters<ComputerUseCapability['call']>[0]) => {
          const token = typeof options.capabilityToken === 'function'
            ? await options.capabilityToken()
            : options.capabilityToken
          return options.computerUse!.call({ ...params, capabilityToken: token })
        },
      }
    : options.computerUse

  let creating = false
  let lastTurnTs = Date.now()

  async function maybeCreateSkill(): Promise<void> {
    if (!autoCreate || creating)
      return
    const history = learning.discourse.recentMessages()
    if (history.length < 2)
      return
    creating = true
    try {
      const draft = await skillForge.detectTeachableMoment(history as ChatMessage[])
      if (!draft)
        return
      const pkg = await skillForge.generateSkill(draft)
      const { registered } = skillForge.register(pkg)
      if (registered)
        logger.info(`auto-created skill "${pkg.frontmatter.name}" (${pkg.frontmatter.description})`)
    }
    catch (err) {
      logger.warn(`auto skill creation failed: ${(err as Error).message}`)
    }
    finally {
      creating = false
    }
  }

  function skillIndexText(): string {
    const skills = skillForge.registry.list()
    if (skills.length === 0)
      return ''
    const lines = skills.map(s => `- ${s.frontmatter.name}: ${s.frontmatter.description}`).join('\n')
    return `You have these reusable skills (invoke via the skill tools):\n${lines}`
  }

  function provider(): ContextMessage | null {
    const parts: string[] = []
    const learningCtx = learning.contextSupplement()
    if (learningCtx)
      parts.push(learningCtx)
    const idx = skillIndexText()
    if (idx)
      parts.push(idx)
    if (computerUse)
      parts.push('You can control the computer via the `computer_use` tool when the user wants to interact with desktop apps.')
    const text = parts.join('\n\n')
    if (!text.trim())
      return null
    return {
      id: nanoid(),
      contextId,
      strategy: ContextUpdateStrategy.ReplaceSelf,
      text,
      createdAt: Date.now(),
    }
  }

  function wrapDeps(deps: ChatOrchestratorRuntimeDeps): ChatOrchestratorRuntimeDeps {
    return {
      ...deps,
      runtimeContextProviders: [...(deps.runtimeContextProviders ?? []), provider],
      getSystemPromptSupplement: () => {
        const base = deps.getSystemPromptSupplement?.() ?? ''
        const idx = skillIndexText()
        const computerNote = computerUse
          ? 'You can control the computer via the `computer_use` tool when asked to interact with desktop applications.'
          : ''
        return [base, idx, computerNote].filter(Boolean).join('\n\n')
      },
      onUserMessageAppended: (event: { messageText: string }) => {
        deps.onUserMessageAppended?.(event as never)
        learning.ingestTurn('user', event.messageText)
      },
      onAssistantMessageAppended: (event: { messageText: string }) => {
        deps.onAssistantMessageAppended?.(event as never)
        learning.ingestTurn('assistant', event.messageText)
      },
      onAssistantTurnReady: (event: { messageText: string }) => {
        deps.onAssistantTurnReady?.(event as never)
        void learning.compact()
        if (autoCreate)
          void maybeCreateSkill()
      },
    }
  }

  function registerHooks(runtime: ChatOrchestratorRuntime): void {
    lastTurnTs = Date.now()
    runtime.hooks.onChatTurnComplete(async () => {
      const now = Date.now()
      const dt = now - lastTurnTs
      lastTurnTs = now
      // Persona drift between turns keeps mood from freezing.
      learning.tick(dt)
    })
  }

  return { skillForge, learning, computerUse, wrapDeps, registerHooks }
}
