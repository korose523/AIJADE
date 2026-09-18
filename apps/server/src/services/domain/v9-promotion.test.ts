import type { CandidateVersion, EvaluationEvidencePack, PgcState4, ShadowParamsProposal } from '@proj-aijade/memory-biomimetic'
import type Redis from 'ioredis'

import { PGlite } from '@electric-sql/pglite'
import { computeLearningInputHash } from '@proj-aijade/memory-biomimetic'
import { drizzle } from 'drizzle-orm/pglite'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { buildMemoryV9Ddl } from '../../schemas/pglite-ddl'
import { dequeueV9Promotion } from './v9-jobs'
import { createV9PromotionService } from './v9-promotion'

import * as schema from '../../schemas/memory-v9'

type TestDb = Awaited<ReturnType<typeof createDb>>

async function createDb() {
  const client = new PGlite()
  await client.exec(buildMemoryV9Ddl())
  return drizzle(client, { schema })
}

/**
 * 夹具必须用**真实**的 `input_hash`，不能编一个字符串。
 *
 * 理由：promotion 的第一道门（`integrity_gate`）会用 `verifyShadowParamsProposalAnchor`
 * 从提案自身字段复算 `input_hash` 并比对。如果夹具里的 hash 是编的，那么**每一条**
 * 测试都会停在 integrity_gate，后面的 EvidenceGate / PGC 门根本不会被触及 ——
 * 测试会"通过"（返回 ok:false），但测的其实不是它们声称要测的那道门。
 * 所以这里一律走与生产者相同的口径。
 */
function makeProposal(overrides: Partial<ShadowParamsProposal> = {}): ShadowParamsProposal {
  const proposalId = overrides.proposalId ?? 'p1'
  const sessionId = overrides.sessionId ?? 's1'
  const candidateParams = overrides.candidateParams ?? { lr: 0.01 }
  return {
    proposalId,
    sessionId,
    inputHash: computeLearningInputHash(sessionId, proposalId, candidateParams),
    anchorKind: 'shadow_params',
    anchorVerified: true,
    candidateParams,
    confidence: 0.9,
    ...overrides,
  }
}

function makePack(overrides: Partial<EvaluationEvidencePack> = {}): EvaluationEvidencePack {
  return {
    id: 'pack-1',
    schema: 'aijade.evaluation_evidence_pack@1',
    proposalRef: 'p1',
    unitContractPropertyTests: { passed: true, total: 10, failed: 0 },
    createdAt: 0,
    traceId: 't1',
    ...overrides,
  }
}

function makeJob(overrides: {
  evaluationPack?: EvaluationEvidencePack
  candidateVersion?: CandidateVersion
  pgcV6State?: PgcState4
  proposal?: ShadowParamsProposal
} = {}) {
  const proposal = overrides.proposal ?? makeProposal()
  return {
    jobId: 'job-1',
    input: {
      proposalId: proposal.proposalId,
      sessionId: proposal.sessionId,
      traceId: 't1',
      tick: 1,
      // 必须与 proposal.inputHash 一致 —— job 头与提案体描述同一个输入快照。
      inputHash: proposal.inputHash,
      evaluationPack: overrides.evaluationPack ?? makePack(),
      proposal,
      candidateVersion: overrides.candidateVersion,
      pgcV6State: overrides.pgcV6State,
    },
  }
}

async function countSpecs(db: TestDb): Promise<number> {
  return (await db.select().from(schema.v9EvolutionSpecs)).length
}

async function countReports(db: TestDb): Promise<number> {
  return (await db.select().from(schema.v9EvalReports)).length
}

