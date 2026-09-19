/**
 * AIJADE 端对端测试驱动（真实 HTTP 服务器 @ :3901 + 真实 PG18 + 真实 Redis + worker）。
 *
 * 覆盖：
 *  - 主流程：render_requested → render_ready（身份链配对）→ 幂等重放 → 视频观察（R1 学习闭环）
 *    → opinion_evaluation（C 路）
 *  - 核心接口：POST /api/v1/v9/events 的信封 strict 校验、逐 topic payload 校验
 *  - 边界：未认证 401、缺 tick、坏 causality、未知字段/未知 topic、payload 缺必填、
 *    自引用 ref（§11.2）、append-only 身份链二次值、畸形 JSON —— 全部要求 4xx 且不落库
 */
const BASE = process.env.AIJADE_E2E_BASE ?? 'http://localhost:3901/api/v1/v9/events'
const TOKEN = process.env.AIJADE_E2E_TOKEN ?? 'e2e-test-token-aijade-2026'
const SESSION = 'e2e-install-001'

const results = []
function record(name, pass, detail = '') {
  results.push({ name, pass, detail })
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`)
}

function envelope(topic, payload, over = {}) {
  const id = over.event_id ?? `evt-${topic}-${Math.random().toString(36).slice(2, 10)}`
  return {
    event_id: id,
    trace_id: over.trace_id ?? `trace-${Math.random().toString(36).slice(2, 10)}`,
    correlation_id: over.correlation_id ?? `corr-${Math.random().toString(36).slice(2, 10)}`,
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
  const out = execFileSync('docker', [
    'exec',
    'proj-airi-server-db-1',
    'psql',
    '-U',
    'postgres',
    '-d',
    'aijade_e2e',
    '-tAc',
    sql,
  ], { encoding: 'utf8' })
  return out.trim()
}

async function counts() {
  const [events, traces] = await Promise.all([
    psql('SELECT count(*) FROM events'),
    psql('SELECT count(*) FROM render_traces'),
  ])
  return { events: Number(events), traces: Number(traces) }
}

async function poll(fn, ms = 20000, step = 1000) {
  const end = Date.now() + ms
  while (Date.now() < end) {
    const v = await fn()
    if (v)
      return v
    await new Promise(r => setTimeout(r, step))
  }
  return null
}

// ============================================================================
async function main() {
  const before = await counts()
  const trace = `trace-e2e-${Date.now()}`

  // ---------- N1 未认证 ----------
  {
    const r = await post(envelope('aijade.persona.render_requested', { session_id: SESSION, persona_snapshot_ref: 'ps-1', intent_ref: 'int-e2e-1' }), false)
    record('N1 未认证请求被 401 拒绝', r.status === 401, `status=${r.status}`)
  }

  // ---------- P1 persona.render_requested ----------
  let p1Body
  {
    p1Body = envelope('aijade.persona.render_requested', { session_id: SESSION, persona_snapshot_ref: 'ps-e2e-1', intent_ref: 'intent-e2e-1' }, { trace_id: trace })
    const r = await post(p1Body)
    const ok = r.status === 201 && r.json?.ok === true
    record('P1 persona.render_requested → 201 落库', ok, JSON.stringify(r.json))
    const r1count = await psql(`SELECT count(*) FROM render_traces WHERE trace_id='${trace}'`)
    const paired = await psql(`SELECT projection_status FROM render_traces WHERE trace_id='${trace}'`)
    record('P1b 投影行建立且为 partial（intent 端先到）', r1count === '1' && paired === 'partial', `rows=${r1count} status=${paired}`)
  }

  // ---------- P2 lpm.render_ready（配对完成） ----------
  {
    const r = await post(envelope('aijade.lpm.render_ready', { session_id: SESSION, render_ref: 'render-e2e-1', applied_params_hash: 'hash-e2e-1', asset_version_hash: 'avh-e2e-1' }, { trace_id: trace }))
    record('P2 lpm.render_ready → 201', r.status === 201, `status=${r.status}`)
    const paired = await psql(`SELECT projection_status FROM render_traces WHERE trace_id='${trace}'`)
    const refs = await psql(`SELECT intent_ref, render_ref, applied_params_hash FROM render_traces WHERE trace_id='${trace}'`)
    record('P2b 身份链配对为 paired 且三元组齐备', paired === 'paired' && refs.includes('intent-e2e-1') && refs.includes('render-e2e-1'), refs)
  }

  // ---------- P3 幂等重放 ----------
  {
    const beforeCnt = (await counts()).events
    const r = await post(p1Body)
    const afterCnt = (await counts()).events
    record('P3 同幂等键重放 → 200 deduped 且事件数不变', r.status === 200 && r.json?.deduped === true && afterCnt === beforeCnt, `status=${r.status} deduped=${r.json?.deduped} ${beforeCnt}→${afterCnt}`)
  }

  // ---------- P4 视频观察（A 路入队 → worker R1 闭环） ----------
  {
    const r = await post(envelope('aijade.video.observation.webpage_text', {
      session_id: SESSION,
      source_url: 'https://example.com/e2e-article',
      content_hash: 'ch-e2e-001',
      spans: [{ start_offset: 0, end_offset: 42, label: 'paragraph' }],
      observation_text: 'The page claims that spaced repetition improves retention by 40 percent.',
    }, { extra: { tick: 42, causality: { inputHash: 'ih-e2e-001' } } }))
    record('P4 video.observation → 201（tick+causality 合规）', r.status === 201, `status=${r.status} eventId=${r.json?.eventId}`)

    // worker 消费后应产出真实学习提案（R1：render_identity 来自 render_traces 真源）
    const proposal = await poll(async () => {
      const n = await psql(`SELECT count(*) FROM events WHERE topic='aijade.learning.proposed.evidence'`)
      return Number(n) > 0 ? n : null
    })
    record('P4b R1 闭环：worker 产出 learning.proposed.evidence（端到端首次真实贯通）', !!proposal, `rows=${proposal ?? 0}`)
    if (proposal) {
      const refs = await psql(`SELECT payload::text FROM events WHERE topic='aijade.learning.proposed.evidence' LIMIT 1`)
      record('P4c 提案引用真实渲染身份（render_ref=render-e2e-1，非合成）', refs.includes('render-e2e-1'), refs.slice(0, 160))
    }
    const dl = await psql(`SELECT count(*) FROM events WHERE topic='aijade.learning.proposed.evidence'`)
    void dl
  }

  // ---------- P5 opinion_evaluation（C 路） ----------
  {
    const r = await post(envelope('aijade.learning.constraint.opinion_evaluation', {
      evaluation_target: 'https://example.com/e2e-article',
      claims: [{ claim_text: 'Spaced repetition improves retention.', confidence: 0.72 }],
      uncertainty_notes: 'Sample size of the cited study unknown from the excerpt.',
    }, { extra: { tick: 43, causality: { inputHash: 'ih-e2e-002' } } }))
    const ev = await psql(`SELECT count(*) FROM events WHERE topic='aijade.learning.constraint.opinion_evaluation'`)
    record('P5 opinion_evaluation → 201 且落库（C 路真实投递）', r.status === 201 && Number(ev) >= 1, `status=${r.status} rows=${ev}`)
  }

  // ---------- 负例矩阵（每个都要求 4xx 且 events/render_traces 计数不变） ----------
  const negatives = []
  async function negative(name, makeBody) {
    const before = await counts()
    const r = await post(makeBody())
    const after = await counts()
    const noWrite = after.events === before.events && after.traces === before.traces
    const pass = r.status >= 400 && r.status < 500 && noWrite
    record(name, pass, `status=${r.status} writes=${!noWrite ? 'DIRTY' : 'clean'}`)
    negatives.push(pass)
  }

  await negative('N2 video topic 缺 tick → 400 不落库', () =>
    envelope('aijade.video.observation.webpage_text', { session_id: SESSION, source_url: 'https://x.test/a', content_hash: 'c', spans: [{ start_offset: 0, end_offset: 5 }], observation_text: 'x' }))
  await negative('N3 causality.inputHash 空串 → 400 不落库', () =>
    envelope('aijade.video.observation.webpage_text', { session_id: SESSION, source_url: 'https://x.test/a', content_hash: 'c', spans: [{ start_offset: 0, end_offset: 5 }], observation_text: 'x' }, { extra: { tick: 1, causality: { inputHash: '' } } }))
  await negative('N4 信封未知多余字段（strict）→ 400 不落库', () => {
    const e = envelope('aijade.persona.render_requested', { session_id: SESSION, persona_snapshot_ref: 'p', intent_ref: 'i' })
    e.rogue_field = 'must-be-rejected'
    return e
  })
  await negative('N5 未知 topic → 400 不落库', () =>
    envelope('aijade.unknown.topic.thing', { foo: 'bar' }))
  await negative('N6 render_requested 缺 intent_ref → 400 不落库', () =>
    envelope('aijade.persona.render_requested', { session_id: SESSION, persona_snapshot_ref: 'p-only' }))
  await negative('N7 render_ref 自引用信封标识（§11.2）→ 400 不落库', () => {
    const e = envelope('aijade.lpm.render_ready', { session_id: SESSION, render_ref: 'SELF', applied_params_hash: 'h' }, { trace_id: `trace-selfref-${Date.now()}` })
    e.payload.render_ref = e.trace_id
    return e
  })
  await negative('N8 同 trace 二次 render_ready 不同 render_ref（append-only）→ 400 不落库', () =>
    envelope('aijade.lpm.render_ready', { session_id: SESSION, render_ref: 'render-e2e-CONFLICT', applied_params_hash: 'hash-2' }, { trace_id: trace }))
  {
    const before = await counts()
    const r = await post('{ not-json')
    const after = await counts()
    record('N9 畸形 JSON → 400 不落库', r.status === 400 && after.events === before.events && after.traces === before.traces, `status=${r.status}`)
  }

  // ---------- 汇总 ----------
  const passed = results.filter(r => r.pass).length
  console.log(`\n===== E2E RESULT: ${passed}/${results.length} passed =====`)
  const after = await counts()
  console.log(`DB events: ${before.events} → ${after.events}, render_traces: ${before.traces} → ${after.traces}`)
  if (passed !== results.length)
    process.exit(1)
}

main().catch((e) => { console.error('E2E DRIVER ERROR', e); process.exit(2) })
