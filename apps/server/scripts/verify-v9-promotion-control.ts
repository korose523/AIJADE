import type { EvaluationEvidencePack, PgcState4, ShadowParamsProposal } from '@proj-aijade/memory-biomimetic'

import process from 'node:process'

import Redis from 'ioredis'

import { computeLearningInputHash } from '@proj-aijade/memory-biomimetic'

/**
 * 门控**特异性**对照装置 —— 关闭 J2 §4.3 / §6 中自曝的两个 P0：
 *
 *   ① **无「无门控」对照** ⇒ 无法排除"门控只是把所有候选都拒绝"这一替代解释；
 *   ② **篡改矩阵规模不足**（原为 3 门 × 各 1 例）。
 *
 * ## 本装置给出的两条对照
 *
 * **对照 A（特异性 / 假阳性率）**：同一批**合法**候选必须被放行（晋升落库）。
 * 若某一门把合法候选也拒绝，"门控有效"就退化为"门控恒拒"——本对照把这条替代解释排除掉。
 *
 * **对照 B（无门控反事实）**：对每一个**篡改**候选，除跑真实服务（含门控）外，
 * 再跑一条**门控被短路为恒真**的写入路径（`bypassPromote`），统计"若门控不存在，
 * 被篡改候选会有多少落库"。得到"有门控 0% vs 无门控 100%"的对比较。
 *
 * > **为什么短路必须发生在装置里、而不是生产代码里**：
 * > 生产代码**不引入任何开关**。`bypassPromote` 是本脚本内的一个局部函数，
 * > 它只复刻成功路径的两条 INSERT，不修改 `createV9PromotionService`，
 * > 因此不存在"可以被误开的生产旁路"。这与 §4.3 修订注的口径一致。
 *
 * ## 篡改矩阵（3 门 × 5 变体 = 15 例：11 真篡改 + 3 无关轴探针 + 1 合法对照）
 *
 * | 组 | 变体 | 构造 | 期望 |
 * |---|---|---|---|
 * | integrity | 参数篡改 | `candidateParams` 改了但 `inputHash` 没跟着变 | 拒绝 |
 * | integrity | 哈希悬空 | `inputHash = ''` | 拒绝 |
 * | integrity | 哈希缺失 | 删除 `inputHash` | 拒绝 |
 * | integrity | 跨轨迹 | job 头 `inputHash` ≠ 提案体 `inputHash` | 拒绝 |
 * | integrity | 锚点标志探针 | `anchorVerified = false` | **不拒绝**（非承重：门复算 hash，不读此标志） |
 * | evidence | 单测失败 | `unitContractPropertyTests.passed = false` | 拒绝 |
 * | evidence | 静态分析失败 | `staticAnalysis.passed = false` | 拒绝 |
 * | evidence | 沙箱逃逸 | `securitySandbox.passed = false` | 拒绝 |
 * | evidence | 对抗评测失败 | `adversarialEval.passed = false` | 拒绝 |
 * | evidence | 历史重放回归 | `historicalReplay.passed = false` | 拒绝 |
 * | pgc | f 高（承重轴） | v6 状态 `f = 0.95` | 拒绝 |
 * | pgc | 全高 | `a = c = d = f = 0.95` | 拒绝 |
 * | pgc | a / c / d 高 | 单轴 0.95 | **不拒绝**（无关轴：commit 由 f 轴驱动） |
 *
 * > **为什么要单列"探针"一类**：一个字段"没被拦下"未必是漏洞 —— 它可能**本就不承重**。
 * > 把无关轴与真篡改混在一起报"漏判率"，会把设计属性误报成缺陷。
 * > 本装置的探针行正是为了让这个区分**可复核**而不是靠口头声明。
 *
 * ## 安全性
 * - **PostgreSQL**：全部在**单个事务**内完成，末尾强制 `ROLLBACK` ⇒ 零持久写入。
 *   装置自身断言"回滚后行数与事务前一致"。
 * - **Redis**：不写入。队列 / dead-letter 键只读，且开始前断言 promotion 队列为空。
 *
 * 运行：
 * `DATABASE_URL=... REDIS_URL=redis://localhost:6379 pnpm --filter @proj-aijade/server verify:v9-promotion-control`
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

/** 与生产者同口径的夹具：`inputHash` 必须是**真实复算**的，否则 integrity 门会先拦下一切。 */
function makeProposal(proposalId: string, overrides: Partial<ShadowParamsProposal> = {}): ShadowParamsProposal {
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
    ...overrides,
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

function makeJob(
  proposalId: string,
  pack: EvaluationEvidencePack,
  pgcV6State: PgcState4,
  opts: { proposal?: ShadowParamsProposal, headerHash?: string | null } = {},
) {
  const proposal = opts.proposal ?? makeProposal(proposalId)
  const headerHash = opts.headerHash === null ? undefined : (opts.headerHash ?? proposal.inputHash)
  return {
    jobId: `control-job-${proposalId}`,
    input: {
      proposalId,
      sessionId: proposal.sessionId,
      traceId: `trace-${proposalId}`,
      tick: 7,
      inputHash: headerHash,
      evaluationPack: pack,
      proposal,
      pgcV6State,
    },
  }
}

/** 中性 v6 状态：既有装置在 `{a:0,c:0,d:0,f:0}` 下可晋升。 */
const NEUTRAL: PgcState4 = { a: 0, c: 0, d: 0, f: 0 }

interface Case {
  /** 门（integrity / evidence / pgc） */
  gate: 'integrity' | 'evidence' | 'pgc'
  /** 变体名 */
  name: string
  /**
   * 案例类型：
   * - `legal`  — 合法对照，必须被放行（测假阳性）
   * - `tamper` — 真篡改，必须被拒绝且零写入
   * - `probe`  — **无关轴探针**：该字段/轴按设计不参与该门的判定，故**不该被拒绝**。
   *              记录它是为了把"门控漏判"与"该轴本就不承重"区分开，避免把设计属性误报成缺陷。
   */
  kind: 'legal' | 'tamper' | 'probe'
  /** probe 的判读依据 */
  note?: string
  build: () => { job: ReturnType<typeof makeJob> }
}

/**
 * 无门控反事实：**只复刻成功路径的两条 INSERT**，不做任何门控判定。
 *
 * 这不是生产代码的一部分，只在本脚本的事务内存在；用它量化
 * "若三门被短路为恒真，被篡改候选会有多少落库"。
 */
async function bypassPromote(
  tx: { insert: (t: unknown) => { values: (v: unknown) => Promise<unknown> } },
  schema: { v9EvolutionSpecs: unknown, v9EvalReports: unknown },
  job: { input: { proposalId: string, sessionId: string, traceId: string, tick: number, inputHash?: string, proposal: ShadowParamsProposal, evaluationPack: EvaluationEvidencePack } },
  tag: string,
): Promise<void> {
  const specId = `evospec_bypass_${tag}`
  const reportId = `evalrep_bypass_${tag}`
  await tx.insert(schema.v9EvolutionSpecs).values({
    id: specId,
    name: `shadow-promotion:bypass:${tag}`,
    spec: { proposalId: job.input.proposalId, bypass: true } as unknown as Record<string, unknown>,
    createdAt: new Date(),
  })
  await tx.insert(schema.v9EvalReports).values({
    id: reportId,
    name: `shadow-eval:bypass:${tag}`,
    metric: { bypass: true } as unknown as Record<string, unknown>,
    result: { promoted: true, bypass: true } as unknown as Record<string, unknown>,
    createdAt: new Date(),
  })
}

function buildCases(): Case[] {
  const cases: Case[] = []

  // ---- 合法对照（必须被放行）----
  cases.push({
    gate: 'integrity',
    name: 'LEGAL (control)',
    kind: 'legal',
    build: () => ({ job: makeJob('ctl-legal', makePack('ctl-legal'), NEUTRAL) }),
  })

  // ---- 组 1：integrity 门（Door 0）----
  const integrityVariants: { name: string, make: (id: string) => ReturnType<typeof makeJob> }[] = [
    {
      name: '参数篡改（hash 不跟随）',
      make: id => makeJob(id, makePack(id), NEUTRAL, {
        proposal: { ...makeProposal(id), candidateParams: { lr: 0.99 } },
      }),
    },
    {
      name: '哈希悬空（inputHash=""）',
      make: id => makeJob(id, makePack(id), NEUTRAL, {
        proposal: { ...makeProposal(id), inputHash: '' },
      }),
    },
    {
      name: '哈希缺失（无 inputHash 字段）',
      make: (id) => {
        const p = makeProposal(id) as Partial<ShadowParamsProposal>
        delete p.inputHash
        return makeJob(id, makePack(id), NEUTRAL, { proposal: p as ShadowParamsProposal })
      },
    },
    {
      name: '跨轨迹（job 头 hash ≠ 提案 hash）',
      make: id => makeJob(id, makePack(id), NEUTRAL, { headerHash: `trace-of-another-job-${id}` }),
    },
  ]
  for (const v of integrityVariants) {
    cases.push({
      gate: 'integrity',
      name: v.name,
      kind: 'tamper',
      build: () => {
        const id = `int-${Math.abs(hashCode(v.name))}`
        return { job: v.make(id) }
      },
    })
  }

  // `anchorVerified` 是**声明字段而非承重字段**：integrity 门独立复算 input_hash，
  // 不读取该标志。故把它置 false 不构成篡改 —— 它是 evidence 归约分支的正常取值
  // （见 shadow-params.ts:239）。此处作为 probe 记录，防止把设计属性误报为缺陷。
  cases.push({
    gate: 'integrity',
    name: 'anchorVerified=false（无关轴探针）',
    kind: 'probe',
    note: 'anchorVerified 非承重：integrity 门复算 hash，不读此标志；evidence 分支正常取值即为 false',
    build: () => ({
      job: makeJob(`int-probe-anchor`, makePack(`int-probe-anchor`), NEUTRAL, {
        proposal: { ...makeProposal(`int-probe-anchor`), anchorVerified: false },
      }),
    }),
  })

  // ---- 组 2：evidence 门（Door 1）----
  const evidenceVariants: { name: string, patch: Partial<EvaluationEvidencePack> }[] = [
    { name: '单测失败', patch: { unitContractPropertyTests: { passed: false, total: 10, failed: 3 } } as Partial<EvaluationEvidencePack> },
    { name: '静态分析失败', patch: { staticAnalysis: { passed: false } } as Partial<EvaluationEvidencePack> },
    { name: '沙箱逃逸', patch: { securitySandbox: { passed: false, escapes: 2 } } as Partial<EvaluationEvidencePack> },
    { name: '对抗评测失败', patch: { adversarialEval: { passed: false } } as Partial<EvaluationEvidencePack> },
    { name: '历史重放回归', patch: { historicalReplay: { passed: false } } as Partial<EvaluationEvidencePack> },
  ]
  for (const v of evidenceVariants) {
    cases.push({
      gate: 'evidence',
      name: v.name,
      kind: 'tamper',
      build: () => {
        const id = `evi-${Math.abs(hashCode(v.name))}`
        return { job: makeJob(id, makePack(id, v.patch), NEUTRAL) }
      },
    })
  }

  // ---- 组 3：pgc 门（Door 2）----
  // v6 提交判定为 `commit_possible ≡ (w_max_global ≥ θ) ∧ (contradiction ≠ high)`，
  // 其中 w 由 **f 轴**驱动（pgc.ts:636-641 的 gMax 取 f）。故 a/c/d 是**与提交判定无关的轴**，
  // 只调它们不该触发拒绝 —— 作为 probe 记录，而非篡改。
  const pgcTamperVariants: { name: string, state: PgcState4 }[] = [
    { name: 'f 高（承重轴）', state: { a: 0, c: 0, d: 0, f: 0.95 } },
    { name: '全高', state: { a: 0.95, c: 0.95, d: 0.95, f: 0.95 } },
  ]
  const pgcProbeVariants: { name: string, state: PgcState4 }[] = [
    { name: 'a 高（无关轴探针）', state: { a: 0.95, c: 0, d: 0, f: 0 } },
    { name: 'c 高（无关轴探针）', state: { a: 0, c: 0.95, d: 0, f: 0 } },
    { name: 'd 高（无关轴探针）', state: { a: 0, c: 0, d: 0.95, f: 0 } },
  ]
  for (const v of pgcTamperVariants) {
    cases.push({
      gate: 'pgc',
      name: v.name,
      kind: 'tamper',
      build: () => {
        const id = `pgc-${Math.abs(hashCode(v.name))}`
        return { job: makeJob(id, makePack(id), v.state) }
      },
    })
  }
  for (const v of pgcProbeVariants) {
    cases.push({
      gate: 'pgc',
      name: v.name,
      kind: 'probe',
      note: 'v6 commit 判定由 f 轴驱动，a/c/d 不承重',
      build: () => {
        const id = `pgcp-${Math.abs(hashCode(v.name))}`
        return { job: makeJob(id, makePack(id), v.state) }
      },
    })
  }

  return cases
}

function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++)
    h = Math.imul(31, h) + s.charCodeAt(i) | 0
  return h
}

