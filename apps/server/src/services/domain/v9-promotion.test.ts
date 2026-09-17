import type { CandidateVersion, EvaluationEvidencePack, PgcState4, ShadowParamsProposal } from '@proj-aijade/memory-biomimetic'
import type Redis from 'ioredis'

import { PGlite } from '@electric-sql/pglite'
import { drizzle } from 'drizzle-orm/pglite'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { dequeueV9Promotion } from './v9-jobs'
import { createV9PromotionService } from './v9-promotion'

import * as schema from '../../schemas/memory-v9'

type TestDb = Awaited<ReturnType<typeof createDb>>

async function createDb() {
  const client = new PGlite()
  await client.exec(`
    CREATE TABLE "evolution_specs" (
      "id" text PRIMARY KEY,
      "name" text NOT NULL,
      "spec" jsonb NOT NULL,
      "created_at" timestamp NOT NULL DEFAULT NOW()
    );
    CREATE TABLE "eval_reports" (
      "id" text PRIMARY KEY,
      "name" text NOT NULL,
      "metric" jsonb NOT NULL,
      "result" jsonb NOT NULL,
      "created_at" timestamp NOT NULL DEFAULT NOW()
    );
  `)
  return drizzle(client, { schema })
}

function makeProposal(): ShadowParamsProposal {
  return {
    proposalId: 'p1',
    sessionId: 's1',
    inputHash: 'h1',
    candidateParams: { lr: 0.01 },
    confidence: 0.9,
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
} = {}) {
  return {
    jobId: 'job-1',
    input: {
      proposalId: 'p1',
      sessionId: 's1',
      traceId: 't1',
      tick: 1,
      inputHash: 'h1',
      evaluationPack: overrides.evaluationPack ?? makePack(),
      proposal: makeProposal(),
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
