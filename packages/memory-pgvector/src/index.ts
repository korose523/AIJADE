import process from 'node:process'

import { Format, LogLevel, setGlobalFormat, setGlobalLogLevel } from '@guiiai/logg'
import { Client } from '@proj-aijade/server-sdk'
import { runUntilSignal } from '@proj-aijade/server-sdk/utils/node'

import { LayeredMemory } from './engine'

export * from './performance'
export { createDefaultLayeredMemory, createLayeredMemoryPort } from './port'

setGlobalFormat(Format.Pretty)
setGlobalLogLevel(LogLevel.Log)

/**
 * The layered memory engine. In production you would inject a real embedding
 * function (e.g. `@xsai/embeddings`) and a pgvector-backed `VectorStore` here;
 * the defaults (hash embedder + in-memory store) keep the module runnable and
 * fully testable without external services.
 */
const memory = new LayeredMemory()

async function main() {
  // `connectionString` is supplied by the runtime when a PostgreSQL backend is
  // configured; a future pgvector adapter can read it to back the engine.
  const client = new Client<{ connectionString: string }>({
    name: 'memory-pgvector',
  })

  client.onEvent('module:configure', (_event) => {
    // Acknowledge configuration and surface engine capabilities. The actual
    // recall/ingest handlers can be wired to the module protocol here once the
    // request/response contract is finalised.
    console.log('[memory-pgvector] layered memory engine ready', memory.stats())
  })

  runUntilSignal()

  process.on('SIGINT', () => client.close())
  process.on('SIGTERM', () => client.close())
}

main()

export { LayeredMemory, memory }
