import type { TelemetryStorage, TurnRecord } from '@proj-aijade/research-telemetry'

import type { LearningLLM } from './index'

import { createMemoryStorage } from '@proj-aijade/research-telemetry'
import { describe, expect, it, vi } from 'vitest'

import {
  createContinuousLearning,
  createLexiconSignalExtractor,
  createPersonaTelemetryRecorder,
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

const POSITIVE = '你真的太棒了，我好喜欢和你聊天，谢谢你！'

/**
 * D1 regression: `onPersonaUpdate` has been plumbed through the bridge since it
 * was written and its docstring calls the trajectory "the data backbone of the
 * dissertation", yet no call site ever passed a listener, so production never
 * recorded a single turn. These tests pin the recorder that closes that gap —
 * and pin the consent semantics an IRB reviewer will look for.
 */
describe('createPersonaTelemetryRecorder', () => {
  it('records nothing while consent is false — not even a session', async () => {
    const storage = createMemoryStorage()
    const recorder = createPersonaTelemetryRecorder({ consent: () => false, storage, sessionId: 's1' })
    const learning = createContinuousLearning({
      llm: fakeLLM(),
      signalExtractor: createLexiconSignalExtractor(),
      onPersonaUpdate: recorder.record,
    })

    learning.ingestTurn('user', POSITIVE)
    await new Promise(resolve => setTimeout(resolve, 10))

    expect((await storage.readTurns('s1')).length).toBe(0)
    expect((await storage.readSessions()).length).toBe(0)
    expect(recorder.diagnostics()).toEqual({ recording: false, turnsRecorded: 0 })
  })

  it('records a turn with a persona snapshot once consent is given', async () => {
    const storage = createMemoryStorage()
    const consent = true
    const recorder = createPersonaTelemetryRecorder({ consent: () => consent, storage, sessionId: 's2' })
    const learning = createContinuousLearning({
      llm: fakeLLM(),
      signalExtractor: createLexiconSignalExtractor(),
      onPersonaUpdate: recorder.record,
    })

    learning.ingestTurn('user', POSITIVE)
    learning.tick(600_000) // drift also emits a persona update

    const turns = await vi.waitFor(async () => {
      const read = await storage.readTurns('s2')
      expect(read.length).toBeGreaterThanOrEqual(2)
      return read
    })

    expect(turns.every(t => t.persona)).toBe(true)
    expect(turns.every(t => t.persona!.vector.warmth >= 0)).toBe(true)
    expect(recorder.diagnostics().turnsRecorded).toBeGreaterThanOrEqual(2)
    expect(recorder.diagnostics().recording).toBe(true)
  })

  it('erases the recorded trajectory when consent is withdrawn', async () => {
    const storage = createMemoryStorage()
    let consent = true
    const recorder = createPersonaTelemetryRecorder({ consent: () => consent, storage, sessionId: 's3' })
    const learning = createContinuousLearning({
      llm: fakeLLM(),
      signalExtractor: createLexiconSignalExtractor(),
      onPersonaUpdate: recorder.record,
    })

    learning.ingestTurn('user', POSITIVE)
    await vi.waitFor(async () => {
      expect((await storage.readTurns('s3')).length).toBeGreaterThan(0)
    })

    // Withdrawal must stop recording *and* purge what was already written —
    // keeping previously collected turns after a withdrawal is exactly what an
    // IRB review treats as a violation.
    consent = false
    learning.ingestTurn('user', POSITIVE)
    await vi.waitFor(async () => {
      expect(await storage.readTurns('s3')).toHaveLength(0)
      expect(await storage.readSessions()).toHaveLength(0)
    })
    expect(recorder.diagnostics().turnsRecorded).toBe(0)
  })

  it('never throws into the chat path when storage fails', async () => {
    const failing: TelemetryStorage = {
      saveSession: () => Promise.reject(new Error('boom')),
      appendTurn: () => Promise.reject(new Error('boom')),
      readTurns: () => Promise.resolve([] as TurnRecord[]),
      readSessions: () => Promise.resolve([]),
      clear: () => Promise.reject(new Error('boom')),
    }
    const onError = vi.fn()
    const recorder = createPersonaTelemetryRecorder({ consent: () => true, storage: failing, sessionId: 's4', onError })
    const learning = createContinuousLearning({
      llm: fakeLLM(),
      signalExtractor: createLexiconSignalExtractor(),
      onPersonaUpdate: recorder.record,
    })

    expect(() => learning.ingestTurn('user', POSITIVE)).not.toThrow()
    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalled()
      expect(recorder.diagnostics().lastError).toBe('boom')
    })
    expect(recorder.diagnostics().turnsRecorded).toBe(0)
  })

  it('refuses to fall back to in-memory storage when no durable storage exists', async () => {
    const onError = vi.fn()
    const recorder = createPersonaTelemetryRecorder({ consent: () => true, onError, sessionId: 's5' })

    recorder.record({
      state: {
        vector: { warmth: 0, curiosity: 0, energy: 0, humor: 0, patience: 0, assertiveness: 0, sincerity: 0, playfulness: 0, formality: 0, empathy: 0 } as never,
        endocrine: {} as never,
        intimacy: {} as never,
        updatedAt: 0,
      } as never,
      cause: 'interaction',
      timestamp: 0,
      role: 'user',
    })

    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalled()
      expect(recorder.diagnostics().lastError).toContain('no durable storage')
    })
  })
})
