/**
 * Layered memory data model for AIJADE.
 *
 * Design is informed by the reference projects the user asked us to study:
 * - AkaneCompanionLab: 分层记忆 (近期原话 → 阶段摘要 → 长期语义) with explicit
 *   time ranges and reinforcement ("反复出现会加固").
 * - Hermes Scope-Recall (B 站 BV12ELn6yEmB): scoped, ranked recall rather than
 *   dumping the whole vector store.
 * - "有活人感和长期记忆的 AI 桌宠" (B 站 BV16PEo6rEXi): human-like long-term memory.
 *
 * The model intentionally mirrors AIJADE's own message concepts:
 * - `EpisodicMemory` ~ a verbatim {@link RawMessage} (role + content).
 * - `SummaryMemory` ~ the `summary` history item produced by
 *   `compactConversationEntries` (text with from/to turn indices).
 * - `LongTermMemory` ~ distilled, embedded facts that survive compaction.
 */

/** A scope tag, e.g. `chat` | `game` | `coding` | `general`. Free-form string. */
export type MemoryScope = string

/** Inclusive time window a memory is considered active (epoch ms). */
export interface TimeRange {
  /** First time this memory was observed. */
  firstSeen: number
  /** Last time this memory was observed or recalled. */
  lastSeen: number
}

export interface EpisodicMemory {
  id: string
  tier: 'episodic'
  scope: MemoryScope
  role?: 'system' | 'user' | 'assistant' | 'tool' | 'event'
  text: string
  createdAt: number
  /** Optional expiry (epoch ms) before {@link LayeredMemory.prune} drops it. */
  expiresAt?: number
}

export interface SummaryMemory {
  id: string
  tier: 'summary'
  scope: MemoryScope
  text: string
  fromTurnIndex?: number
  toTurnIndex?: number
  createdAt: number
  /** Episodic ids this summary was compacted from. */
  sourceIds: string[]
}

export interface LongTermMemory {
  id: string
  tier: 'longterm'
  scope: MemoryScope
  text: string
  embedding: number[]
  timeRange: TimeRange
  /**
   * Reinforcement counter. Incremented on every recall (see `reinforce` in
   * {@link RecallOptions}). Drives the salience boost in Scope-Recall, i.e.
   * frequently recalled memories are "consolidated" and rank higher.
   */
  salience: number
  createdAt: number
  lastRecalledAt?: number
  sourceIds: string[]
}

export type AnyMemory = EpisodicMemory | SummaryMemory | LongTermMemory

export interface RecallOptions {
  /** Only recall memories tagged with these scopes. Empty/undefined = all scopes. */
  scopes?: MemoryScope[]
  /** Restrict to memories whose {@link TimeRange} overlaps this window. */
  timeRange?: Partial<TimeRange>
  /** Max number of returned memories. */
  limit?: number
  /** Minimum cosine similarity for long-term candidates (0..1). */
  minSimilarity?: number
  /** If true (default), recalling a long-term memory reinforces it. */
  reinforce?: boolean
  /** Include episodic + summary tiers in results (default true). */
  includeRecent?: boolean
}

export interface RecallResult {
  id: string
  tier: AnyMemory['tier']
  scope: MemoryScope
  text: string
  /** Unified ranking score (long-term: sim × decay × boost; recent: recency). */
  score: number
  similarity?: number
  salience?: number
  timeRange?: TimeRange
}

export interface MemoryStats {
  episodic: number
  summaries: number
  longTerm: number
  vectorStoreSize: number
}
