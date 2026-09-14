/**
 * Real backend adapters for the growth-services product layer.
 *
 * Each adapter implements one of the ports in `../ports` against a genuine
 * backend (Ollama LLM, node:crypto signing, persistent disk/Postgres storage,
 * persistent budget scheduler, memory-pgvector retrieval). `in-memory.ts`
 * remains the deterministic default for unit tests; these are for real runs.
 */

export * from './crypto-signing'
export * from './file-storage'
export * from './ollama-llm'
export * from './pg-storage'
export * from './pgvector-search'
export * from './real-ports'
export * from './system-scheduler'
