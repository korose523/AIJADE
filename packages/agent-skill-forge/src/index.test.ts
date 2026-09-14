import { describe, expect, it } from 'vitest'

import { defineSkill, parseSkillMarkdown, skillFrontmatterSchema, skillToMarkdown } from './index'

describe('skillFrontmatterSchema', () => {
  it('accepts a compliant frontmatter', () => {
    const r = skillFrontmatterSchema.safeParse({
      name: 'search-arxiv',
      description: 'Search arXiv papers by keyword.',
      version: '0.1.0',
      author: 'AIJADE',
    })
    expect(r.success).toBe(true)
  })

  it('rejects a description without a trailing period', () => {
    const r = skillFrontmatterSchema.safeParse({
      name: 'search-arxiv',
      description: 'Search arXiv papers by keyword',
      version: '0.1.0',
      author: 'AIJADE',
    })
    expect(r.success).toBe(false)
  })

  it('rejects an over-long description', () => {
    const r = skillFrontmatterSchema.safeParse({
      name: 'x',
      description: 'A comprehensive skill that lets the agent search arXiv for academic papers using many fields.',
      version: '0.1.0',
      author: 'AIJADE',
    })
    expect(r.success).toBe(false)
  })
})

describe('defineSkill', () => {
  it('fills version/author defaults and stamps timestamps', () => {
    const pkg = defineSkill({
      frontmatter: { name: 'hello', description: 'Greet the user warmly.' },
      body: { title: 'Hello', whenToUse: ['when greeting'], procedure: ['say hi'] },
    })
    expect(pkg.frontmatter.version).toBe('0.1.0')
    expect(pkg.frontmatter.author).toBe('AIJADE')
    expect(pkg.source).toBe('hand-authored')
    expect(pkg.evolutionLog).toEqual([])
    expect(pkg.createdAt).toBeGreaterThan(0)
  })
})

describe('skillToMarkdown / parseSkillMarkdown', () => {
  it('round-trips frontmatter and body', () => {
    const pkg = defineSkill({
      frontmatter: {
        name: 'open-notepad',
        description: 'Open the system notepad app.',
        platforms: ['windows'],
        metadata: { tags: ['Os', 'Utility'] },
      },
      body: {
        title: 'Open Notepad',
        intro: 'Launches Notepad without stealing focus.',
        whenToUse: ['user wants to edit text'],
        prerequisites: ['Windows 10+'],
        howToRun: 'invoke through the computer_use tool',
        quickReference: ['action: focus_app'],
        procedure: ['Capture the desktop', 'Focus Notepad'],
        pitfalls: ['May raise the window'],
        verification: 'Notepad is the frontmost process',
      },
    })
    const md = skillToMarkdown(pkg)
    expect(md).toContain('name: open-notepad')
    expect(md).toContain('## Procedure')
    expect(md).toContain('1. Capture the desktop')

    const parsed = parseSkillMarkdown(md)
    expect(parsed.frontmatter.name).toBe('open-notepad')
    expect(parsed.frontmatter.platforms).toEqual(['windows'])
    expect(parsed.body.procedure).toEqual(['Capture the desktop', 'Focus Notepad'])
    expect(parsed.body.title).toBe('Open Notepad')
  })
})
