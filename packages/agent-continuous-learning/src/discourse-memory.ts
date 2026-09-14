import type { ChatMessage } from '@proj-aijade/agent-llm-client'

import type { LearningLLM } from './types'

import { createLogger } from '@proj-aijade/agent-llm-client'

const logger = createLogger('agent-continuous-learning:discourse')

export interface DiscourseMemoryOptions {
  llm: LearningLLM
  /** Max recent messages kept verbatim before compaction. */
  window?: number
  /** Max working-memory chunks (LPM "3-chunk hybrid cache"). */
  maxChunks?: number
}

export interface DiscourseMemory {
  ingest: (role: 'user' | 'assistant', text: string) => void
  /** Summarize overflow into a "sink" chunk (LPM bounded-memory idea). */
  compact: () => Promise<void>
  /** Build a bounded context string for prompt injection. */
  context: () => string
  /** Recent messages as structured {@link ChatMessage}s (for teachable-moment detection). */
  recentMessages: () => ChatMessage[]
  stats: () => { recent: number, chunks: number }
}

/**
 * LPM-style bounded discourse memory. Recent turns are kept verbatim; when the
 * buffer overflows, the oldest slice is compressed by the LLM into a single
 * "sink" sentence and pushed into a small ring of working-memory chunks
 * (default 3). This keeps per-turn prompt cost roughly constant across long
 * sessions instead of growing without bound.
 */
export function createDiscourseMemory(options: DiscourseMemoryOptions): DiscourseMemory {
  const window = options.window ?? 12
  const maxChunks = options.maxChunks ?? 3
  const recent: ChatMessage[] = []
  const chunks: string[] = []

  function ingest(role: 'user' | 'assistant', text: string): void {
    recent.push({ role, content: text })
    if (recent.length > window * 1.5)
      void compact()
  }

  async function compact(): Promise<void> {
    if (recent.length <= window)
      return
    const overflow = recent.splice(0, Math.floor(recent.length - window))
    const transcript = overflow.map(m => `${m.role}: ${m.content}`).join('\n')
    try {
      const res = await options.llm.complete([
        {
          role: 'system',
          content: 'Compress conversation excerpts into ONE dense "sink" sentence of <=60 words, preserving durable facts and user preferences. Output only the sentence.',
        },
        { role: 'user', content: transcript },
      ])
      const sink = res.text.trim()
      if (sink) {
        chunks.push(sink)
        while (chunks.length > maxChunks)
          chunks.shift()
        logger.debug(`compacted ${overflow.length} messages -> sink chunk (${chunks.length}/${maxChunks})`)
      }
    }
    catch (err) {
      logger.warn(`discourse compact skipped: ${(err as Error).message}`)
    }
  }

  function context(): string {
    const parts: string[] = []
    if (chunks.length)
      parts.push(`[long-term sink]\n${chunks.join('\n')}`)
    const tail = recent.slice(-window)
    if (tail.length)
      parts.push(`[recent discourse]\n${tail.map(m => `${m.role}: ${m.content}`).join('\n')}`)
    return parts.join('\n\n')
  }

  function recentMessages(): ChatMessage[] {
    return recent.slice(-window)
  }

  return {
    ingest,
    compact,
    context,
    recentMessages,
    stats: () => ({ recent: recent.length, chunks: chunks.length }),
  }
}
