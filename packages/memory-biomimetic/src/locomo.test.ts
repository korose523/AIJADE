import { describe, expect, it } from 'vitest'

import { buildMemory, evidenceRecall, parseConversation } from './locomo'
import { DEFAULT_GATING, NO_GATING } from './types'

const raw = {
  sample_id: 'test',
  conversation: {
    speaker_a: 'A',
    speaker_b: 'B',
    session_1_date_time: '1:00 pm on 1 Jan, 2023',
    session_1: [
      { speaker: 'A', dia_id: 'D1:1', text: 'Caroline went to the LGBTQ support group' },
      { speaker: 'B', dia_id: 'D1:2', text: 'The weather was nice and we walked the dog' },
    ],
  },
  qa: [
    { question: 'When did Caroline go to the support group?', answer: '1 Jan 2023', evidence: ['D1:1'], category: 1 },
    { question: 'Who went to the support group?', answer: 'Caroline', evidence: ['D1:1'], category: 1 },
  ],
}

describe('parseConversation', () => {
  it('maps sessions to episodes keyed by dia_id', () => {
    const c = parseConversation(raw as any)
    expect(c.episodes.map(e => e.id)).toEqual(['D1:1', 'D1:2'])
    expect(c.evidenceIds.has('D1:1')).toBe(true)
    expect(c.endTs).toBeGreaterThan(0)
  })
  it('marks evidence-bearing turns as salient (high dopamine)', () => {
    const c = parseConversation(raw as any)
    const salient = c.episodes.find(e => e.id === 'D1:1')!
    const noise = c.episodes.find(e => e.id === 'D1:2')!
    expect(salient.encoding.salience).toBeGreaterThan(noise.encoding.salience)
  })
})

describe('evidenceRecall pipeline (tiny fixture)', () => {
  it('runs end-to-end and ON retains evidence at least as well as OFF at +365d', async () => {
    const c = parseConversation(raw as any)
    const on = await buildMemory(c, DEFAULT_GATING)
    const off = await buildMemory(c, NO_GATING)
    on.setNow(c.endTs + 365 * 86_400_000)
    off.setNow(c.endTs + 365 * 86_400_000)
    const rOn = evidenceRecall(on, c, 5)
    const rOff = evidenceRecall(off, c, 5)
    expect(rOn.total).toBe(2)
    expect(rOn.overall).toBeGreaterThanOrEqual(rOff.overall)
  })
})
