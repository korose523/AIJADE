import type { PersonaSnapshot } from './types'

import { describe, expect, it } from 'vitest'

import {
  createMemoryStorage,
  CSV_COLUMNS,
  fingerprintConfig,
  fingerprintParameters,
  startSession,
  sweepAxis,
  toCsv,
} from './index'

function persona(offset = 0): PersonaSnapshot {
  const base = 0.5 + offset
  return {
    vector: {
      openness: base,
      warmth: base,
      curiosity: base,
      patience: base,
      formality: base,
      playfulness: base,
      caution: base,
      confidence: base,
      empathy: base,
      spontaneity: base,
      diligence: base,
      assertiveness: base,
      stability: base,
    },
    endocrine: {
      dopamine: base,
      serotonin: base,
      cortisol: base,
      oxytocin: base,
      adrenaline: base,
    },
    pad: { pleasure: base, arousal: base, dominance: base },
    bigFive: { O: base, C: base, E: base, A: base, N: base },
    intimacy: {
      warmth: base,
      trust: base,
      dependence: base,
      security: base,
      familiarity: base,
      longing: base,
    },
    moodLabel: 'calm',
  }
}

describe('fingerprintConfig', () => {
  it('is deterministic regardless of key insertion order', () => {
    const a = fingerprintConfig({
      personaDynamics: true,
      hormoneCoupling: false,
      memoryRetrieval: true,
      skillForge: true,
      discourseMemory: true,
    })
    const b = fingerprintConfig({
      discourseMemory: true,
      skillForge: true,
      memoryRetrieval: true,
      hormoneCoupling: false,
      personaDynamics: true,
    })
    expect(a).toBe(b)
  })

  it('differs when a switch flips', () => {
    const base = {
      personaDynamics: true,
      hormoneCoupling: true,
      memoryRetrieval: true,
      skillForge: true,
      discourseMemory: true,
    }
    expect(fingerprintConfig(base)).not.toBe(
      fingerprintConfig({ ...base, hormoneCoupling: false }),
    )
  })
})

describe('fingerprintParameters', () => {
  it('ignores key order inside nested maps', () => {
    const a = fingerprintParameters({
      relaxationMs: 1000,
      hormoneCoupling: { dopamine: 0.3, cortisol: 0.1 },
    })
    const b = fingerprintParameters({
      relaxationMs: 1000,
      hormoneCoupling: { cortisol: 0.1, dopamine: 0.3 },
    })
    expect(a).toBe(b)
  })
})

describe('sweepAxis', () => {
  it('produces one point per value with readable names', () => {
    const points = sweepAxis('relaxationMs', [100, 200, 400])
    expect(points).toHaveLength(3)
    expect(points.map(p => p.name)).toEqual(['relax-100', 'relax-200', 'relax-400'])
    expect(points[2].parameters.relaxationMs).toBe(400)
  })
})

describe('experimentSessionRunner', () => {
  it('records turns with monotonic indices and persona snapshots', async () => {
    const storage = createMemoryStorage()
    const session = await startSession({ storage, sessionId: 's1', condition: 'baseline' })

    await session.recordTurn({ role: 'user', persona: persona(0), textLength: 12 })
    await session.recordTurn({ role: 'assistant', persona: persona(0.1), textLength: 84 })

    const turns = await storage.readTurns('s1')
    expect(turns).toHaveLength(2)
    expect(turns[0].turnIndex).toBe(0)
    expect(turns[1].turnIndex).toBe(1)
    expect(turns[1].persona?.vector.openness).toBeCloseTo(0.6, 5)
  })

  it('carries session parameters onto every turn', async () => {
    const storage = createMemoryStorage()
    const session = await startSession({
      storage,
      sessionId: 's2',
      parameters: { relaxationMs: 2500, noiseSigma: 0.02 },
    })
    await session.recordTurn({ role: 'user' })

    const turns = await storage.readTurns('s2')
    expect(turns[0].parameters?.relaxationMs).toBe(2500)
    expect(session.parameterFingerprint).toBe(
      fingerprintParameters({ relaxationMs: 2500, noiseSigma: 0.02 }),
    )
  })

  it('exposes ablation state via isEnabled', async () => {
    const session = await startSession({ condition: 'no-hormone-coupling' })
    expect(session.isEnabled('hormoneCoupling')).toBe(false)
    expect(session.isEnabled('personaDynamics')).toBe(true)
  })

  it('rejects turns after close', async () => {
    const session = await startSession({ sessionId: 's3' })
    await session.close()
    await expect(session.recordTurn({ role: 'user' })).rejects.toThrow(/closed/)
  })
})

describe('toCsv', () => {
  it('flattens nested persona state into one column per scalar', async () => {
    const storage = createMemoryStorage()
    const session = await startSession({ storage, sessionId: 's4' })
    await session.recordTurn({
      role: 'assistant',
      persona: persona(0.2),
      latency: { llm: 800, total: 1100 },
      tokens: { prompt: 1200, completion: 90 },
    })

    const csv = toCsv(await storage.readTurns('s4'))
    const [header, row] = csv.trim().split('\n')

    expect(header).toBe(CSV_COLUMNS.join(','))
    expect(header).toContain('persona.endocrine.dopamine')
    expect(header).toContain('latency.llm')

    const idx = (col: string) => CSV_COLUMNS.indexOf(col)
    const cells = row.split(',')
    expect(Number(cells[idx('persona.pad.pleasure')])).toBeCloseTo(0.7, 5)
    expect(Number(cells[idx('latency.llm')])).toBe(800)
    expect(Number(cells[idx('tokens.prompt')])).toBe(1200)
  })

  it('emits a header-only file for an empty set', () => {
    expect(toCsv([]).trim()).toBe(CSV_COLUMNS.join(','))
  })
})
