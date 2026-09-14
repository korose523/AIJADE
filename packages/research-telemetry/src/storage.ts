/**
 * Pluggable persistence for turn records.
 *
 * Three adapters are provided so the same experiment code runs unchanged in
 * every target the project supports:
 *
 * - `createMemoryStorage()`   — tests, and short in-browser runs.
 * - `createFileStorage()`     — Electron main process / Node services. Writes
 *                               JSONL (one record per line) so a crash mid-run
 *                               never loses earlier turns — important when a
 *                               single session is meant to last weeks.
 * - `createIndexedDbStorage()`— browser / Electron renderer. Survives reloads,
 *                               which a weeks-long web study requires.
 *
 * JSONL is the on-disk format everywhere: it is append-only, diffable, and
 * directly loadable by pandas / R / DuckDB without a parser.
 */

import type { SessionMeta, TurnRecord } from './types'

export interface TelemetryStorage {
  /** Persist (or refresh) session metadata. */
  saveSession: (session: SessionMeta) => Promise<void>
  /** Append a single turn record. */
  appendTurn: (record: TurnRecord) => Promise<void>
  /** All turns for a session, ordered by turnIndex. */
  readTurns: (sessionId: string) => Promise<TurnRecord[]>
  /** All known sessions. */
  readSessions: () => Promise<SessionMeta[]>
  /** Drop everything (used between pilot runs). */
  clear: () => Promise<void>
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export function createMemoryStorage(): TelemetryStorage {
  const sessions = new Map<string, SessionMeta>()
  const turns = new Map<string, TurnRecord[]>()

  return {
    async saveSession(session) {
      sessions.set(session.sessionId, { ...session })
    },
    async appendTurn(record) {
      const list = turns.get(record.sessionId) ?? []
      list.push({ ...record })
      turns.set(record.sessionId, list)
    },
    async readTurns(sessionId) {
      return [...(turns.get(sessionId) ?? [])].sort((a, b) => a.turnIndex - b.turnIndex)
    },
    async readSessions() {
      return [...sessions.values()]
    },
    async clear() {
      sessions.clear()
      turns.clear()
    },
  }
}

// ---------------------------------------------------------------------------
// File (Node / Electron main) — append-only JSONL
// ---------------------------------------------------------------------------

export interface FileStorageOptions {
  /** Directory that will hold `sessions.jsonl` and `turns.jsonl`. */
  dir: string
  /** Injectable fs, so tests can pass a stub. Defaults to `node:fs/promises`. */
  fs?: {
    mkdir: (path: string, opts: { recursive: boolean }) => Promise<unknown>
    appendFile: (path: string, data: string) => Promise<unknown>
    readFile: (path: string, encoding: 'utf8') => Promise<string>
    writeFile: (path: string, data: string) => Promise<unknown>
  }
}

export function createFileStorage(options: FileStorageOptions): TelemetryStorage {
  const dir = options.dir

  // Lazily resolved so the package stays importable in a browser bundle.
  let fsPromise: Promise<NonNullable<FileStorageOptions['fs']>> | undefined
  function getFs(): Promise<NonNullable<FileStorageOptions['fs']>> {
    if (options.fs)
      return Promise.resolve(options.fs)
    fsPromise ??= import('node:fs/promises').then(m => m as unknown as NonNullable<FileStorageOptions['fs']>)
    return fsPromise
  }

  const sessionsPath = `${dir}/sessions.jsonl`
  const turnsPath = `${dir}/turns.jsonl`

  // Serialise all writes through one chain: concurrent appendFile calls on the
  // same fd can interleave and corrupt lines.
  let writeChain: Promise<unknown> = Promise.resolve()
  function enqueue(task: () => Promise<unknown>): Promise<void> {
    writeChain = writeChain.then(task, task)
    return writeChain.then(() => undefined)
  }

  async function ensureDir(): Promise<void> {
    const fs = await getFs()
    await fs.mkdir(dir, { recursive: true })
  }

  async function readLines(path: string): Promise<string[]> {
    const fs = await getFs()
    try {
      const raw = await fs.readFile(path, 'utf8')
      return raw.split('\n').filter(l => l.trim().length > 0)
    }
    catch {
      // File does not exist yet — a fresh experiment directory.
      return []
    }
  }

  return {
    async saveSession(session) {
      await ensureDir()
      const line = `${JSON.stringify(session)}\n`
      await enqueue(async () => {
        const fs = await getFs()
        // Sessions are rewritten in full so re-saving an updated meta (e.g.
        // endedAt) does not leave duplicates.
        const others = (await readLines(sessionsPath))
          .map(l => JSON.parse(l) as SessionMeta)
          .filter(s => s.sessionId !== session.sessionId)
        const all = [...others, session]
          .sort((a, b) => a.startedAt - b.startedAt)
          .map(s => JSON.stringify(s))
          .join('\n')
        await fs.writeFile(sessionsPath, `${all}\n`)
      })
      void line
    },
    async appendTurn(record) {
      await ensureDir()
      const line = `${JSON.stringify(record)}\n`
      await enqueue(async () => {
        const fs = await getFs()
        await fs.appendFile(turnsPath, line)
      })
    },
    async readTurns(sessionId) {
      const lines = await readLines(turnsPath)
      return lines
        .map(l => JSON.parse(l) as TurnRecord)
        .filter(r => r.sessionId === sessionId)
        .sort((a, b) => a.turnIndex - b.turnIndex)
    },
    async readSessions() {
      const lines = await readLines(sessionsPath)
      return lines.map(l => JSON.parse(l) as SessionMeta)
    },
    async clear() {
      await ensureDir()
      await enqueue(async () => {
        const fs = await getFs()
        await fs.writeFile(sessionsPath, '')
        await fs.writeFile(turnsPath, '')
      })
    },
  }
}

// ---------------------------------------------------------------------------
// IndexedDB (browser / Electron renderer)
// ---------------------------------------------------------------------------

export interface IndexedDbStorageOptions {
  dbName?: string
  /** Injectable factory; defaults to globalThis.indexedDB. */
  indexedDB?: IDBFactory
}

/**
 * Minimal IndexedDB adapter (no external dependency).
 *
 * Store layout:
 *   `sessions` — keyPath `sessionId`
 *   `turns`    — autoIncrement, index `sessionId`
 */
export function createIndexedDbStorage(options: IndexedDbStorageOptions = {}): TelemetryStorage {
  const dbName = options.dbName ?? 'airi-research-telemetry'
  const VERSION = 1

  function open(): Promise<IDBDatabase> {
    const factory = options.indexedDB ?? globalThis.indexedDB
    if (!factory)
      return Promise.reject(new Error('indexedDB is not available in this environment'))
    return new Promise((resolve, reject) => {
      const req = factory.open(dbName, VERSION)
      req.onupgradeneeded = () => {
        const db = req.result
        if (!db.objectStoreNames.contains('sessions'))
          db.createObjectStore('sessions', { keyPath: 'sessionId' })
        if (!db.objectStoreNames.contains('turns')) {
          const store = db.createObjectStore('turns', { autoIncrement: true })
          store.createIndex('sessionId', 'sessionId', { unique: false })
        }
      }
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    })
  }

  function tx<T>(
    db: IDBDatabase,
    store: string,
    mode: IDBTransactionMode,
    run: (s: IDBObjectStore) => IDBRequest<T>,
  ): Promise<T> {
    return new Promise((resolve, reject) => {
      const t = db.transaction(store, mode)
      const req = run(t.objectStore(store))
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    })
  }

  return {
    async saveSession(session) {
      const db = await open()
      try {
        await tx(db, 'sessions', 'readwrite', s => s.put(session) as IDBRequest<IDBValidKey>)
      }
      finally {
        db.close()
      }
    },
    async appendTurn(record) {
      const db = await open()
      try {
        await tx(db, 'turns', 'readwrite', s => s.add(record) as IDBRequest<IDBValidKey>)
      }
      finally {
        db.close()
      }
    },
    async readTurns(sessionId) {
      const db = await open()
      try {
        const all = await tx(db, 'turns', 'readonly', s => s.getAll() as IDBRequest<TurnRecord[]>)
        return all.filter(r => r.sessionId === sessionId).sort((a, b) => a.turnIndex - b.turnIndex)
      }
      finally {
        db.close()
      }
    },
    async readSessions() {
      const db = await open()
      try {
        return await tx(db, 'sessions', 'readonly', s => s.getAll() as IDBRequest<SessionMeta[]>)
      }
      finally {
        db.close()
      }
    },
    async clear() {
      const db = await open()
      try {
        await tx(db, 'sessions', 'readwrite', s => s.clear() as unknown as IDBRequest<undefined>)
        await tx(db, 'turns', 'readwrite', s => s.clear() as unknown as IDBRequest<undefined>)
      }
      finally {
        db.close()
      }
    },
  }
}

/**
 * Pick a sensible default adapter for the current runtime.
 *
 * Order: explicit override → Node/Electron main (file) → browser (IndexedDB)
 * → memory.
 */
export function createDefaultStorage(
  override?: TelemetryStorage,
  fileOptions?: Omit<FileStorageOptions, 'fs'>,
): TelemetryStorage {
  if (override)
    return override
  const hasNodeFs = typeof process !== 'undefined' && !!process.versions?.node
  if (hasNodeFs && fileOptions?.dir)
    return createFileStorage(fileOptions)
  if (typeof globalThis !== 'undefined' && globalThis.indexedDB)
    return createIndexedDbStorage()
  return createMemoryStorage()
}
