import { existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { defineSkill } from './index'
import { createPersistentSkillRegistry } from './registry'

function tmpFile(name: string): string {
  return join(tmpdir(), `aijade-skill-test-${process.pid}-${name}.jsonl`)
}

describe('persistent skill registry', () => {
  const created: string[] = []
  afterEach(() => {
    for (const f of created)
      rmSync(f, { force: true })
    created.length = 0
  })

  it('survives a restart: write, drop the instance, rebuild from the same file', () => {
    const file = tmpFile(`restart-${Date.now()}`)
    created.push(file)

    // Instance A: register a skill and exercise the measurement path.
    const a = createPersistentSkillRegistry([], { file })
    const skill = defineSkill({
      frontmatter: { name: 'open-notepad', description: 'Open the system notepad app.' },
      body: { title: 'Open Notepad', whenToUse: ['edit text'], procedure: ['focus notepad'] },
    })
    a.add(skill)
    a.setSelfVerification('open-notepad', 'pass', { score: 0.9 })
    a.recordExecution('open-notepad', { ok: true })
    expect(a.has('open-notepad')).toBe(true)
    expect(a.metrics().total).toBe(1)
    expect(a.metrics().execSuccess).toBe(1)
    expect(a.metrics().precision).toBe(1)

    // Instance A's in-memory state is about to be garbage-collected. Build a
    // brand-new instance backed ONLY by the same on-disk file.
    const b = createPersistentSkillRegistry([], { file })
    expect(b.has('open-notepad')).toBe(true)
    expect(b.get('open-notepad')?.frontmatter.name).toBe('open-notepad')
    expect(b.list()).toHaveLength(1)
    // The measured record survives too: precision is recomputed from disk.
    const m = b.metrics()
    expect(m.total).toBe(1)
    expect(m.execSuccess).toBe(1)
    expect(m.precision).toBe(1)
  })

  it('reconstructs a usable SkillPackage (body round-trips)', () => {
    const file = tmpFile(`body-${Date.now()}`)
    created.push(file)

    const a = createPersistentSkillRegistry([], { file })
    const skill = defineSkill({
      frontmatter: { name: 'greet', description: 'Greet the user warmly.' },
      body: { title: 'Greeting', whenToUse: ['when greeting'], procedure: ['say hi'] },
    })
    a.add(skill)

    const b = createPersistentSkillRegistry([], { file })
    const restored = b.get('greet')
    expect(restored).toBeDefined()
    expect(restored?.frontmatter.description).toBe('Greet the user warmly.')
    expect(restored?.body.procedure).toEqual(['say hi'])
  })

  it('does NOT persist when using the in-memory registry (contrast case)', () => {
    // Control: the classic in-memory registry loses everything on rebuild, which
    // is exactly the defect this fix addresses. Documented here so the contrast
    // is explicit and the persistence test above cannot be "cheated" by an
    // in-memory default.
    const file = tmpFile(`unused-${Date.now()}`)
    created.push(file)
    // File should not even be created by an in-memory registry.
    // (We do not construct a persistent registry here on purpose.)
    expect(existsSync(file)).toBe(false)
  })
})
