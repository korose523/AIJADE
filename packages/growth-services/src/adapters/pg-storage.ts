/**
 * Real PostgreSQL storage adapter (opt-in) — backs {@link StoragePort} with a
 * `jsonb` key/value table. Activated only when `AIJADE_PGVECTOR_URL` (or
 * `DATABASE_URL`) is set; otherwise `PostgresStorageAdapter.fromEnv()` returns
 * `null` and the caller falls back to {@link FileStorageAdapter}.
 *
 * Uses the `postgres` client (already a workspace dependency via
 * `memory-pgvector`). The table is created lazily on first write.
 */

import type { Sql } from 'postgres'

import type { StoragePort } from '../ports'

import process from 'node:process'

import postgres from 'postgres'

const DEFAULT_TABLE = 'aijade_growth_kv'

export class PostgresStorageAdapter implements StoragePort {
  /**
   * Build a Postgres-backed store from the environment, or `null` when no
   * connection string is configured (caller should fall back to file storage).
   */
  static fromEnv(opts?: { table?: string }): PostgresStorageAdapter | null {
    const url = process.env.AIJADE_PGVECTOR_URL ?? process.env.DATABASE_URL
    if (!url)
      return null
    return new PostgresStorageAdapter(url, opts)
  }

  private readonly sql: Sql
  private readonly table: string
  private initialized = false

  constructor(url: string, opts?: { table?: string }) {
    this.sql = postgres(url, { max: 1, onnotice: () => {} })
    this.table = opts?.table ?? DEFAULT_TABLE
  }

  private async ensureTable(): Promise<void> {
    if (this.initialized)
      return
    await this.sql.unsafe(
      `CREATE TABLE IF NOT EXISTS ${this.table} (kind text, id text, value jsonb, primary key (kind, id))`,
    )
    this.initialized = true
  }

  async put<T>(kind: string, id: string, value: T): Promise<void> {
    await this.ensureTable()
    await this.sql`
      INSERT INTO ${this.sql(this.table)} (kind, id, value)
      VALUES (${kind}, ${id}, ${this.sql.json(value as never)})
      ON CONFLICT (kind, id) DO UPDATE SET value = EXCLUDED.value
    `
  }

  async get<T>(kind: string, id: string): Promise<T | undefined> {
    await this.ensureTable()
    const rows = await this.sql<{ value: T }[]>`
      SELECT value FROM ${this.sql(this.table)} WHERE kind = ${kind} AND id = ${id}
    `
    return rows[0] ? rows[0].value : undefined
  }

  async list<T>(kind: string): Promise<T[]> {
    await this.ensureTable()
    const rows = await this.sql<{ value: T }[]>`
      SELECT value FROM ${this.sql(this.table)} WHERE kind = ${kind}
    `
    return rows.map(r => r.value)
  }

  async query<T>(kind: string, pred: (item: T) => boolean): Promise<T[]> {
    return (await this.list<T>(kind)).filter(pred)
  }

  /** Close the underlying connection pool (call on shutdown). */
  async close(): Promise<void> {
    await this.sql.end()
  }
}
