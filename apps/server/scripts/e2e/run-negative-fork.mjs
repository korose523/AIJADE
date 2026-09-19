/**
 * E2E 负向分支 v2（对应审稿意见 P0-5）：「宁缺勿伪造」
 *
 * 关键修正：v1 把「对照组（有回执）」放在前面，导致实验组开始时库里已经有了
 * 渲染轨迹——而服务端的语义是「最近一条全局真实回执」（findLatestRenderIdentity，
 * 刻意不做 session 级 join，见 v9-events.ts:292-298 的设计注释）。因此 v1 的
 * B 组并不是真正的「无渲染身份」场景，测出的是跨会话归因行为。
 *
 * v2 顺序（必须在零渲染轨迹的干净库上运行）：
 *   Phase 1  零渲染身份：仅投观察 ⇒ 期望 提案增量 = 0，且观察照常落库（跳过派发≠拒绝受理）
 *   Phase 2  随后补齐真实回执 ⇒ 再投观察 ⇒ 期望 产出提案，且 render_ref 与投影真源逐字一致
 *   Phase 3  可恢复性：Phase 2 的提案引用必须可在 render_traces 中定位（无悬空引用）
 */
const BASE = process.env.AIJADE_E2E_BASE ?? 'http://localhost:3901/api/v1/v9/events'
const TOKEN = process.env.AIJADE_E2E_TOKEN ?? 'e2e-test-token-aijade-2026'

const rand = () => Math.random().toString(36).slice(2, 10)
let NEG_TICK = 9000
const results = []
function record(name, pass, detail = '') {
  results.push({ name, pass, detail })
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

function envelope(topic, payload, over = {}) {
  const id = over.event_id ?? `evt-${topic}-${rand()}`
  return {
    event_id: id,
    trace_id: over.trace_id ?? `trace-${rand()}`,
    correlation_id: over.correlation_id ?? `corr-${rand()}`,
    timestamp: Date.now(),
    producer: 'e2e-driver',
    origin_device: 'e2e-host',
    privacy_level: 1,
    evidence_refs: [],
    causal_context_refs: [],
    risk_score: 0.1,
    idempotency_key: over.idempotency_key ?? `idem-${id}`,
    replay_mode: 'live',
    risk_level: 'low',
    topic,
    payload,
    ...over.extra,
  }
}

async function post(body, withAuth = true) {
  const res = await fetch(BASE, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      ...(withAuth ? { authorization: `Bearer ${TOKEN}` } : {}),
    },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  })
  let json = null
  try { json = await res.json() }
  catch {}
  return { status: res.status, json }
}

async function psql(sql) {
  const { execFileSync } = await import('node:child_process')
  return execFileSync('docker', [
    'exec',
    process.env.AIJADE_DB_CONTAINER ?? 'proj-airi-server-db-1',
    'psql',
    '-U',
    'postgres',
    '-d',
    process.env.AIJADE_DB_NAME ?? 'aijade_e2e',
    '-tAc',
    sql,
  ], { encoding: 'utf8' }).trim()
}

const sleep = ms => new Promise(r => setTimeout(r, ms))
const TOPIC_PROPOSED = 'aijade.learning.proposed.evidence'
const countProposals = async () => Number(await psql(`SELECT count(*) FROM events WHERE topic='${TOPIC_PROPOSED}'`))
const countEvents = async () => Number(await psql('SELECT count(*) FROM events'))
const countTraces = async () => Number(await psql('SELECT count(*) FROM render_traces'))

function observationEnvelope(sessionId, extra = {}) {
  return envelope('aijade.video.observation.webpage_text', {
    session_id: sessionId,
    source_url: 'https://example.com/e2e-negfork2',
    content_hash: `ch-${rand()}`,
    spans: [{ start_offset: 0, end_offset: 120, label: 'paragraph' }],
    observation_text: 'Spaced repetition improves retention by 40 percent in this sample.',
  }, { extra: { tick: (NEG_TICK += 1), causality: { inputHash: `ih-${rand()}` }, ...extra } })
}

