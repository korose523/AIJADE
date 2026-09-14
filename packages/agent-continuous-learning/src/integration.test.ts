import type { TelemetryStorage, TurnRecord } from '@proj-aijade/research-telemetry'

import type { LearningLLM } from './index'

import { createMemoryStorage, startSession } from '@proj-aijade/research-telemetry'
import { describe, expect, it, vi } from 'vitest'

import {
  createContinuousLearning,
  createLexiconSignalExtractor,

  toPersonaSnapshot,
} from './index'

function fakeLLM(): LearningLLM {
  return {
    async complete() {
      return { id: 'x', model: 'fake', text: 'summary', finishReason: 'stop', usage: null, raw: {} }
    },
    async jsonComplete<T>() {
      return {} as T
    },
  }
}

/**
 * End-to-end check that the persona pipeline is actually live: a turn now changes
 * the persona (the bug we fixed), the change is recorded to telemetry, and the
 * dynamics parameters are sweepable.
 */
describe('continuous-learning pipeline (integration)', () => {
  it('applies interaction-driven updates and records them to telemetry', async () => {
    const storage: TelemetryStorage = createMemoryStorage()
    const session = await startSession({ sessionId: 's1', condition: 'baseline', storage })

    const records: TurnRecord[] = []
    const learning = createContinuousLearning({
      llm: fakeLLM(),
      signalExtractor: createLexiconSignalExtractor(),
      onPersonaUpdate: (event) => {
        // Push synchronously (the callback fires inline); the telemetry write is
        // best-effort and fire-and-forget.
        records.push({
          sessionId: session.sessionId,
          turnIndex: records.length,
          timestamp: event.timestamp,
          wallClock: new Date(event.timestamp).toISOString(),
          role: event.role ?? 'user',
          persona: toPersonaSnapshot(event.state),
        })
        void session.recordTurn({ role: event.role ?? 'user', persona: toPersonaSnapshot(event.state) })
      },
    })

    const before = learning.getPersona()
    // A clearly positive user message.
    learning.ingestTurn('user', '你真的太棒了，我好喜欢和你聊天，谢谢你！')
    const afterPos = learning.getPersona()

    // Before the fix, `ingestTurn` never passed a signal so `applyInteraction`
    // never ran; warmth would be identical. Now it must move.
    expect(afterPos.vector.warmth).toBeGreaterThan(before.vector.warmth)
    expect(afterPos.endocrine.oxytocin).toBeGreaterThan(before.endocrine.oxytocin)

    // A clearly negative message should push the other way.
    learning.ingestTurn('assistant', '抱歉，我搞砸了，这真的很糟糕，很烦人。')
    const afterNeg = learning.getPersona()
    expect(afterNeg.endocrine.cortisol).toBeGreaterThan(afterPos.endocrine.cortisol)

    // Drift must also keep the persona from freezing.
    learning.tick(600_000)
    const drifted = learning.getPersona()
    expect(drifted.updatedAt).toBeGreaterThanOrEqual(afterNeg.updatedAt)

    // Telemetry should have captured every change.
    expect(records.length).toBeGreaterThanOrEqual(3)
    expect(records[0].persona).toBeDefined()
    expect(records[0].persona!.vector.warmth).toBeGreaterThanOrEqual(0)
  })

  it('respects the interactionGain ablation (0 = no interaction effect)', () => {
    const learning = createContinuousLearning({
      llm: fakeLLM(),
      dynamics: { interactionGain: 0 },
      signalExtractor: createLexiconSignalExtractor(),
    })
    const before = learning.getPersona()
    learning.ingestTurn('user', '你真的太棒了，我好喜欢你！')
    const after = learning.getPersona()
    expect(after.vector.warmth).toBeCloseTo(before.vector.warmth, 10)
    expect(after.endocrine.oxytocin).toBeCloseTo(before.endocrine.oxytocin, 10)
  })

  it('exposes the active dynamics parameters for sweep logging', () => {
    const learning = createContinuousLearning({ llm: fakeLLM(), dynamics: { interactionGain: 2 } })
    const d = learning.getDynamics()
    expect(d.interactionGain).toBe(2)
    // Non-overridden knobs keep their validated defaults.
    expect(d.drift.relaxationMs).toBe(600_000)
  })

  it('falls back gracefully when no signal extractor is provided (legacy mode)', () => {
    const spied = vi.fn()
    const learning = createContinuousLearning({
      llm: fakeLLM(),
      signalExtractor: null,
      onPersonaUpdate: spied,
    })
    const before = learning.getPersona()
    learning.ingestTurn('user', '你真的太棒了，我好喜欢你！')
    const after = learning.getPersona()
    // With no extractor and no explicit signal, the legacy behaviour holds:
    // the persona does not move from the interaction.
    expect(after.vector.warmth).toBeCloseTo(before.vector.warmth, 10)
    // Only drift emits updates.
    expect(spied).not.toHaveBeenCalled()
  })
})
