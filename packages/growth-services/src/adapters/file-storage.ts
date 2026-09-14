/**
 * Real persistent storage adapter — backs {@link StoragePort} with JSON files
 * on disk (`node:fs/promises`). Unlike `InMemoryStorage`, every `put` is
 * durable across process restarts, so GrowthLoop's interest threads, quests,
 * claim maps, artifacts and journals actually persist. This is the default
 * "real" store when no PostgreSQL connection is configured.
 */

import type { StoragePort } from '../ports'

import { mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

/** Keep `kind` / `id` within a single directory segment (no path traversal). */
function safe(segment: string): string {
  return segment.replace(/[^\w.-]/g, '_').slice(0, 128)
}

export class FileStorageAdapter implements StoragePort {
  constructor(private readonly rootDir: string) {}

  private dir(kind: string): string {
    return join(this.rootDir, safe(kind))
  }

  private file(kind: string, id: string): string {
    return join(this.dir(kind), `${safe(id)}.json`)
  }

  async put<T>(kind: string, id: string, value: T): Promise<void> {
    await mkdir(this.dir(kind), { recursive: true })
    await writeFile(this.file(kind, id), JSON.stringify(value), 'utf8')
  }

  async get<T>(kind: string, id: string): Promise<T | undefined> {
    try {
      const raw = await readFile(this.file(kind, id), 'utf8')
      return JSON.parse(raw) as T
    }
    catch {
      return undefined
    }
  }

  async list<T>(kind: string): Promise<T[]> {
    try {
      const files = await readdir(this.dir(kind))
      const out: T[] = []
      for (const f of files) {
        if (!f.endsWith('.json'))
          continue
        try {
          out.push(JSON.parse(await readFile(join(this.dir(kind), f), 'utf8')) as T)
        }
        catch {
          // Skip unreadable / corrupt entries.
        }
      }
      return out
    }
    catch {
      return []
    }
  }

  async query<T>(kind: string, pred: (item: T) => boolean): Promise<T[]> {
    return (await this.list<T>(kind)).filter(pred)
  }

  /** Ops / test helper: wipe a single kind. */
  async clearKind(kind: string): Promise<void> {
    await rm(this.dir(kind), { recursive: true, force: true })
  }
}
