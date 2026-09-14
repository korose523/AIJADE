/**
 * In-memory / stub implementations of the product-layer ports.
 *
 * These are the default adapters injected into the growth services during tests
 * and for local runs. They are deterministic and require no external services.
 */

import type {
  GrowthPorts,
  LlmPort,
  RawHit,
  SchedulerPort,
  SearchPort,
  SigningPort,
  StoragePort,
} from './ports'

import { fnv1a } from './util'

/** A single namespace of keyed values, kept in a plain Map. */
interface Bucket {
  values: Map<string, unknown>
}

/** In-memory persistence: an in-process key/value store partitioned by kind. */
export class InMemoryStorage implements StoragePort {
  private readonly buckets = new Map<string, Bucket>()

  private bucket(kind: string): Bucket {
    let b = this.buckets.get(kind)
    if (!b) {
      b = { values: new Map() }
      this.buckets.set(kind, b)
    }
    return b
  }

  async put<T>(kind: string, id: string, value: T): Promise<void> {
    this.bucket(kind).values.set(id, value)
  }

  async get<T>(kind: string, id: string): Promise<T | undefined> {
    return this.bucket(kind).values.get(id) as T | undefined
  }

  async list<T>(kind: string): Promise<T[]> {
    return [...this.bucket(kind).values.values()] as T[]
  }

  async query<T>(kind: string, pred: (item: T) => boolean): Promise<T[]> {
    return (await this.list<T>(kind)).filter(pred)
  }

  /** Test helper: read the whole bucket (not part of the port contract). */
  all<T>(kind: string): T[] {
    return [...this.bucket(kind).values.values()] as T[]
  }
}

/** In-memory search over a seed list of hits. */
export class InMemorySearch implements SearchPort {
  private readonly index: RawHit[]

  constructor(seed: RawHit[] = []) {
    this.index = [...seed]
  }

  async search(query: string, sourceTypes: string[]): Promise<RawHit[]> {
    const q = query.trim().toLowerCase()
    const types = new Set(sourceTypes)
    return this.index.filter((hit) => {
      const typeOk = types.size === 0 || types.has(hit.sourceType)
      const textOk = q.length === 0 || hit.content.toLowerCase().includes(q) || hit.locator.toLowerCase().includes(q)
      return typeOk && textOk
    })
  }
}

/**
 * HMAC-style string signing. Deterministically signs a JSON-serialised payload
 * together with a private secret (FNV-1a over `payload + ':' + secret`). Verifying
 * recomputes the same digest. This is a deliberately simple stand-in for a real
 * detached-signature scheme — enough to exercise the signing / release contracts.
 */
export class InMemorySigning implements SigningPort {
  private readonly secret: string

  constructor(secret = 'aijade-growth-inmemory-secret') {
    this.secret = secret
  }

  sign(payload: unknown): string {
    const body = JSON.stringify(payload)
    return `sig_${fnv1a(`${body}:${this.secret}`)}`
  }

  verify(payload: unknown, sig: string): boolean {
    return this.sign(payload) === sig
  }
}

/**
 * In-memory scheduler: a clock and a set of named budgets.
 *
 * `consumeBudget` draws down a scope's remaining units; when a scope has no
 * budget registered it is treated as unlimited (so tests that do not configure a
 * budget never stall). Configure a finite scope to exercise the exhaustion path.
 */
export class InMemoryScheduler implements SchedulerPort {
  private readonly budgets = new Map<string, number>()
  private readonly unlimited = new Set<string>()

  constructor(budgets: Record<string, number> = {}) {
    for (const [scope, amount] of Object.entries(budgets)) this.budgets.set(scope, amount)
  }

  /** Register a scope as unlimited (default if unregistered). */
  markUnlimited(scope: string): void {
    this.unlimited.add(scope)
  }

  now(): number {
    return Date.now()
  }

  consumeBudget(scope: string, amount: number): boolean {
    if (this.unlimited.has(scope) || !this.budgets.has(scope))
      return true
    const remaining = this.budgets.get(scope) as number
    if (remaining < amount)
      return false
    this.budgets.set(scope, remaining - amount)
    return true
  }
}

/**
 * Deterministic stub LLM. By default it returns a short, stable acknowledgement
 * so planning / synthesis steps can run without a real model. Tests may override
 * `handler` to return canned completions.
 */
export class StubLlm implements LlmPort {
  /** Optional handler override; receives the prompt and returns the completion. */
  handler: ((prompt: string) => string) | null = null

  async complete(prompt: string): Promise<string> {
    if (this.handler)
      return this.handler(prompt)
    const preview = prompt.slice(0, 64).replace(/\s+/g, ' ').trim()
    return `[stub-completion] acknowledged: ${preview}`
  }
}

/** Build a ready-to-inject default port bundle for tests / local runs. */
export function defaultPorts(opts: {
  searchSeed?: RawHit[]
  budgets?: Record<string, number>
  llm?: StubLlm
} = {}): GrowthPorts {
  return {
    storage: new InMemoryStorage(),
    search: new InMemorySearch(opts.searchSeed ?? []),
    signing: new InMemorySigning(),
    scheduler: new InMemoryScheduler(opts.budgets ?? {}),
    llm: opts.llm ?? new StubLlm(),
  }
}
