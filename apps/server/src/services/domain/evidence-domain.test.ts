import { PGlite } from '@electric-sql/pglite'
import { drizzle } from 'drizzle-orm/pglite'
import { beforeEach, describe, expect, it } from 'vitest'

import { buildMemoryV9Ddl } from '../../schemas/pglite-ddl'
import { createEvidenceDomainService, verifyEvidenceRefsPure } from './evidence-domain'

import * as schema from '../../schemas/memory-v9'

/**
 * 复核报告 R3 / 核对项 3.2：独立「证据态引用域」校验。
 * - 纯函数侧：`verifyEvidenceRefsPure` 无库即可测（悬空引用 / 去重 / 空集）。
 * - 查询侧：PGlite 真库种子数据 → 快照 → 校验闭环（引用域确实"可查询"）。
 */

function makeDomain(over: Partial<Parameters<typeof verifyEvidenceRefsPure>[1]> = {}) {
  return {
    sessionId: 's-1',
    evidencePackIds: [],
    evidenceChunkIds: [],
    beliefIds: [],
    memoryVersionIds: [],
    graphHashes: [],
    ...over,
  }
}

describe('verifyEvidenceRefsPure（引用域一致性 · 纯函数）', () => {
  it('全部引用落在域内 ⇒ ok 且 missing 为空', () => {
    const domain = makeDomain({ evidenceChunkIds: ['c-1', 'c-2'], beliefIds: ['b-1'], graphHashes: ['gh-1'] })
    expect(verifyEvidenceRefsPure(['c-1', 'b-1', 'gh-1'], domain)).toEqual({ ok: true, missing: [] })
  })

  it('悬空引用 ⇒ ok=false 且逐个列出（宁缺勿伪造）', () => {
    const domain = makeDomain({ evidencePackIds: ['p-1'] })
    const v = verifyEvidenceRefsPure(['p-1', 'ghost-1', 'ghost-2'], domain)
    expect(v.ok).toBe(false)
    expect(v.missing).toEqual(['ghost-1', 'ghost-2'])
  })

  it('重复引用去重判定；空引用集恒 ok', () => {
    const domain = makeDomain({ evidenceChunkIds: ['c-1'] })
    expect(verifyEvidenceRefsPure(['c-1', 'c-1'], domain).ok).toBe(true)
    expect(verifyEvidenceRefsPure([], domain)).toEqual({ ok: true, missing: [] })
  })
})

describe('getEvidenceDomain（PGlite · 会话级引用域快照）', () => {
  let db: ReturnType<typeof drizzle>

  beforeEach(async () => {
    const client = new PGlite()
    await client.exec(buildMemoryV9Ddl())
    db = drizzle(client, { schema })
  })

  it('种子证据态可被快照查询，且引用域闭环校验通过；跨会话引用不入域', async () => {
    const svc = createEvidenceDomainService(db as never)

    // 种子：s-1 的 pack/chunk；s-2 的 pack（不得混入 s-1 的域）。
    await db.insert(schema.v9EvidencePacks).values([
      { id: 'p-1', sessionId: 's-1', source: 'webpage_text' },
      { id: 'p-2', sessionId: 's-2', source: 'video_transcript' },
    ])
    await db.insert(schema.v9EvidenceChunks).values([
      { id: 'c-1', packId: 'p-1', idx: '0', content: 'text' },
      { id: 'c-2', packId: 'p-2', idx: '0', content: 'other session' },
    ])
    await db.insert(schema.v9Beliefs).values([{
      id: 'b-1',
      proposition: 'the page claims X',
      scope: 'session:s-1',
      confidence: '0.8',
      logit: '1.4',
      status: 'hypothesis',
      owner: 'agent',
      evidenceIds: ['c-1'],
      counterEvidenceIds: [],
      validFrom: new Date(),
    }])
    // 会话内因果链：tx → version → weave（graph_hash）。
    await db.insert(schema.v9PgcStates).values({
      id: 'pgc-1',
      sessionId: 's-1',
      traceId: 'tr-1',
      policyVersion: 'v1',
      components: {},
      v6State: {},
    })
    await db.insert(schema.v9MemoryTxs).values({
      id: 'tx-1',
      sessionId: 's-1',
      traceId: 'tr-1',
      atomicity: 'bundle',
      maxWrites: '8',
      status: 'committed',
    })
    await db.insert(schema.v9MemoryVersions).values({
      id: 'mv-1',
      memoryTxId: 'tx-1',
      memoryItemId: 'mi-1',
      memoryWriteId: 'mw-1',
      memoryKind: 'long_term',
      contentHashSha256: 'h-1',
      evidencePackId: 'p-1',
      evidenceIds: ['c-1'],
      pgcStateId: 'pgc-1',
      intensity: '0.5',
      durability: '0.5',
    })
    await db.insert(schema.v9EvidenceWeaves).values({
      id: 'w-1',
      txId: 'tx-1',
      graphHash: 'gh-1',
      spec: {},
      links: {},
    })

    const domain = await svc.getEvidenceDomain('s-1')
    expect(domain.evidencePackIds).toEqual(['p-1'])
    expect(domain.evidenceChunkIds).toEqual(['c-1'])
    expect(domain.beliefIds).toEqual(['b-1'])
    expect(domain.memoryVersionIds).toEqual(['mv-1'])
    expect(domain.graphHashes).toEqual(['gh-1'])

    // 域内引用全过；跨会话 chunk（c-2）与幽灵引用被判悬空。
    expect(svc.verifyEvidenceRefs(['p-1', 'c-1', 'b-1', 'mv-1', 'gh-1'], domain).ok).toBe(true)
    const v = svc.verifyEvidenceRefs(['c-2', 'ghost'], domain)
    expect(v.ok).toBe(false)
    expect(v.missing).toEqual(['c-2', 'ghost'])
  })

  it('空会话 ⇒ 空域快照，任何引用都判悬空（不伪造）', async () => {
    const svc = createEvidenceDomainService(db as never)
    const domain = await svc.getEvidenceDomain('empty-session')
    expect(domain.evidencePackIds).toEqual([])
    expect(svc.verifyEvidenceRefs(['anything'], domain).ok).toBe(false)
  })
})
