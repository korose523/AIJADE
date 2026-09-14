import type { Episode, SemanticFact } from './types'

import { LexicalDistiller } from './consolidation'

/**
 * Minimal LLM surface the memory package needs. Implemented by an adapter that
 * wraps `@proj-aijade/model-substrate` (see eval/adapter-model-substrate.ts) so
 * this package stays dependency-free. The dynamics experiment does NOT require
 * an LLM — {@link LexicalDistiller} is the default and is fully deterministic.
 */
export interface LlmClient {
  generate: (prompt: string, opts: { temperature: number, maxTokens?: number }) => Promise<string>
}

function summarizePrompt(episodes: Episode[]): string {
  const bullet = episodes.map(e => `- ${e.content}`).join('\n')
  return [
    'Distil the following conversation excerpts into concise, self-contained factual statements.',
    'Preserve names, dates, and relationships exactly. One statement per line.',
    '',
    bullet,
  ].join('\n')
}

/**
 * LLM-backed distiller. Falls back to lexical behaviour for any episode it
 * cannot summarise, so a partial model failure never breaks consolidation.
 */
export class LlmDistiller extends LexicalDistiller {
  constructor(private readonly client: LlmClient) {
    super()
  }

  async distill(episodes: Episode[]): Promise<SemanticFact[]> {
    const base = await super.distill(episodes)
    const prompt = summarizePrompt(episodes)
    try {
      const out = await this.client.generate(prompt, { temperature: 0, maxTokens: 512 })
      const lines = out.split('\n').map(l => l.trim()).filter(Boolean)
      if (lines.length > 0) {
        return episodes.map((e, i): SemanticFact => ({
          ...base[i],
          content: lines[i] ?? e.content,
        }))
      }
    }
    catch {
      // fall through to lexical base
    }
    return base
  }
}
