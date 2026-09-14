import type { SkillBody, SkillFrontmatter, SkillPackage } from './types'

/**
 * Serialize a skill's YAML frontmatter by hand (no YAML dependency). Only the
 * fields Hermes / agentskills.io care about are emitted.
 */
function serializeFrontmatter(fm: SkillFrontmatter): string {
  const lines: string[] = ['---']
  lines.push(`name: ${fm.name}`)
  lines.push(`description: ${JSON.stringify(fm.description)}`)
  lines.push(`version: ${fm.version}`)
  lines.push(`author: ${fm.author}`)
  if (fm.platforms && fm.platforms.length > 0)
    lines.push(`platforms: [${fm.platforms.map(p => JSON.stringify(p)).join(', ')}]`)
  if (fm.metadata?.tags && fm.metadata.tags.length > 0) {
    lines.push('metadata:')
    lines.push(`  tags: [${fm.metadata.tags.map(t => JSON.stringify(t)).join(', ')}]`)
  }
  lines.push('---')
  return lines.join('\n')
}

function serializeSection(heading: string, items?: string[] | string): string {
  if (items == null)
    return ''
  if (Array.isArray(items)) {
    if (items.length === 0)
      return ''
    return [`## ${heading}`, ...items.map(i => `- ${i}`)].join('\n')
  }
  return [`## ${heading}`, items].join('\n')
}

function serializeNumbered(heading: string, items: string[]): string {
  if (items.length === 0)
    return ''
  const body = items.map((step, i) => `${i + 1}. ${step}`).join('\n')
  return [`## ${heading}`, body].join('\n')
}

/** Build the agentskills.io-compatible SKILL.md text for a skill package. */
export function skillToMarkdown(pkg: SkillPackage): string {
  const { frontmatter: fm, body } = pkg
  const blocks: string[] = [serializeFrontmatter(fm)]

  blocks.push(`# ${body.title}`)
  if (body.intro)
    blocks.push(body.intro)

  blocks.push(serializeSection('When to Use', body.whenToUse))
  blocks.push(serializeSection('Prerequisites', body.prerequisites))
  blocks.push(serializeSection('How to Run', body.howToRun))
  blocks.push(serializeSection('Quick Reference', body.quickReference))
  blocks.push(serializeNumbered('Procedure', body.procedure))
  blocks.push(serializeSection('Pitfalls', body.pitfalls))
  blocks.push(serializeSection('Verification', body.verification))

  return `${blocks.filter(Boolean).join('\n\n')}\n`
}

/** Parse a SKILL.md string back into frontmatter + body (module is not reconstructable). */
export function parseSkillMarkdown(text: string): { frontmatter: SkillFrontmatter, body: SkillBody } {
  const match = text.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/)
  if (!match)
    throw new Error('Invalid SKILL.md: missing YAML frontmatter delimited by ---.')
  const frontRaw = match[1]
  const bodyRaw = match[2]

  const fm: Record<string, unknown> = {}
  let parent: string | null = null
  for (const line of frontRaw.split('\n')) {
    const m = line.match(/^(\s*)(\w+):\s*(.*)$/)
    if (!m)
      continue
    const indent = m[1].length
    const key = m[2]
    const raw = m[3].trim()
    let value: unknown = raw
    if (raw.startsWith('[') || raw.startsWith('{') || (raw.startsWith('"') && raw.endsWith('"')))
      value = JSON.parse(raw)
    if (indent === 0) {
      if (value === '' || value === null) {
        // A bare `key:` opens a nested block (e.g. `metadata:`).
        fm[key] = {}
        parent = key
      }
      else {
        fm[key] = value
        parent = null
      }
    }
    else if (parent) {
      // Continuation of the open nested block.
      ;(fm[parent] as Record<string, unknown>)[key] = value
    }
  }

  const body: SkillBody = { title: '', whenToUse: [], procedure: [] }
  const lines = bodyRaw.split('\n')

  // Title + intro live before the first `##` section.
  const firstSectionIdx = lines.findIndex(l => /^##\s/.test(l))
  const headLines = (firstSectionIdx === -1 ? lines : lines.slice(0, firstSectionIdx)).filter(Boolean)
  if (headLines[0]?.startsWith('# '))
    body.title = headLines[0].slice(2).trim()
  body.intro = headLines.slice(1).join('\n').trim() || undefined

  // Walk sections, collecting each section's content lines into the buffer.
  const listKey: Record<string, 'whenToUse' | 'prerequisites' | 'pitfalls' | 'quickReference'> = {
    'When to Use': 'whenToUse',
    'Prerequisites': 'prerequisites',
    'Pitfalls': 'pitfalls',
    'Quick Reference': 'quickReference',
  }
  let current: string | null = null
  let buffer: string[] = []
  const flush = () => {
    if (!current)
      return
    const content = buffer.join('\n').trim()
    if (current in listKey) {
      const key = listKey[current]
      body[key] = content.split('\n').map(s => s.replace(/^- /, '')).filter(Boolean)
    }
    else if (current === 'Procedure') {
      body.procedure = content.split('\n').map(s => s.replace(/^\d+\.\s*/, '')).filter(Boolean)
    }
    else if (current === 'How to Run') {
      body.howToRun = content
    }
    else if (current === 'Verification') {
      body.verification = content
    }
  }
  const sectionRe = /^##\s+(.+?)\s*$/
  for (let i = firstSectionIdx === -1 ? lines.length : firstSectionIdx; i < lines.length; i++) {
    const sec = lines[i].match(sectionRe)
    if (sec) {
      flush()
      current = sec[1].trim()
      buffer = []
    }
    else if (current) {
      buffer.push(lines[i])
    }
  }
  flush()

  return {
    frontmatter: fm as unknown as SkillFrontmatter,
    body,
  }
}
