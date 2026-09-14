import type { StorageAdapter, StoreSnapshotV1 } from './types'

import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'

/**
 * v7 §26 存储分层（Storage Tiering）— 具体存储适配器。
 *
 * `StorageAdapter`（接口定义在 `./types`）是 store 唯一依赖的抽象；本文件提供两种
 * 实现：内存适配器（默认、测试用）与 JSON 文件适配器（Node，进程级持久化）。
 *
 * 设计要点（与 H2c 兼容护盾一致）：
 * - 适配器**只承载**状态，绝不决定保留期 / 显著性 —— 那是 HAC（§9.3）的职责。
 * - 所有方法同步：持久化不得进入记忆门控路径，避免 I/O 抖动污染可复现实验。
 * - 快照是可序列化的纯数据（`StoreSnapshotV1`），不含任何函数 / 类实例 / 循环引用。
 */

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

/** In-memory adapter — the default for tests and the "no persistence" baseline. */
export class InMemoryStorageAdapter implements StorageAdapter {
  readonly kind = 'memory'
  private snapshot: StoreSnapshotV1 | null = null

  persist(snapshot: StoreSnapshotV1): void {
    this.snapshot = clone(snapshot)
  }

  load(): StoreSnapshotV1 | null {
    return this.snapshot ? clone(this.snapshot) : null
  }

  clear(): void {
    this.snapshot = null
  }
}

/** File-backed adapter (Node). Persists a single JSON snapshot per path. */
export class JsonFileStorageAdapter implements StorageAdapter {
  readonly kind = 'json-file'
  constructor(private readonly filePath: string) {}

  persist(snapshot: StoreSnapshotV1): void {
    writeFileSync(this.filePath, JSON.stringify(snapshot), 'utf8')
  }

  load(): StoreSnapshotV1 | null {
    try {
      return JSON.parse(readFileSync(this.filePath, 'utf8')) as StoreSnapshotV1
    }
    catch {
      return null
    }
  }

  clear(): void {
    try {
      unlinkSync(this.filePath)
    }
    catch {
      // Not present — nothing to clear.
    }
  }
}