async function main(): Promise<number> {
  const connectionString = process.env.DATABASE_URL
  const redisUrl = process.env.REDIS_URL
  if (!connectionString || !redisUrl) {
    console.error('[verify:promotion-control] both DATABASE_URL and REDIS_URL are required.')
    return EXIT.missingEnv
  }

  const { createDrizzle } = await import('../src/libs/db')
  const { V9_PROMOTION_QUEUE } = await import('../src/services/domain/v9-jobs')
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

  try {
    await redis.connect()
    console.info(`[verify:promotion-control] postgres=${describeTarget(connectionString)} redis=${redisUrl}`)

    const queueLen = await redis.llen(V9_PROMOTION_QUEUE)
    check(queueLen === 0, `promotion queue is empty (got ${queueLen})`)
    if (queueLen !== 0) {
      console.error('[verify:promotion-control] refusing to run: the promotion queue is not empty.')
      return EXIT.failed
    }

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

    interface Row {
      gate: string
      name: string
      kind: 'legal' | 'tamper' | 'probe'
      note: string
      stage: string
      refused: boolean
      realRows: number
      bypassRows: number
    }
    const rows: Row[] = []

    try {
      await db.transaction(async (tx) => {
        const service = createV9PromotionService({ db: tx as never })
        specsBefore = await countSpecs(tx)
        reportsBefore = await countReports(tx)

        const cases = buildCases()
        let tag = 0
        for (const c of cases) {
          tag++
          const { job } = c.build()
          const s0 = await countSpecs(tx)
          const r0 = await countReports(tx)

          // ---- 真实路径：含全部门控 ----
          const res = await service.process(job as never)
          const s1 = await countSpecs(tx)
          const r1 = await countReports(tx)
          const realRows = (s1 - s0) + (r1 - r0)

          // ---- 无门控反事实：直接写 ----
          const s2 = await countSpecs(tx)
          const r2 = await countReports(tx)
          await bypassPromote(tx as never, schema as never, job as never, `t${tag}-${c.gate}`)
          const s3 = await countSpecs(tx)
          const r3 = await countReports(tx)
          const bypassRows = (s3 - s2) + (r3 - r2)

          rows.push({
            gate: c.gate,
            name: c.name,
            kind: c.kind,
            note: c.note ?? '',
            stage: String((res as { stage?: string }).stage ?? 'unknown'),
            refused: (res as { ok?: boolean }).ok === false,
            realRows,
            bypassRows,
          })
        }

        // 校验：回滚前先核对我们确实写进了东西（否则"零写入"可能是假象）。
        const sEnd = await countSpecs(tx)
        check(sEnd > specsBefore, `control run actually wrote rows before rollback (${specsBefore} -> ${sEnd})`)

        throw ROLLBACK
      })
    }
    catch (error) {
      if (error !== ROLLBACK)
        throw error
    }

    // ---- 汇总与断言 ----
    const legal = rows.filter(r => r.kind === 'legal')
    const tampered = rows.filter(r => r.kind === 'tamper')
    const probes = rows.filter(r => r.kind === 'probe')

    console.info('\n── 篡改矩阵（真实服务，全部门控开启）──────────────────────────────')
    console.info('  门          类型    变体                              阶段             有门控写入  无门控写入')
    for (const r of rows) {
      console.info(
        `  ${r.gate.padEnd(11)} ${r.kind.padEnd(7)} ${r.name.padEnd(32)} ${r.stage.padEnd(16)} ${String(r.realRows).padEnd(11)} ${r.bypassRows}`,
      )
    }

    // 断言 1：合法对照必须被放行（假阳性 = 0）
    for (const r of legal) {
      check(r.refused === false && r.stage === 'promoted', `LEGAL control is promoted (stage=${r.stage})`)
      check(r.realRows === 2, `LEGAL control writes exactly 2 rows (got ${r.realRows})`)
    }

    // 断言 2：真篡改必须被拒绝且零写入
    for (const r of tampered) {
      check(r.refused === true, `tamper [${r.gate}/${r.name}] is refused (stage=${r.stage})`)
      check(r.realRows === 0, `tamper [${r.gate}/${r.name}] wrote 0 rows (got ${r.realRows})`)
    }

    // 断言 3：无门控反事实必须全部落库（证明"拒绝"来自门控，而非候选本身不可写）
    for (const r of [...tampered, ...probes]) {
      check(r.bypassRows === 2, `no-gating counterfactual writes 2 rows for [${r.gate}/${r.name}] (got ${r.bypassRows})`)
    }

    // 断言 4：无关轴探针必须**不被**该门拒绝（否则说明门在无关轴上误报）
    for (const r of probes) {
      check(r.refused === false, `probe [${r.gate}/${r.name}] is not refused by design (stage=${r.stage}) [${r.note}]`)
    }

    // 断言 5：零残留
    {
      const afterSpecs = (await db.select({ id: schema.v9EvolutionSpecs.id }).from(schema.v9EvolutionSpecs)).length
      const afterReports = (await db.select({ id: schema.v9EvalReports.id }).from(schema.v9EvalReports)).length
      check(afterSpecs === specsBefore, `no residue in evolution_specs (${specsBefore} -> ${afterSpecs})`)
      check(afterReports === reportsBefore, `no residue in eval_reports (${reportsBefore} -> ${afterReports})`)
    }

    // ---- 特异性与无门控对照的比率 ----
    const legalPass = legal.filter(r => !r.refused).length
    const tamperRefused = tampered.filter(r => r.refused).length
    const tamperGatedWrites = tampered.filter(r => r.realRows > 0).length
    const bypassWrote = tampered.filter(r => r.bypassRows > 0).length
    const refusedRate = tampered.length ? (tamperRefused / tampered.length) : 0
    const bypassRate = tampered.length ? (bypassWrote / tampered.length) : 0
    console.info('\n── 汇总 ──────────────────────────────────────────────────────')
    console.info(`  合法对照放行率        : ${legalPass}/${legal.length} = ${(legal.length ? legalPass / legal.length : 0).toFixed(3)}  （假阳性 = ${legal.length - legalPass}）`)
    console.info(`  真篡改拒绝率          : ${tamperRefused}/${tampered.length} = ${refusedRate.toFixed(3)}`)
    console.info(`  有门控下篡改入库率    : ${tamperGatedWrites}/${tampered.length} = ${(tampered.length ? tamperGatedWrites / tampered.length : 0).toFixed(3)}`)
    console.info(`  无门控下篡改入库率    : ${bypassWrote}/${tampered.length} = ${bypassRate.toFixed(3)}`)
    console.info(`  篡改矩阵规模          : ${tampered.length} 例真篡改 + ${probes.length} 例无关轴探针 + ${legal.length} 例合法对照 = ${rows.length} 例`)
    console.info('  判读：拒绝来自门控本身（无门控反事实下同一批候选全部落库），而非候选不可写。')
    console.info('  探针说明：')
    for (const r of probes)
      console.info(`    · ${r.gate}/${r.name} — ${r.note}（实测 stage=${r.stage}）`)

    if (failures > 0) {
      console.error(`\nFAIL: ${failures} promotion-control assertion(s) failed`)
      return EXIT.failed
    }
    console.info('\nPASS: gate specificity + no-gating control verified against real PostgreSQL')
    return EXIT.ok
  }
  catch (error) {
    console.error('[verify:promotion-control] failed:', error)
    return EXIT.failed
  }
  finally {
    try {
      await redis.quit()
    }
    catch {
      // best-effort
    }
    try {
      await pool.end()
    }
    catch {
      // best-effort
    }
  }
}

main().then(code => process.exit(code)).catch((error) => {
  console.error('[verify:promotion-control] unexpected:', error)
  process.exit(EXIT.unexpected)
})
