/**
 * Real port composition.
 *
 * `makeRealPorts` assembles a production `GrowthPorts` bundle from the genuine
 * backend adapters, with graceful degradation:
 *
 *   storage   → PostgreSQL (`AIJADE_PGVECTOR_URL`) when configured, else
 *               durable file storage under `<dataDir>/storage`.
 *   search    → `memory-pgvector` layered-memory retrieval (seeded from a
 *               corpus and/or a local knowledge directory).
 *   signing   → HMAC-SHA256 (node:crypto).
 *   scheduler → wall clock + persistent token-bucket budget ledger.
 *   llm       → Ollama / OpenAI-compatible chat (local model by default).
 *
 * `makeRealGrowthLoop` wires those ports into the GrowthLoop orchestrator.
 */

import type { GrowthPorts, LlmPort } from '../ports'
import type { CorpusItem } from './pgvector-search'
import type { BudgetPolicy } from './system-scheduler'

import process from 'node:process'

import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { GrowthLoop } from '../growth-loop'
import { StubLlm } from '../in-memory'
import { CryptoSigningAdapter } from './crypto-signing'
import { FileStorageAdapter } from './file-storage'
import { OllamaLlmAdapter } from './ollama-llm'
import { PostgresStorageAdapter } from './pg-storage'
import { PgVectorSearchAdapter } from './pgvector-search'
import { SystemSchedulerAdapter } from './system-scheduler'

export interface RealPortsOptions {
  /** Root directory for file storage + scheduler ledger. @default $AIJADE_DATA_DIR or os temp. */
  dataDir?: string
  /** Signing secret (else `AIJADE_SIGNING_SECRET`). */
  signingSecret?: string
  /** Ollama/OpenAI client config (else env). */
  llm?: { baseURL?: string, model?: string }
  /** Use the deterministic stub LLM instead of a real model (tests / offline). */
  stubLlm?: boolean
  /** Pre-built LLM adapter to inject directly (overrides `llm`/`stubLlm`). */
  llmInstance?: LlmPort
  /** Per-scope budget policies. */
  budgets?: Record<string, BudgetPolicy>
  /** Corpus to seed the retrieval backend with. */
  searchCorpus?: CorpusItem[]
  /** Load a corpus from a local directory of documents. */
  searchDir?: string
}

export function makeRealPorts(opts: RealPortsOptions = {}): GrowthPorts {
  const dataDir = opts.dataDir ?? process.env.AIJADE_DATA_DIR ?? join(tmpdir(), 'aijade-growth')

  const storage = PostgresStorageAdapter.fromEnv() ?? new FileStorageAdapter(join(dataDir, 'storage'))

  const search = new PgVectorSearchAdapter({
    corpus: opts.searchCorpus,
    searchDir: opts.searchDir,
  })

  const signing = new CryptoSigningAdapter(opts.signingSecret)

  const scheduler = new SystemSchedulerAdapter({
    budgets: opts.budgets ?? {
      // A modest per-hour budget for the growth loop by default.
      growth_loop: { capacity: 50, refillPerSec: 50 / 3600 },
    },
    ledgerPath: join(dataDir, 'scheduler-ledger.json'),
  })

  const llm: LlmPort = opts.llmInstance
    ?? (opts.stubLlm ? new StubLlm() : new OllamaLlmAdapter(opts.llm))

  return { storage, search, signing, scheduler, llm }
}

/** Build a GrowthLoop backed by the real (or stubbed) port adapters. */
export function makeRealGrowthLoop(
  opts: RealPortsOptions,
  agentId: string,
  userScope: string,
): GrowthLoop {
  return new GrowthLoop(makeRealPorts(opts), agentId, userScope)
}
