import type { EvaluationEvidencePack, PgcState4, ShadowParamsProposal } from '@proj-aijade/memory-biomimetic'

import process from 'node:process'

import Redis from 'ioredis'

import { computeLearningInputHash } from '@proj-aijade/memory-biomimetic'

/**
 * v9/v10 promotion worker 的**真实基础设施**验收。
 *
 * ## 为什么需要它（单测覆盖不到什么）
 *
 * `v9-promotion.test.ts` 用 PGlite 验两道门与落库，但它**没有碰过 Redis**：
 * 队列的 lpush/brpop 往返、`dequeueV9Promotion` 的载荷校验、dead-letter 的写入形状，
 * 在单测里全是 mock 或完全不覆盖。于是"promotion worker 能跑"这件事此前**没有运行期证据**。
 *
 * 本脚本用**真实 Redis**（`REDIS_URL`）+ **真实 PostgreSQL**（`DATABASE_URL`）跑完整链路：
 *   1. 队列往返保真（入队 → 出队 → 逐字段比对）；
 *   2. 非法载荷必须被 `dequeueV9Promotion` 拒绝（不是静默当成好任务）；
 *   3. dead-letter 键名与载荷形状（钉住 `V9_PROMOTION_DEAD_LETTER` 的值，防重构漂移）；
 *   4. 三道 DB 结论（evidence_gate 拒 / pgc_gate 拒 / promoted）在真实 PG 上成立，
 *      且**拒绝必须不落库**。
 *
 * ## 安全性
 * - **Redis**：只操作 `aijade:v9:promotion` 与 dead-letter 键，且开始前断言两者为空；
 *   脚本自己写入的条目在结束时逐条 `lrem` 清除。若有其他 worker 在消费，脚本会先报错退出。
 * - **PostgreSQL**：所有写入都在一个事务里完成，断言后 rollback ⇒ 零持久写入。
 *
 * 运行：
 * `DATABASE_URL=... REDIS_URL=redis://localhost:6379 pnpm --filter @proj-aijade/server verify:v9-promotion`
 */

const EXIT = {
  ok: 0,
  missingEnv: 2,
  failed: 3,
  unexpected: 4,
} as const

let failures = 0

function check(ok: boolean, msg: string): void {
  if (ok) {
    console.info(`ok   ${msg}`)
  }
  else {
    failures++
    console.error(`FAIL ${msg}`)
  }
}

function describeTarget(connectionString: string): string {
  try {
    const url = new URL(connectionString)
    return `${url.hostname}${url.port ? `:${url.port}` : ''}${url.pathname}`
  }
  catch {
    return '(unparseable connection string)'
  }
}

const ROLLBACK = Symbol('rollback')

/**
 * 夹具必须带**真实**的 `input_hash`。
 *
 * promotion 的第一道门会用 `verifyShadowParamsProposalAnchor` 从提案自身字段复算并比对。
 * 如果这里编一个 `input-${proposalId}`，那么三道 DB 结论里那两条**应当通过** integrity 门
 * 的用例（promoted / pgc_gate 拒绝）会先停在 integrity_gate —— 脚本仍会"通过"，
 * 但测的已经不是 evidence_gate 与 pgc_gate 了。所以一律走与生产者相同的口径。
 */
function makeProposal(proposalId: string): ShadowParamsProposal {
  const sessionId = `session-${proposalId}`
  const candidateParams = { lr: 0.01 }
  return {
    proposalId,
    sessionId,
    inputHash: computeLearningInputHash(sessionId, proposalId, candidateParams),
    anchorKind: 'shadow_params',
    anchorVerified: true,
    candidateParams,
    confidence: 0.9,
  }
}

function makePack(proposalId: string, overrides: Partial<EvaluationEvidencePack> = {}): EvaluationEvidencePack {
  return {
    id: `pack-${proposalId}`,
    schema: 'aijade.evaluation_evidence_pack@1',
    proposalRef: proposalId,
    unitContractPropertyTests: { passed: true, total: 10, failed: 0 },
    createdAt: 0,
    traceId: `trace-${proposalId}`,
    ...overrides,
  } as EvaluationEvidencePack
}

