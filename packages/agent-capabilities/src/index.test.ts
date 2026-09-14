import type { LearningLLM } from '@proj-aijade/agent-continuous-learning'
import type { SkillForge } from '@proj-aijade/agent-skill-forge'
import type { ChatOrchestratorRuntime, ChatOrchestratorRuntimeDeps } from '@proj-aijade/core-agent'

import { createSkillForge, defineSkill } from '@proj-aijade/agent-skill-forge'
import { ContextUpdateStrategy } from '@proj-aijade/server-sdk'
import { describe, expect, it } from 'vitest'

import { createAgentCapabilitiesBridge } from './index'

function fakeLLM(): LearningLLM {
  return {
    async complete() {
      return { id: 'x', model: 'fake', text: 'ok', finishReason: 'stop', usage: null, raw: {} }
    },
    async jsonComplete<T>() {
      return {} as T
    },
  }
}

describe('agent capabilities bridge', () => {
  it('injects persona + skill-index context and supplements the system prompt', () => {
    const forge: SkillForge = createSkillForge({ llm: fakeLLM() })
    forge.registry.add(defineSkill({
      frontmatter: { name: 'open-notepad', description: 'Open the notepad app.' },
      body: { title: 'Open Notepad', whenToUse: ['edit text'], procedure: ['focus notepad'] },
    }))

    const bridge = createAgentCapabilitiesBridge({ llm: fakeLLM(), skillForge: forge, autoCreateSkills: false })

    const fakeDeps = {
      runtimeContextProviders: [],
      getSystemPromptSupplement: () => 'base supplement',
    } as unknown as ChatOrchestratorRuntimeDeps

    const wrapped = bridge.wrapDeps(fakeDeps)

    const provider = wrapped.runtimeContextProviders?.at(-1)
    expect(provider).toBeTypeOf('function')
    const ctx = provider!()
    expect(ctx).not.toBeNull()
    expect(ctx!.strategy).toBe(ContextUpdateStrategy.ReplaceSelf)
    expect(ctx!.text).toContain('Persona')
    expect(ctx!.text).toContain('open-notepad')

    const supplement = wrapped.getSystemPromptSupplement!()
    expect(supplement).toContain('base supplement')
    expect(supplement).toContain('open-notepad')
  })

  it('registers a per-turn persona drift hook', () => {
    const bridge = createAgentCapabilitiesBridge({ llm: fakeLLM(), autoCreateSkills: false })
    let captured: (() => void) | null = null
    const fakeRuntime = {
      hooks: { onChatTurnComplete: (cb: () => void) => { captured = cb } },
    } as unknown as ChatOrchestratorRuntime

    bridge.registerHooks(fakeRuntime)
    expect(captured).toBeTypeOf('function')
    expect(() => captured!()).not.toThrow()
  })
})