describe('v9 promotion service', () => {
  let db: TestDb

  beforeEach(async () => {
    db = await createDb()
  })

  it('refuses when core unit/contract/property tests fail and writes nothing', async () => {
    const svc = createV9PromotionService({ db: db as never })
    const res = await svc.process(makeJob({
      evaluationPack: makePack({ unitContractPropertyTests: { passed: false, total: 10, failed: 3 } }),
    }))
    expect(res.ok).toBe(false)
    expect(res.stage).toBe('evidence_gate')
    expect(await countSpecs(db)).toBe(0)
    expect(await countReports(db)).toBe(0)
  })

  it('promotes when all gates pass and PGC commit_possible is true', async () => {
    const svc = createV9PromotionService({ db: db as never })
    const cv: CandidateVersion = {
      id: 'cv1',
      deltaQuality: 0.5,
      deltaLatency: 0,
      deltaCost: 0,
      risk: 0,
      complexity: 0,
      drift: 0,
      safety: 1,
      baselineSafety: 1,
      coreInvariantsHold: true,
      rollbackAvailable: true,
    }
    // f = 0 ⇒ w_raw = rho0·(1+dot)·1 ≥ commit_min_w ⇒ commit_possible.
    const res = await svc.process(makeJob({ candidateVersion: cv, pgcV6State: { a: 0, c: 0, d: 0, f: 0 } }))
    expect(res.ok).toBe(true)
    expect(res.stage).toBe('promoted')
    expect(res.evolutionSpecId).toBe('evospec_p1')
    expect(res.evalReportId).toBe('evalrep_p1')
    expect(await countSpecs(db)).toBe(1)
    expect(await countReports(db)).toBe(1)
    const specs = await db.select().from(schema.v9EvolutionSpecs)
    expect(specs[0].name).toBe('shadow-promotion:p1')
    expect((specs[0].spec as { selectedCandidateVersionId?: string }).selectedCandidateVersionId).toBe('cv1')
  })

  it('refuses when an optional gate (securitySandbox) fails and writes nothing', async () => {
    const svc = createV9PromotionService({ db: db as never })
    const res = await svc.process(makeJob({
      evaluationPack: makePack({ securitySandbox: { passed: false, escapes: 2 } }),
      pgcV6State: { a: 0, c: 0, d: 0, f: 0 },
    }))
    expect(res.ok).toBe(false)
    expect(res.stage).toBe('evidence_gate')
    expect(await countSpecs(db)).toBe(0)
    expect(await countReports(db)).toBe(0)
  })

  it('refuses when PGC commit_possible is false (low w / high fatigue) and carries commit_reason', async () => {
    const svc = createV9PromotionService({ db: db as never })
    // f = 0.95 ⇒ w_raw < 0 (kappa·f > 1) ⇒ w = 0 ⇒ commit_possible false.
    const res = await svc.process(makeJob({ pgcV6State: { a: 0, c: 0, d: 0, f: 0.95 } }))
    expect(res.ok).toBe(false)
    expect(res.stage).toBe('pgc_gate')
    expect(res.reason).toContain('commit rejected')
    expect(res.reason).toMatch(/w_below_theta|evidence_insufficient|w_max_below_theta|contradiction_high|fatigue_deferred/)
    expect(await countSpecs(db)).toBe(0)
    expect(await countReports(db)).toBe(0)
  })

  // ---------------------------------------------------------------------------
  // integrity_gate —— 这一组的关键不是"拒绝"，而是"拒绝不是因为别的门也在拒"。
  // 所有"通过"的用例都必须真的走到 promoted；所有"该被 integrity_gate 拒"的用例
  // 必须精确停在 integrity_gate，而不是恰好被 EvidenceGate 或 PGC 门拦住。
  // ---------------------------------------------------------------------------

  it('promotes all the way to persisted rows, proving the happy path is not silently stopped at integrity_gate', async () => {
    const svc = createV9PromotionService({ db: db as never })
    // 全套门都必须真通过：integrity → evidence → pgc → 落 2 行。
    const res = await svc.process(makeJob({ pgcV6State: { a: 0, c: 0, d: 0, f: 0 } }))
    expect(res.stage).toBe('promoted')
    expect(await countSpecs(db)).toBe(1)
    expect(await countReports(db)).toBe(1)
  })

  it('refuses when the proposal input_hash does not match its own body (tampered queue payload)', async () => {
    const svc = createV9PromotionService({ db: db as never })
    const honest = makeProposal()
    // 模拟"队列里的提案被人改过"：改 body 但保留旧 hash（或反之）。
    const tampered: ShadowParamsProposal = { ...honest, candidateParams: { lr: 0.99 } }
    expect(tampered.inputHash).toBe(honest.inputHash) // 值确实没变，是 body 被改了

    const res = await svc.process(makeJob({ proposal: tampered, pgcV6State: { a: 0, c: 0, d: 0, f: 0 } }))
    expect(res.ok).toBe(false)
    expect(res.stage).toBe('integrity_gate')
    expect(res.reason).toContain('input_hash mismatch')
    expect(await countSpecs(db)).toBe(0)
    expect(await countReports(db)).toBe(0)
  })

  it('refuses when the job header inputHash disagrees with the proposal body', async () => {
    const svc = createV9PromotionService({ db: db as never })
    const job = makeJob({ pgcV6State: { a: 0, c: 0, d: 0, f: 0 } })
    const res = await svc.process({
      ...job,
      input: { ...job.input, inputHash: 'some-other-snapshot' },
    })
    expect(res.ok).toBe(false)
    expect(res.stage).toBe('integrity_gate')
    expect(res.reason).toContain('disagrees with proposal')
    expect(await countSpecs(db)).toBe(0)
    expect(await countReports(db)).toBe(0)
  })

  it('refuses an evidence-anchor proposal whose derived hash no longer matches its body', async () => {
    const svc = createV9PromotionService({ db: db as never })
    // evidence 分支没有生产方声明的 input_hash，所以它的锚点是**可复算**而非可对比的；
    // 一旦有人改了 claim_text 而没重算，这里必须拦住（此前这条路径完全没有闸门）。
    const evidenceAnchor = computeLearningInputHash('s1', 'p1', { evidence_hash: 'eh1', claim_text: 'original claim' })
    const proposal: ShadowParamsProposal = {
      proposalId: 'p1',
      sessionId: 's1',
      inputHash: evidenceAnchor,
      anchorKind: 'evidence',
      anchorVerified: false,
      candidateParams: {},
      confidence: 0.9,
      evidenceHash: 'eh1',
      claimText: 'tampered claim',
    }
    const res = await svc.process(makeJob({ proposal, pgcV6State: { a: 0, c: 0, d: 0, f: 0 } }))
    expect(res.ok).toBe(false)
    expect(res.stage).toBe('integrity_gate')
    expect(res.reason).toContain('evidence input_hash mismatch')
    expect(await countSpecs(db)).toBe(0)
    expect(await countReports(db)).toBe(0)
  })

  it('refuses an evidence-anchor proposal that is missing its anchor fields (cannot-recompute is not a pass)', async () => {
    const svc = createV9PromotionService({ db: db as never })
    const proposal: ShadowParamsProposal = {
      proposalId: 'p1',
      sessionId: 's1',
      inputHash: 'whatever',
      anchorKind: 'evidence',
      anchorVerified: false,
      candidateParams: {},
      confidence: 0.9,
      // evidenceHash / claimText 均缺失 ⇒ 算不出来 ⇒ 必须拒绝，而不是跳过。
    }
    const res = await svc.process(makeJob({ proposal, pgcV6State: { a: 0, c: 0, d: 0, f: 0 } }))
    expect(res.ok).toBe(false)
    expect(res.stage).toBe('integrity_gate')
    expect(res.reason).toContain('cannot be recomputed')
    expect(await countSpecs(db)).toBe(0)
    expect(await countReports(db)).toBe(0)
  })

  it('honours an evidence-anchor proposal whose hash is honest (the gate is not "always refuse")', async () => {
    const svc = createV9PromotionService({ db: db as never })
    const body = { evidence_hash: 'eh1', claim_text: 'original claim' }
    const proposal: ShadowParamsProposal = {
      proposalId: 'p1',
      sessionId: 's1',
      inputHash: computeLearningInputHash('s1', 'p1', body),
      anchorKind: 'evidence',
      anchorVerified: false,
      candidateParams: {},
      confidence: 0.9,
      evidenceHash: 'eh1',
      claimText: 'original claim',
    }
    const res = await svc.process(makeJob({ proposal, pgcV6State: { a: 0, c: 0, d: 0, f: 0 } }))
    expect(res.stage).toBe('promoted')
    expect(await countSpecs(db)).toBe(1)
    expect(await countReports(db)).toBe(1)
  })
})

describe('dequeueV9Promotion', () => {
  it('throws when the payload is not valid JSON', async () => {
    const fakeRedis = { brpop: vi.fn().mockResolvedValue(['aijade:v9:promotion', 'not json{']) } as unknown as Redis
    await expect(dequeueV9Promotion(fakeRedis)).rejects.toThrow()
  })

  it('throws when required keys are missing', async () => {
    const fakeRedis = {
      brpop: vi.fn().mockResolvedValue(['aijade:v9:promotion', JSON.stringify({ foo: 'bar' })]),
    } as unknown as Redis
    await expect(dequeueV9Promotion(fakeRedis)).rejects.toThrow('invalid v9 promotion job payload')
  })
})
