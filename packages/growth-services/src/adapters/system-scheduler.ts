/**
 * Real scheduler adapter — backs {@link SchedulerPort} with the wall clock and a
 * token-bucket budget ledger that is persisted to disk (so quota survives
 * process restarts). Replaces the in-memory scheduler whose budgets vanish on
 * exit, giving GrowthLoop genuine, durable rate-limiting.
 *
 * `consumeBudget` stays SYNCHRONOUS to honour the port contract (the
 * orchestrator calls it without `await`); persistence uses the synchronous
 * `node:fs` API on a tiny ledger file.
 */

import type { SchedulerPort } from '../ports'

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'

export interface BudgetPolicy {
  /** Maximum tokens the bucket can hold. */
  capacity: number
  /** Refill rate in tokens per second. */
  refillPerSec: number
}

export interface SystemSchedulerOptions {
  /** Per-scope budgets. Unlisted scopes are unlimited. */
  budgets?: Record<string, BudgetPolicy>
  /** Path to persist the ledger (JSON). Omit for in-memory only. */
  ledgerPath?: string
  /** Clock override (for tests). */
  now?: () => number
}

interface LedgerEntry {
  balance: number
  lastRefill: number
}

export class SystemSchedulerAdapter implements SchedulerPort {
  private readonly budgets: Map<string, BudgetPolicy>
  private readonly ledger = new Map<string, LedgerEntry>()
  private readonly ledgerPath?: string
  private readonly nowFn: () => number

  constructor(opts: SystemSchedulerOptions = {}) {
    this.budgets = new Map(Object.entries(opts.budgets ?? {}))
    this.ledgerPath = opts.ledgerPath
    this.nowFn = opts.now ?? Date.now
    if (this.ledgerPath && existsSync(this.ledgerPath)) {
      try {
        const data = JSON.parse(readFileSync(this.ledgerPath, 'utf8')) as Record<string, LedgerEntry>
        for (const [k, v] of Object.entries(data))
          this.ledger.set(k, v)
      }
      catch {
        // Corrupt ledger — start fresh.
      }
    }
  }

  now(): number {
    return this.nowFn()
  }

  consumeBudget(scope: string, amount: number): boolean {
    const policy = this.budgets.get(scope)
    if (!policy)
      return true // unlimited scope

    const now = this.nowFn()
    let entry = this.ledger.get(scope)
    if (!entry) {
      entry = { balance: policy.capacity, lastRefill: now }
      this.ledger.set(scope, entry)
    }

    // Refill based on elapsed time.
    const elapsedSec = Math.max(0, (now - entry.lastRefill) / 1000)
    entry.balance = Math.min(policy.capacity, entry.balance + elapsedSec * policy.refillPerSec)
    entry.lastRefill = now

    if (entry.balance < amount) {
      this.persist()
      return false
    }

    entry.balance -= amount
    this.persist()
    return true
  }

  /** Snapshot of current balances (ops / tests). */
  snapshot(): Record<string, number> {
    const out: Record<string, number> = {}
    for (const [k, v] of this.ledger)
      out[k] = v.balance
    return out
  }

  private persist(): void {
    if (!this.ledgerPath)
      return
    try {
      mkdirSync(dirname(this.ledgerPath), { recursive: true })
      writeFileSync(this.ledgerPath, JSON.stringify(Object.fromEntries(this.ledger)), 'utf8')
    }
    catch {
      // Persistence is best-effort; budgeting still works in-memory.
    }
  }
}
