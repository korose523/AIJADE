/**
 * Persistence for the skill library.
 *
 * The upstream registry is an in-memory `Map`. Anything measured across
 * sessions therefore vanishes on restart, which is why no learning curve can
 * currently be drawn. These adapters make the library durable.
 *
 * JSONL is the default on-disk format for the same reason as in
 * `research-telemetry`: append-only, crash-safe, diffable, and loadable
 * directly by pandas / R / DuckDB.
 *
 * The interface is intentionally narrow (`upsert` / `get` / `all`) so a SQLite
 * or Postgres adapter can be dropped in later without touching callers —
 * which matters because a weeks-long study will accumulate enough records to
 * make linear scans uncomfortable.
 */

import type { SkillRecord } from './types'

export interface SkillStore {
  upsert: (record: SkillRecord) => Promise<void>
  get: (skillId: string) => Promise<SkillRecord | undefined>
  all: () => Promise<SkillRecord[]>
  /** Replace the whole store — used by tests and by pilot-run resets. */
  replaceAll: (records: readonly SkillRecord[]) => Promise<void>
  clear: () => Promise<void>
}

export function createMemorySkillStore(initial: readonly SkillRecord[] = []): SkillStore {
  const map = new Map<string, SkillRecord>(initial.map(r => [r.skillId, { ...r }]))

  return {
    async upsert(record) {
      map.set(record.skillId, { ...record })
    },
    async get(skillId) {
      const found = map.get(skillId)
      return found ? { ...found } : undefined
    },
    async all() {
      return [...map.values()].map(r => ({ ...r }))
    },
    async replaceAll(records) {
      map.clear()
      for (const r of records)
        map.set(r.skillId, { ...r })
    },
    async clear() {
      map.clear()
    },
  }
}

export interface JsonlSkillStoreOptions {
  /** Full path including filename, e.g. `<dir>/skills.jsonl`. */
  file: string
  fs?: {
    mkdir: (path: string, opts: { recursive: boolean }) => Promise<unknown>
    appendFile: (path: string, data: string) => Promise<unknown>
    readFile: (path: string, encoding: 'utf8') => Promise<string>
    writeFile: (path: string, data: string) => Promise<unknown>
  }
}

/**
 * JSONL-backed store with an in-memory index.
 *
 * Writes are append-only for speed, but `upsert` on an existing id must not
 * duplicate the record. We therefore append a new revision and rebuild the
 * file, keeping the last revision per id. For the record volumes of a single
 * participant this is cheap; if a study outgrows it, swap in SQLite — the
 * `SkillStore` interface is unchanged.
 */
export function createJsonlSkillStore(options: JsonlSkillStoreOptions): SkillStore {
  const file = options.file
  const dir = file.replace(/\/[^/]+$/, '')

  let fsPromise: Promise<NonNullable<JsonlSkillStoreOptions['fs']>> | undefined
  function getFs(): Promise<NonNullable<JsonlSkillStoreOptions['fs']>> {
    if (options.fs)
      return Promise.resolve(options.fs)
    fsPromise ??= import('node:fs/promises').then(m => m as unknown as NonNullable<JsonlSkillStoreOptions['fs']>)
    return fsPromise
  }

  // Serialise writes; interleaved append/write on one path corrupts lines.
  let chain: Promise<unknown> = Promise.resolve()
  function enqueue(task: () => Promise<unknown>): Promise<void> {
    chain = chain.then(task, task)
    return chain.then(() => undefined)
  }

  async function readAll(): Promise<SkillRecord[]> {
    const fs = await getFs()
    try {
      const raw = await fs.readFile(file, 'utf8')
      return raw
        .split('\n')
        .filter(l => l.trim().length > 0)
        .map(l => JSON.parse(l) as SkillRecord)
    }
    catch {
      return []
    }
  }

  async function writeAll(records: readonly SkillRecord[]): Promise<void> {
    const fs = await getFs()
    await fs.mkdir(dir, { recursive: true })
    const body = records.map(r => `${JSON.stringify(r)}\n`).join('')
    await fs.writeFile(file, body)
  }

  return {
    async upsert(record) {
      return enqueue(async () => {
        const all = await readAll()
        const idx = all.findIndex(r => r.skillId === record.skillId)
        if (idx >= 0)
          all[idx] = record
        else
          all.push(record)
        await writeAll(all)
      })
    },
    async get(skillId) {
      const all = await readAll()
      return all.find(r => r.skillId === skillId)
    },
    async all() {
      return readAll()
    },
    async replaceAll(records) {
      return enqueue(() => writeAll(records))
    },
    async clear() {
      return enqueue(() => writeAll([]))
    },
  }
}
