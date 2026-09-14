import { describe, expect, it } from 'vitest'

import {
  assertOracleAvailable,
  createMemorySkillStore,
  createSkillRegistry,
} from './index'

function reg() {
  return createSkillRegistry({ store: createMemorySkillStore(), now: () => 1_700_000_000_000 })
}

describe('persistence', () => {
  it('survives a new registry bound to the same store', async () => {
    const store = createMemorySkillStore()
    const a = createSkillRegistry({ store })
    await a.create({ name: 'craft_table', domain: 'game', skillId: 'k1' })

    // Simulate a process restart: fresh registry, same backing store.
    const b = createSkillRegistry({ store })
    expect(await b.get('k1')).toBeDefined()
    expect((await b.all()).length).toBe(1)
  })
})

describe('precision becomes computable', () => {
  it('tracks call / success / failure counters', async () => {
    const r = reg()
    const s = await r.create({ name: 'mine', domain: 'game', skillId: 'k1' })

    await r.recordExecution(s.skillId, { ok: true })
    await r.recordExecution(s.skillId, { ok: false })
    await r.recordExecution(s.skillId, { ok: true })

    const rec = await r.get(s.skillId)
    expect(rec?.callCount).toBe(3)
    expect(rec?.successCount).toBe(2)
    expect(rec?.failureCount).toBe(1)

    const m = await r.metrics()
    expect(m.precision).toBeCloseTo(2 / 3, 5)
  })

  it('reports NaN precision when nothing was ever called, not 0', async () => {
    const r = reg()
    await r.create({ name: 'never_used', domain: 'game', skillId: 'k1' })
    const m = await r.metrics()
    // A study that executed nothing must not be able to report "0% precision".
    expect(Number.isNaN(m.precision)).toBe(true)
  })
})

describe('self-verification hallucination rate', () => {
  it('counts self-passed-but-failed skills', async () => {
    const r = reg()

    // Two skills the LLM declared correct; the environment disagreed with one.
    const good = await r.create({ name: 'good', domain: 'game', skillId: 'k1' })
    await r.setSelfVerification(good.skillId, 'pass', { score: 0.95 })
    await r.recordExecution(good.skillId, { ok: true })

    const bad = await r.create({ name: 'bad', domain: 'game', skillId: 'k2' })
    await r.setSelfVerification(bad.skillId, 'pass', { score: 0.88 })
    await r.recordExecution(bad.skillId, { ok: false, detail: 'tool missing' })

    const m = await r.metrics()
    expect(m.selfPass).toBe(2)
    expect(m.execFail).toBe(1)
    expect(m.selfVerificationHallucinationRate).toBeCloseTo(0.5, 5)
    expect(m.selfEnvironmentAgreement).toBeCloseTo(0.5, 5)
  })

  it('records the miss rate: good skills the model threw away', async () => {
    const r = reg()
    const s = await r.create({ name: 'underrated', domain: 'game', skillId: 'k1' })
    await r.setSelfVerification(s.skillId, 'fail', { score: 0.2 })
    await r.recordExecution(s.skillId, { ok: true })

    const m = await r.metrics()
    expect(m.selfVerificationMissRate).toBe(1)
    // Self-rejection should mark the skill rejected, not silently keep it active.
    expect((await r.get(s.skillId))?.status).toBe('rejected')
  })
})

describe('retirement stops the library being add-only', () => {
  it('auto-retires a skill that fails repeatedly', async () => {
    const r = reg()
    const s = await r.create({ name: 'doomed', domain: 'game', skillId: 'k1' })
    await r.recordExecution(s.skillId, { ok: false })
    await r.recordExecution(s.skillId, { ok: false })
    expect((await r.get(s.skillId))?.status).toBe('active') // not yet: only 2 calls

    await r.recordExecution(s.skillId, { ok: false })
    const rec = await r.get(s.skillId)
    expect(rec?.status).toBe('retired')
    expect(rec?.retirementReason).toBe('low-precision')
  })

  it('prunes below a precision threshold once minCalls is met', async () => {
    const r = reg()
    for (let i = 0; i < 4; i++) {
      const s = await r.create({ name: `s${i}`, domain: 'game', skillId: `k${i}` })
      // k0 stays precise (3/3); the rest sit at 1/3 and are pruned.
      await r.recordExecution(s.skillId, { ok: true })
      await r.recordExecution(s.skillId, { ok: i === 0 })
      await r.recordExecution(s.skillId, { ok: i === 0 })
    }

    // Nothing should have been auto-retired: every skill has >=1 success.
    expect(await r.metrics().then(m => m.retired)).toBe(0)

    const pruned = await r.pruneLowPrecision(0.5, 3)
    expect(pruned.map(p => p.skillId).sort()).toEqual(['k1', 'k2', 'k3'])
    const m = await r.metrics()
    expect(m.active).toBe(1)
    expect(m.retired).toBe(3)
    expect(m.precision).toBeCloseTo(6 / 12, 5)
  })
})

describe('2x2 design', () => {
  it('separates oracle-available from oracle-absent domains', async () => {
    const r = reg()

    const g = await r.create({ name: 'mine', domain: 'game', skillId: 'g1' })
    await r.setSelfVerification(g.skillId, 'pass')
    await r.recordExecution(g.skillId, { ok: false })

    await r.create({
      name: 'comfort_user',
      domain: 'conversation',
      skillId: 'c1',
      selfVerification: { verdict: 'pass', enabled: true },
    })
    // No execution recorded: conversation has no oracle. That is the point.

    const cells = await r.twoByTwo()
    const gameOn = cells.find(x => x.domain === 'game' && x.selfVerificationEnabled)
    const convOn = cells.find(x => x.domain === 'conversation' && x.selfVerificationEnabled)

    expect(gameOn?.count).toBe(1)
    expect(gameOn?.hallucinationRate).toBe(1)
    expect(convOn?.count).toBe(1)
    // The conversation cell can never produce a hallucination rate — which is
    // precisely the asymmetry the experiment is designed around.
    expect(Number.isNaN(convOn?.hallucinationRate ?? Number.NaN)).toBe(true)

    const m = await r.metrics()
    expect(m.byDomain.game).toBe(1)
    expect(m.byDomain.conversation).toBe(1)
  })

  it('refuses to fabricate ground truth for a domain without an oracle', async () => {
    const r = reg()
    const c = await r.create({ name: 'chat', domain: 'conversation', skillId: 'c1' })
    expect(() => assertOracleAvailable(c)).toThrow(/no environmental oracle/)
  })
})