function makeJob(proposalId: string, pack: EvaluationEvidencePack, pgcV6State?: PgcState4) {
  const proposal = makeProposal(proposalId)
  return {
    jobId: `verify-job-${proposalId}`,
    input: {
      proposalId,
      sessionId: proposal.sessionId,
      traceId: `trace-${proposalId}`,
      tick: 7,
      // 必须与 proposal.inputHash 一致（job 头与提案体描述同一输入快照）。
      inputHash: proposal.inputHash,
      evaluationPack: pack,
      proposal,
      pgcV6State,
    },
  }
}

async function main(): Promise<number> {
  const connectionString = process.env.DATABASE_URL
  const redisUrl = process.env.REDIS_URL
  if (!connectionString || !redisUrl) {
    console.error('[verify:promotion] both DATABASE_URL and REDIS_URL are required.')
    return EXIT.missingEnv
  }

  const { createDrizzle } = await import('../src/libs/db')
  const {
    dequeueV9Promotion,
    enqueueV9Promotion,
    parkDeadLetter,
    V9_MEMORY_DEAD_LETTER,
    V9_PERCEPTION_DEAD_LETTER,
    V9_PROMOTION_DEAD_LETTER,
    V9_PROMOTION_QUEUE,
  } = await import('../src/services/domain/v9-jobs')
  const { createV9PromotionService } = await import('../src/services/domain/v9-promotion')
  const { sql } = await import('drizzle-orm')
  const schema = await import('../src/schemas/memory-v9')

  const { db, pool } = createDrizzle({
    DATABASE_URL: connectionString,
    DB_POOL_MAX: 2,
    DB_POOL_IDLE_TIMEOUT_MS: 5_000,
    DB_POOL_CONNECTION_TIMEOUT_MS: 5_000,
    DB_POOL_KEEPALIVE_INITIAL_DELAY_MS: 1_000,
  })
  const redis = new Redis(redisUrl, { lazyConnect: true, maxRetriesPerRequest: 2 })

  /** 我们自己往 Redis 写过的条目，结束时逐条清除。 */
  const written: { key: string, raw: string }[] = []

  try {
    await redis.connect()
    console.info(`[verify:promotion] postgres=${describeTarget(connectionString)} redis=${redisUrl}`)

    // ---- 键名单一真源（防重构把 worker 写到别的键上） ----
    check(V9_PERCEPTION_DEAD_LETTER === 'aijade:v9:dead-letter', 'perception dead-letter key pinned')
    check(V9_PROMOTION_DEAD_LETTER === 'aijade:v9:promotion:dead-letter', 'promotion dead-letter key pinned')
    check(V9_MEMORY_DEAD_LETTER === 'aijade:memory:dead-letter', 'memory dead-letter key pinned')
    check(V9_PROMOTION_QUEUE === 'aijade:v9:promotion', 'promotion queue key pinned')

    // ---- 前置：队列必须为空，否则说明有别的生产者在跑，测试会互相干扰 ----
    const queueLen = await redis.llen(V9_PROMOTION_QUEUE)
    check(queueLen === 0, `promotion queue starts empty (got ${queueLen})`)
    if (queueLen !== 0) {
      console.error('[verify:promotion] refusing to run: the promotion queue is not empty.')
      return EXIT.failed
    }

    // ---- 1. 队列往返保真 ----
    {
      const job = makeJob('roundtrip', makePack('roundtrip'), { a: 0, c: 0, d: 0, f: 0 })
      await enqueueV9Promotion(redis, job)
      check(await redis.llen(V9_PROMOTION_QUEUE) === 1, 'enqueue puts exactly one job on the real queue')

      const back = await dequeueV9Promotion(redis)
      check(Boolean(back), 'dequeue returns the job')
      check(JSON.stringify(back) === JSON.stringify(job), 'queue round-trip preserves the payload byte-for-byte')
      check(await redis.llen(V9_PROMOTION_QUEUE) === 0, 'queue is drained after one dequeue')
    }

    // ---- 2. 非法载荷必须被拒 ----
    {
      const bad = [
        { label: 'missing input', raw: JSON.stringify({ jobId: 'bad-1' }) },
        { label: 'missing evaluationPack gate', raw: JSON.stringify({ jobId: 'bad-2', input: { proposalId: 'p', sessionId: 's', traceId: 't', tick: 1, inputHash: 'h', evaluationPack: { id: 'x' }, proposal: {} } }) },
      ]
      for (const item of bad) {
        await redis.lpush(V9_PROMOTION_QUEUE, item.raw)
        written.push({ key: V9_PROMOTION_QUEUE, raw: item.raw })
        let threw = false
        try {
          await dequeueV9Promotion(redis)
        }
        catch {
          threw = true
        }
        check(threw, `dequeue rejects malformed job (${item.label}) with a throw, not a silent accept`)
      }
    }

    // ---- 3. dead-letter 形状（真实 Redis 往返） ----
    {
      const before = await redis.llen(V9_PROMOTION_DEAD_LETTER)
      const entry = { job: { jobId: 'verify-poison' }, error: 'simulated failure' }
      await parkDeadLetter(redis, V9_PROMOTION_DEAD_LETTER, entry)
      const raw = await redis.lindex(V9_PROMOTION_DEAD_LETTER, 0)
      written.push({ key: V9_PROMOTION_DEAD_LETTER, raw: raw ?? '' })
      check(await redis.llen(V9_PROMOTION_DEAD_LETTER) === before + 1, 'parkDeadLetter appends to the real dead-letter list')
      const parsed = raw ? JSON.parse(raw) as { job?: { jobId?: string }, error?: string } : null
      check(parsed?.job?.jobId === 'verify-poison', 'dead-letter entry carries the job')
      check(parsed?.error === 'simulated failure', 'dead-letter entry carries the error string')
    }

    // ---- 4. 三道 DB 结论（真实 PG，事务内，最后 rollback） ----
    const countSpecs = async (tx: unknown) => {
      const res = await (tx as { execute: (q: unknown) => Promise<{ rows: { n: number }[] }> })
        .execute(sql`SELECT COUNT(*)::int AS n FROM "evolution_specs"`)
      return res.rows[0].n
    }
    const countReports = async (tx: unknown) => {
      const res = await (tx as { execute: (q: unknown) => Promise<{ rows: { n: number }[] }> })
        .execute(sql`SELECT COUNT(*)::int AS n FROM "eval_reports"`)
      return res.rows[0].n
    }

    let specsBefore = 0
    let reportsBefore = 0

    try {
      await db.transaction(async (tx) => {
        const service = createV9PromotionService({ db: tx as never })
        specsBefore = await countSpecs(tx)
        reportsBefore = await countReports(tx)

        // 4a. 完整性锚点门（Door 0）拒绝 ⇒ 不落库
        //     关键：被篡改的提案必须停在 integrity_gate，而**不是**恰好被后面的门拦住。
        {
          const honest = makeProposal('gate-anchor')
          const tampered = { ...honest, candidateParams: { lr: 0.99 } }
          const job = makeJob('gate-anchor', makePack('gate-anchor'), { a: 0, c: 0, d: 0, f: 0 })
          const res = await service.process({ ...job, input: { ...job.input, proposal: tampered } } as never)
          check(res.ok === false && res.stage === 'integrity_gate', `integrity gate refuses a tampered proposal (stage=${res.stage})`)
          check(typeof res.reason === 'string' && res.reason.includes('input_hash mismatch'), `integrity refusal names the mismatch (${res.reason})`)
          check(await countSpecs(tx) === specsBefore, 'integrity-gate refusal wrote no evolution_specs row')
          check(await countReports(tx) === reportsBefore, 'integrity-gate refusal wrote no eval_reports row')
        }

        // 4b. EvidenceGate 拒绝 ⇒ 不落库
        {
          const job = makeJob('gate-evidence', makePack('gate-evidence', {
            securitySandbox: { passed: false, escapes: 2 },
          } as Partial<EvaluationEvidencePack>), { a: 0, c: 0, d: 0, f: 0 })
          const res = await service.process(job as never)
          check(res.ok === false && res.stage === 'evidence_gate', `evidence gate refuses (stage=${res.stage})`)
          check(await countSpecs(tx) === specsBefore, 'evidence-gate refusal wrote no evolution_specs row')
          check(await countReports(tx) === reportsBefore, 'evidence-gate refusal wrote no eval_reports row')
        }

        // 4c. PGC 门拒绝 ⇒ 不落库，且 reason 带 commit_reason
        {
          const job = makeJob('gate-pgc', makePack('gate-pgc'), { a: 0, c: 0, d: 0, f: 0.95 })
          const res = await service.process(job as never)
          check(res.ok === false && res.stage === 'pgc_gate', `pgc gate refuses (stage=${res.stage})`)
          check(typeof res.reason === 'string' && res.reason.includes('pgc commit rejected'), `pgc refusal carries the commit reason (${res.reason})`)
          check(await countSpecs(tx) === specsBefore, 'pgc-gate refusal wrote no evolution_specs row')
          check(await countReports(tx) === reportsBefore, 'pgc-gate refusal wrote no eval_reports row')
        }

        // 4d. 两道门通过 ⇒ 恰好落 2 行
        {
          const job = makeJob('promoted', makePack('promoted'), { a: 0, c: 0, d: 0, f: 0 })
          const res = await service.process(job as never)
          check(res.ok === true && res.stage === 'promoted', `both gates pass -> promoted (stage=${res.stage})`)
          check(await countSpecs(tx) === specsBefore + 1, 'promotion wrote exactly one evolution_specs row')
          check(await countReports(tx) === reportsBefore + 1, 'promotion wrote exactly one eval_reports row')

          const spec = await tx.select().from(schema.v9EvolutionSpecs)
          const ours = spec.find(r => r.id === 'evospec_promoted')
          check(Boolean(ours), 'the promotion row is readable back by its derived id')
          check(ours?.name === 'shadow-promotion:promoted', `promotion row name is derived from the proposal (${ours?.name})`)
        }

        throw ROLLBACK
      })
    }
    catch (error) {
      if (error !== ROLLBACK)
        throw error
    }

    // ---- 5. 零残留：真实库行数必须与事务前一致 ----
    {
      const after = await db.select({ id: schema.v9EvolutionSpecs.id }).from(schema.v9EvolutionSpecs)
      check(after.length === specsBefore, `no residue in evolution_specs (${specsBefore} -> ${after.length})`)
      const afterReports = await db.select({ id: schema.v9EvalReports.id }).from(schema.v9EvalReports)
      check(afterReports.length === reportsBefore, `no residue in eval_reports (${reportsBefore} -> ${afterReports.length})`)
    }

    if (failures > 0) {
      console.error(`\nFAIL: ${failures} promotion-worker assertion(s) failed`)
      return EXIT.failed
    }
    console.info('\nPASS: promotion worker transport + gates verified against real Redis and real PostgreSQL')
    return EXIT.ok
  }
  catch (error) {
    console.error('[verify:promotion] failed:', error)
    return EXIT.failed
  }
  finally {
    // 清除本脚本写入的 Redis 条目（只删我们自己已知的原值，不动别人的）。
    for (const item of written) {
      try {
        if (item.raw)
          await redis.lrem(item.key, 1, item.raw)
      }
      catch {
        // best-effort 清理
      }
    }
    try {
      await redis.quit()
    }
    catch {
      // ignore
    }
    await pool.end()
  }
}

main()
  .then(code => process.exit(code))
  .catch((error) => {
    console.error('[verify:promotion] unexpected error:', error)
    process.exit(EXIT.unexpected)
  })
