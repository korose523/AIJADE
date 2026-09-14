import type { LayeredMemoryOptions } from './engine/layered-memory'
import type { MemoryScope } from './engine/types'

import { LayeredMemory } from './engine/layered-memory'

/**
 * AIJADE-facing memory port.
 *
 * Decouples the conversation pipeline from the {@link LayeredMemory} engine:
 * the pipeline calls `recall` / `ingestUser` / `ingestAssistant` / `maybeCompact`
 * and never learns about embeddings, vector stores, or Scope-Recall internals.
 *
 * Structurally compatible with whatever the caller uses to build a
 * `ContextMessage`, so no cross-package type coupling is required.
 */
export interface MemoryPort {
  /** Recall memories relevant to the current user text, rendered as a context block. */
  recall: (query: string) => Promise<string | null>
  /** Persist a verbatim user turn into the episodic tier. */
  ingestUser: (text: string, ts?: number) => void | Promise<void>
  /** Persist a verbatim assistant turn into the episodic tier. */
  ingestAssistant: (text: string, ts?: number) => void | Promise<void>
  /** Optionally compact + prune when the episodic tier grows large. */
  maybeCompact?: () => void | Promise<void>
}

export interface LayeredMemoryPortOptions {
  /** Scope tag applied to ingested turns. @default 'chat' */
  scope?: MemoryScope
  /** Scopes filtered during recall. @default [options.scope] */
  recallScopes?: MemoryScope[]
  /** Max recalled memories returned to the prompt. @default 6 */
  recallLimit?: number
  /** Minimum long-term cosine similarity. @default 0.05 */
  minSimilarity?: number
  /** Episodic count that triggers `compact`. @default 20 */
  compactThreshold?: number
  /** Episodic TTL (ms). @default 7 days */
  episodicTtlMs?: number
}

/**
 * Bridge a {@link LayeredMemory} engine to the conversational pipeline.
 *
 * `recall` returns a compact `[Memory]` bullet block in AIJADE's context style
 * (flat bullets, not XML — weak local models tend to mirror XML wrappers back
 * into replies; see core-agent `formatContextPromptText`). Returns `null` when
 * nothing is relevant so the caller can skip injecting an empty context.
 */
export function createLayeredMemoryPort(
  engine: LayeredMemory,
  opts: LayeredMemoryPortOptions = {},
): MemoryPort {
  const scope = opts.scope ?? 'chat'
  const recallScopes = opts.recallScopes ?? [scope]
  const recallLimit = opts.recallLimit ?? 6
  const minSimilarity = opts.minSimilarity ?? 0.05
  const compactThreshold = opts.compactThreshold ?? 20
  const ttlMs = opts.episodicTtlMs ?? 7 * 24 * 60 * 60 * 1000

  return {
    async recall(query: string) {
      if (!query.trim())
        return null

      const results = await engine.recall(query, {
        scopes: recallScopes,
        limit: recallLimit,
        minSimilarity,
      })
      if (results.length === 0)
        return null

      const lines = results.map(r => `- ${r.scope}: ${r.text}`)
      return ['[Memory]', ...lines].join('\n')
    },

    async ingestUser(text: string, _ts?: number) {
      if (!text.trim())
        return
      await engine.ingestEpisodic(text, { scope, role: 'user', ttlMs })
    },

    async ingestAssistant(text: string, _ts?: number) {
      if (!text.trim())
        return
      await engine.ingestEpisodic(text, { scope, role: 'assistant', ttlMs })
    },

    async maybeCompact() {
      const stats = engine.stats()
      if (stats.episodic >= compactThreshold) {
        await engine.compact({ scope, force: true })
        engine.prune()
      }
    },
  }
}

/**
 * Convenience factory for the default, dependency-free engine (hash embedder +
 * in-memory vector store). Swap for a real embedder + pgvector store in prod.
 */
export function createDefaultLayeredMemory(opts?: LayeredMemoryOptions): LayeredMemory {
  return new LayeredMemory(opts)
}
