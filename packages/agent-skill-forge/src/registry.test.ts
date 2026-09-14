import { describe, expect, it } from 'vitest'

import { defineSkill } from './index'
import { createSkillRegistry } from './registry'

describe('measured skill registry', () => {
  it('keeps the legacy sync API working (add/get/has/list/remove)', () => {
    const skill = defineSkill({
      frontmatter: { name: 'open-notepad', description: 'Open the notepad app.' },
      body: { title: 'Open Notepad', whenToUse: ['edit text'], procedure: ['focus notepad'] },
    })
    const reg = createSkillRegistry([skill])
    expect(reg.has('open-notepad')).toBe(true)
    expect(reg.get('open-notepad')?.frontmatter.name).toBe('open-notepad')
    expect(reg.list()).toHaveLength(1)
    expect(reg.remove('open-notepad')).toBe(true)
    expect(reg.has('open-notepad')).toBe(false)
  })

  it('computes precision and the self-verification hallucination rate', () => {
    const good = defineSkill({
      frontmatter: { name: 'good', description: 'A reliable skill.' },
      body: { title: 'Good', whenToUse: ['x'], procedure: ['y'] },
    })
    const bad = defineSkill({
      frontmatter: { name: 'bad', description: 'A broken skill.' },
      body: { title: 'Bad', whenToUse: ['x'], procedure: ['y'] },
    })
    const reg = createSkillRegistry([good, bad])
    reg.setSelfVerification('good', 'pass', { score: 0.9 })
    reg.setSelfVerification('bad', 'pass', { score: 0.9 })

    // good actually works; bad actually fails → a self-verification hallucination.
    reg.recordExecution('good', { ok: true })
    reg.recordExecution('bad', { ok: false, detail: 'tool missing' })

    const m = reg.metrics()
    expect(m.total).toBe(2)
    expect(m.selfPass).toBe(2)
    expect(m.executed).toBe(2)
    expect(m.execSuccess).toBe(1)
    expect(m.execFail).toBe(1)
    expect(m.precision).toBeCloseTo(0.5, 5)
    // The headline RQ-C number: of the 2 self-passed skills, 1 failed → 0.5.
    expect(m.selfVerificationHallucinationRate).toBeCloseTo(0.5, 5)
  })

  it('auto-retires a skill after 3 consecutive failures', () => {
    const k = defineSkill({
      frontmatter: { name: 'flaky', description: 'Flaky.' },
      body: { title: 'Flaky', whenToUse: ['x'], procedure: ['y'] },
    })
    const reg = createSkillRegistry([k])
    reg.recordExecution('flaky', { ok: false })
    expect(reg.get('flaky')?.source).toBeDefined()
    reg.recordExecution('flaky', { ok: false })
    reg.recordExecution('flaky', { ok: false })
    const m = reg.metrics()
    expect(m.retired).toBe(1)
    expect(m.active).toBe(0)
  })

  it('rejects on self-verification failure and builds the 2×2', () => {
    const s = defineSkill({
      frontmatter: { name: 'rejected', description: 'Will fail self-check.' },
      body: { title: 'R', whenToUse: ['x'], procedure: ['y'] },
    })
    const reg = createSkillRegistry([s], { domain: 'game' })
    reg.setSelfVerification('rejected', 'fail', { score: 0.1 })
    const m = reg.metrics()
    expect(m.selfFail).toBe(1)
    expect(m.rejected).toBe(1)
    const table = reg.twoByTwo()
    expect(table.length).toBeGreaterThan(0)
    expect(table.some(c => c.domain === 'game')).toBe(true)
  })
})
