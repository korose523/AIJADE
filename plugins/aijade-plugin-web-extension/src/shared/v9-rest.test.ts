import { describe, expect, it, vi } from 'vitest'

import { reducePageToEvidence, reduceSubtitleToEvidence } from './v10-evidence'
import { buildV9EventEnvelope, postV9Event } from './v9-rest'

function makeMockFetch(status: number, body: Record<string, unknown>) {
  return vi.fn(async () => ({
    status,
    json: async () => body,
  })) as unknown as typeof fetch
}

const pagePayload = {
  site: 'youtube' as const,
  url: 'https://example.test/article',
  title: 'A title',
  description: 'A summary',
}

const subtitlePayload = {
  site: 'youtube' as const,
  url: 'https://youtube.test/watch?v=abc',
  videoId: 'abc',
  text: '  hello   world ',
}

describe('buildV9EventEnvelope', () => {
  it('assembles a complete envelope with tick + causality.inputHash and no unknown fields', () => {
    const evidence = reducePageToEvidence(pagePayload)!
    const env = buildV9EventEnvelope({ evidence, tick: 3 })

    expect(env.tick).toBe(3)
    expect(env.causality.inputHash).toBe(env.payload.content_hash)
    expect(env.producer).toBe('aijade-web-extension')
    expect(env.origin_device).toBe('browser')
    expect(env.privacy_level).toBe(1)
    expect(env.replay_mode).toBe('live')
    expect(env.risk_level).toBe('low')
    expect(env.causal_context_refs).toEqual([env.trace_id])
    expect(env.evidence_refs).toEqual([])

    // 信封字段必须恰好等于服务端 strictObject schema 要求的 17 个字段
    // （任何未知字段会让服务端返回 400）。
    expect(Object.keys(env).sort()).toEqual([
      'causal_context_refs',
      'causality',
      'correlation_id',
      'event_id',
      'evidence_refs',
      'idempotency_key',
      'origin_device',
      'payload',
      'privacy_level',
      'producer',
      'replay_mode',
      'risk_level',
      'risk_score',
      'tick',
      'timestamp',
      'topic',
      'trace_id',
    ].sort())
  })

  it('two identical observations (same topic + hash + tick) share the idempotency_key', () => {
    const evidence = reduceSubtitleToEvidence(subtitlePayload)!
    const a = buildV9EventEnvelope({ evidence, tick: 7 })
    const b = buildV9EventEnvelope({ evidence, tick: 7 })

    expect(a.idempotency_key).toBe(b.idempotency_key)
    expect(a.idempotency_key).toBe(
      `aijade.video.observation.video_transcript#${evidence.payload.transcript_hash}#7`,
    )
    // 仅 idempotency_key 确定；随机字段不应相同（证明我们没有把随机值塞进幂等键）。
    expect(a.event_id).not.toBe(b.event_id)
    expect(a.trace_id).not.toBe(b.trace_id)
  })

  it('causality.inputHash equals the payload snapshot hash (true link)', () => {
    const page = reducePageToEvidence(pagePayload)!
    const envPage = buildV9EventEnvelope({ evidence: page, tick: 1 })
    expect(envPage.causality.inputHash).toBe(page.payload.content_hash)

    const sub = reduceSubtitleToEvidence(subtitlePayload)!
    const envSub = buildV9EventEnvelope({ evidence: sub, tick: 1 })
    expect(envSub.causality.inputHash).toBe(sub.payload.transcript_hash)
  })
})

describe('postV9Event', () => {
  function pageEnvelope(tick = 1) {
    return buildV9EventEnvelope({ evidence: reducePageToEvidence(pagePayload)!, tick })
  }

  it('201 → ok:true', async () => {
    const fetchImpl = makeMockFetch(201, { ok: true, deduped: false, eventId: 'evt-1' })
    const res = await postV9Event('http://localhost:6121', pageEnvelope(), { fetchImpl })
    expect(res.ok).toBe(true)
    expect(res.deduped).toBe(false)
    expect(res.eventId).toBe('evt-1')
    expect(res.status).toBe(201)
  })

  it('200 → deduped:true', async () => {
    const fetchImpl = makeMockFetch(200, { ok: true, deduped: true, eventId: 'evt-2' })
    const res = await postV9Event('http://localhost:6121', pageEnvelope(), { fetchImpl })
    expect(res.ok).toBe(true)
    expect(res.deduped).toBe(true)
    expect(res.status).toBe(200)
  })

  it('400 → ok:false with a non-empty error', async () => {
    const fetchImpl = makeMockFetch(400, { error: 'Invalid v9 event envelope', issues: [] })
    const res = await postV9Event('http://localhost:6121', pageEnvelope(), { fetchImpl })
    expect(res.ok).toBe(false)
    expect(res.status).toBe(400)
    expect(typeof res.error).toBe('string')
    expect(res.error!.length).toBeGreaterThan(0)
  })

  it('sends Bearer token when provided and includes credentials', async () => {
    const fetchImpl = vi.fn(async (_url: string, init: RequestInit) => {
      expect((init.headers as Record<string, string>).authorization).toBe('Bearer secret')
      expect(init.credentials).toBe('include')
      return { status: 201, json: async () => ({ ok: true, deduped: false, eventId: 'x' }) }
    }) as unknown as typeof fetch
    await postV9Event('http://localhost:6121', pageEnvelope(), { token: 'secret', fetchImpl })
  })

  it('network failure → ok:false with error (not silently swallowed)', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('network down')
    }) as unknown as typeof fetch
    const res = await postV9Event('http://localhost:6121', pageEnvelope(), { fetchImpl })
    expect(res.ok).toBe(false)
    expect(res.status).toBe(0)
    expect(res.error).toBe('network down')
  })
})
