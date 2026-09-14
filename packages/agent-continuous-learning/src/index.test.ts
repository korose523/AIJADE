import type { SkillForge } from '@proj-aijade/agent-skill-forge'

import type { LearningLLM } from './index'

import { createSkillRegistry, defineSkill } from '@proj-aijade/agent-skill-forge'
import { describe, expect, it } from 'vitest'

import {
  applyInteraction,
  applyIntimacy,
  createContinuousLearning,
  createDiscourseMemory,
  createIntimacyState,
  createPersonaState,
  drift,
  driftIntimacy,

  toBigFive,
  toContext,
  toMoodProfile,
  toPAD,
  toThreeForce,
} from './index'

function fakeLLM(summary = 'compressed sink sentence'): LearningLLM {
  return {
    async complete() {
      return { id: 'x', model: 'fake', text: summary, finishReason: 'stop', usage: null, raw: {} }
    },
    async jsonComplete<T>() {
      return {} as T
    },
  }
}

describe('persona', () => {
  it('keeps all dimensions in 0..1 and reacts to valence', () => {
    const s0 = createPersonaState(0.5)
    for (const v of Object.values(s0.vector))
      expect(v).toBeGreaterThanOrEqual(0), expect(v).toBeLessThanOrEqual(1)
    const positive = applyInteraction(s0, { valence: 1, arousal: 0.2 })
    expect(positive.vector.warmth).toBeGreaterThan(s0.vector.warmth)
    const drifted = drift(positive, 600_000)
    expect(drifted.vector.warmth).toBeLessThanOrEqual(positive.vector.warmth)
  })

  it('derives PAD / Big-Five / three-force / mood within bounds', () => {
    const s = createPersonaState(0.7)
    const pad = toPAD(s)
    expect(pad.pleasure).toBeGreaterThanOrEqual(0)
    expect(pad.pleasure).toBeLessThanOrEqual(1)
    expect(pad.arousal).toBeGreaterThanOrEqual(0)
    expect(pad.arousal).toBeLessThanOrEqual(1)
    const big5 = toBigFive(s.vector)
    for (const k of ['O', 'C', 'E', 'A', 'N'] as const)
      expect(big5[k]).toBeGreaterThanOrEqual(0)
    const force = toThreeForce(s)
    expect(force.natural + force.social + force.individual).toBeCloseTo(1, 5)
    const mood = toMoodProfile(s)
    expect(mood.emoji).toMatch(/\p{Emoji}/u)
    expect(mood.voiceRate).toBeGreaterThan(0.5)
  })

  it('updates intimacy on interaction and raises longing while idle', () => {
    let i = createIntimacyState()
    const before = i.longing
    i = applyIntimacy(i, { valence: 1, arousal: 0.3 })
    expect(i.warmth).toBeGreaterThan(createIntimacyState().warmth)
    expect(i.familiarity).toBeGreaterThan(createIntimacyState().familiarity)
    // Simulate a long silence: longing should creep up.
    i = driftIntimacy(i, 3_600_000)
    expect(i.longing).toBeGreaterThanOrEqual(before)
  })

  it('includes mood + intimacy in the compact context supplement', () => {
    const s = createPersonaState(0.6)
    const ctx = toContext(s)
    expect(ctx).toContain('mood=')
    expect(ctx).toContain('PAD(')
    expect(ctx).toContain('intimacy(')
  })
})

describe('discourse memory', () => {
  it('keeps recent turns and compacts overflow into sink chunks', async () => {
    const dm = createDiscourseMemory({ llm: fakeLLM(), window: 4, maxChunks: 3 })
    for (let i = 0; i < 12; i++)
      dm.ingest('user', `message number ${i}`)
    // window=4 verbatim, so 8 should have been compacted into sink chunks
    await dm.compact()
    const ctx = dm.context()
    expect(ctx).toContain('[recent discourse]')
    expect(dm.stats().recent).toBeLessThanOrEqual(4)
  })
})

describe('continuous learning + feedback-driven evolution', () => {
  it('evolves the matching skill when feedback is captured', async () => {
    const skill = defineSkill({
      frontmatter: { name: 'open-notepad', description: 'Open the notepad app.' },
      body: { title: 'Open Notepad', whenToUse: ['edit text'], procedure: ['focus notepad'] },
    })
    const forge: SkillForge = {
      registry: createSkillRegistry([skill]),
      detectTeachableMoment: async () => null,
      generateSkill: async () => skill,
      validateSkill: async () => ({ ok: true, errors: [], warnings: [], score: 1 }),
      evolveSkill: async (pkg, fb) => ({
        ...pkg,
        frontmatter: { ...pkg.frontmatter, version: '0.1.1' },
        evolutionLog: [...pkg.evolutionLog, { at: Date.now(), feedback: fb, summary: 'e', fromVersion: pkg.frontmatter.version, toVersion: '0.1.1' }],
      }),
      register: () => ({ registered: true, result: { ok: true, errors: [], warnings: [], score: 1 } }),
    }
    const learning = createContinuousLearning({ llm: fakeLLM(), skillForge: forge })
    learning.ingestTurn('user', 'please open notepad and write a note')
    await learning.captureFeedback('it should also raise the window', 'open notepad')
    const evolved = forge.registry.get('open-notepad')
    expect(evolved?.frontmatter.version).toBe('0.1.1')
    expect(evolved?.evolutionLog.length).toBe(1)
  })
})