async function main() {
  console.log('--- E2E 负向分支 v2：宁缺勿伪造（真实栈 / 零渲染轨迹起点）---\n')

  const traces0 = await countTraces()
  record('P0 前提：起点库内渲染轨迹为 0（真正的"无渲染身份"场景）', traces0 === 0, `render_traces=${traces0}`)
  if (traces0 !== 0) {
    console.log('\n前提不成立，后续结论无效。请在干净库上运行。')
    process.exit(3)
  }

  // ---------- Phase 1：零渲染身份 ----------
  const sessionB = `e2e-nf2-b-${rand()}`
  const beforeP1 = await countProposals()
  const eventsBeforeP1 = await countEvents()
  const obsB = await post(observationEnvelope(sessionB))
  record('P1.1 零渲染身份：观察被正常受理（201，不因缺身份而拒绝）', obsB.status === 201, `status=${obsB.status}`)

  await sleep(6000) // 覆盖 worker 轮询 + 归约窗口
  const afterP1 = await countProposals()
  const eventsAfterP1 = await countEvents()
  record('P1.2 零渲染身份：不产出提案（宁缺勿伪造 · 负向分支）', afterP1 === beforeP1, `proposals ${beforeP1} → ${afterP1}（期望不变）`)
  record('P1.3 零渲染身份：观察照常落库（跳过派发 ≠ 拒绝受理）', eventsAfterP1 > eventsBeforeP1, `events ${eventsBeforeP1} → ${eventsAfterP1}`)
  const tracesAfterP1 = await countTraces()
  record('P1.4 零渲染身份：未产生任何伪造渲染轨迹', tracesAfterP1 === 0, `render_traces=${tracesAfterP1}`)

  // ---------- Phase 2：补齐真实回执后重新观察 ----------
  const traceA = `trace-nf2-a-${rand()}`
  const sessionA = `e2e-nf2-a-${rand()}`
  const intentRef = `intent-nf2-${rand()}`
  const renderRef = `render-nf2-${rand()}`
  const paramsHash = `hash-nf2-${rand()}`

  const r1 = await post(envelope('aijade.persona.render_requested', {
    session_id: sessionA,
    persona_snapshot_ref: 'ps-nf2-1',
    intent_ref: intentRef,
  }, { trace_id: traceA }))
  const r2 = await post(envelope('aijade.lpm.render_ready', {
    session_id: sessionA,
    render_ref: renderRef,
    applied_params_hash: paramsHash,
    asset_version_hash: 'avh-nf2-1',
  }, { trace_id: traceA }))
  record('P2.1 补齐：渲染请求/回执 201 配对', r1.status === 201 && r2.status === 201, `req=${r1.status} ready=${r2.status}`)

  const beforeP2 = await countProposals()
  const obsA = await post(observationEnvelope(sessionA))
  await sleep(6000)
  const afterP2 = await countProposals()
  record('P2.2 有真实回执 ⇒ 产出提案（增量 > 0）', obsA.status === 201 && afterP2 > beforeP2, `obs=${obsA.status} proposals ${beforeP2} → ${afterP2}`)

  // ---------- Phase 3：引用可锚定（无悬空引用） ----------
  const projRef = await psql(`SELECT render_ref FROM render_traces WHERE trace_id='${traceA}' LIMIT 1`)
  const proposalRef = await psql(`SELECT payload::text FROM events WHERE topic='${TOPIC_PROPOSED}' ORDER BY timestamp DESC LIMIT 1`)
  record('P3.1 提案引用与投影真源逐字一致', projRef.length > 0 && proposalRef.includes(projRef), `projection=${projRef} | contained=${proposalRef.includes(projRef)}`)

  const dangling = Number(await psql(
    `SELECT count(*) FROM events e WHERE e.topic='${TOPIC_PROPOSED}' `
    + `AND (e.payload->>'render_ref') IS NOT NULL `
    + `AND NOT EXISTS (SELECT 1 FROM render_traces rt WHERE rt.render_ref = e.payload->>'render_ref')`,
  ))
  record('P3.2 无悬空引用（所有提案 render_ref 均可在投影表定位）', dangling === 0, `dangling=${dangling}`)

  const passed = results.filter(r => r.pass).length
  console.log(`\n===== E2E NEGATIVE-FORK v2 RESULT: ${passed}/${results.length} passed =====`)
  if (passed !== results.length) {
    console.log('失败项：')
    for (const r of results.filter(x => !x.pass))
      console.log(`  - ${r.name} :: ${r.detail}`)
    process.exit(1)
  }
}

main().catch((err) => {
  console.error('E2E NEGATIVE-FORK v2 DRIVER ERROR', err)
  process.exit(2)
})
