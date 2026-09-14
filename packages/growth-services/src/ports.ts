/**
 * Product-layer I/O ports.
 *
 * The growth services deliberately do NOT touch the outside world directly — they
 * depend only on these small, explicit port interfaces. Concrete adapters (in
 * `in-memory.ts` for tests, or real DB / web / LLM adapters in production) are
 * injected through the constructors. This keeps the services pure, deterministic
 * and unit-testable against stubs.
 */

/** A raw hit returned by a search adapter (untrusted external content). */
export interface RawHit {
  /** Locator (URL, DOI, local path, tool result ref). */
  locator: string
  /** Coarse source type (official_doc | paper | news | code | social | tool | …). */
  sourceType: string
  /** The fetched content body (used to derive a content hash). */
  content: string
  /** Epoch ms when the hit was fetched. */
  fetchedAt: number
}

/** External search / retrieval. Returns untrusted content to be quarantined. */
export interface SearchPort {
  /** Search `query` across the given `sourceTypes`. */
  search: (query: string, sourceTypes: string[]) => Promise<RawHit[]>
}

/** Generic persistence. The product layer never assumes a concrete store. */
export interface StoragePort {
  /** Persist `value` under `kind`/`id`. */
  put: <T>(kind: string, id: string, value: T) => Promise<void>
  /** Load a single value by `kind`/`id`, or undefined when absent. */
  get: <T>(kind: string, id: string) => Promise<T | undefined>
  /** List every value stored under `kind`. */
  list: <T>(kind: string) => Promise<T[]>
  /** List every value under `kind` matching `pred`. */
  query: <T>(kind: string, pred: (item: T) => boolean) => Promise<T[]>
}

/** Detached-signature port (used to sign evolution proposals / releases). */
export interface SigningPort {
  /** Produce a deterministic signature over an arbitrary payload. */
  sign: (payload: unknown) => string
  /** Verify that `sig` is the signature of `payload`. */
  verify: (payload: unknown, sig: string) => boolean
}

/** Time + budget control (a tiny scheduler/quota surface). */
export interface SchedulerPort {
  /** Current epoch-ms clock. */
  now: () => number
  /** Attempt to draw `amount` from the named budget scope; false if insufficient. */
  consumeBudget: (scope: string, amount: number) => boolean
}

/** LLM surface for planning / synthesis / candidate generation (testable stub). */
export interface LlmPort {
  /** Complete a prompt; returns generated text. */
  complete: (prompt: string) => Promise<string>
}

/** Bundle of ports a service may need. Services take only the subset they use. */
export interface GrowthPorts {
  storage: StoragePort
  search: SearchPort
  signing: SigningPort
  scheduler: SchedulerPort
  llm: LlmPort
}
