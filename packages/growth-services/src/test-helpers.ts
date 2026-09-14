import type { SourceRecord } from '@proj-aijade/memory-biomimetic'

/** Shared helpers for the growth-services tests. Not a test file itself. */
import type { SchedulerPort } from './ports'

/** A scheduler pinned to a fixed clock (and optional budget policy). */
export class FixedScheduler implements SchedulerPort {
  constructor(
    private readonly t: number = 1_700_000_000_000,
    private readonly allowBudget = true,
  ) {}

  now(): number {
    return this.t
  }

  consumeBudget(_scope: string, _amount: number): boolean {
    return this.allowBudget
  }
}

let __n = 0

/** Build a valid SourceRecord for tests. */
export function makeSource(over: Partial<SourceRecord> = {}): SourceRecord {
  __n += 1
  return {
    id: `src_${__n}`,
    schema: 'aijade.source_record@1',
    locator: `https://example.com/doc/${__n}`,
    sourceType: 'web',
    quality: { reliability: 0.7, independence: 0.8, directness: 0.6, recency: 0.7, reproducibility: 0.6 },
    upstreamRefs: [],
    contentHash: `h_${__n}`,
    fetchedAt: 1_700_000_000_000 + __n,
    ...over,
  }
}

export const AGENT = 'agent-test'
export const SCOPE = 'scope-test'
