import { describe, expect, it } from 'vitest'

import { LayeredMemory } from './engine'
import { createLayeredMemoryPort } from './port'

describe('createLayeredMemoryPort', () => {
  it('recalls the most relevant memory as a context block', async () => {
    const engine = new LayeredMemory()
    const port = createLayeredMemoryPort(engine, { scope: 'chat' })

    await port.ingestUser('I love playing Minecraft with my friends')
    await port.ingestUser('My favorite color is blue and I like the sea')

    const block = await port.recall('tell me about Minecraft')
    expect(block).not.toBeNull()
    expect(block).toContain('[Memory]')
    expect(block).toContain('Minecraft')
  })

  it('returns null when nothing is relevant', async () => {
    const engine = new LayeredMemory()
    const port = createLayeredMemoryPort(engine)
    expect(await port.recall('')).toBeNull()
    expect(await port.recall('anything')).toBeNull()
  })

  it('ingests assistant turns into the episodic tier', async () => {
    const engine = new LayeredMemory()
    const port = createLayeredMemoryPort(engine)
    await port.ingestAssistant('Sure, let\'s build a redstone contraption!')
    expect(engine.stats().episodic).toBe(1)
  })

  it('compacts once the episodic tier crosses the threshold', async () => {
    const engine = new LayeredMemory()
    const port = createLayeredMemoryPort(engine, { compactThreshold: 2, scope: 'chat' })

    await port.ingestUser('one')
    await port.ingestUser('two')
    await port.ingestUser('three')
    expect(engine.stats().summaries).toBe(0)

    await port.maybeCompact!()
    expect(engine.stats().summaries).toBeGreaterThanOrEqual(1)
    // episodic tier was compacted (threshold was 2, so >2 entries triggered)
    expect(engine.stats().episodic).toBeLessThan(3)
  })

  it('does not compact below threshold', async () => {
    const engine = new LayeredMemory()
    const port = createLayeredMemoryPort(engine, { compactThreshold: 20 })
    await port.ingestUser('only a few turns')
    await port.maybeCompact!()
    expect(engine.stats().summaries).toBe(0)
    expect(engine.stats().episodic).toBe(1)
  })
})
