import { describe, expect, it, vi } from 'vitest'

import { ensureV9PersonaIntent, getIntentRefFor, getPersonaSnapshotRefFor } from './v9-persona-intent'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('v9 persona intent refs (P0-1 real ref source)', () => {
  it('caches real refs from a successful derive and exposes them via getters', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(200, { persona_snapshot_ref: 'snap-1', intent_ref: 'pi-1' }))
    await ensureV9PersonaIntent('s-ok', { fetchImpl })
    expect(getPersonaSnapshotRefFor('s-ok')).toBe('snap-1')
    expect(getIntentRefFor('s-ok')).toBe('pi-1')
  })

  it('never caches on HTTP failure — getters stay undefined (宁缺勿伪造)', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(422, { message: 'NO_EVIDENCE' }))
    await ensureV9PersonaIntent('s-fail', { fetchImpl })
    expect(getPersonaSnapshotRefFor('s-fail')).toBeUndefined()
    expect(getIntentRefFor('s-fail')).toBeUndefined()
  })

  it('does not cache empty refs even on 200', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(200, { persona_snapshot_ref: '', intent_ref: 'pi-x' }))
    await ensureV9PersonaIntent('s-empty', { fetchImpl })
    expect(getPersonaSnapshotRefFor('s-empty')).toBeUndefined()
    expect(getIntentRefFor('s-empty')).toBeUndefined()
  })

  it('derives at most once per session (cache hit ⇒ no second HTTP call)', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(200, { persona_snapshot_ref: 'snap-2', intent_ref: 'pi-2' }))
    await ensureV9PersonaIntent('s-cache', { fetchImpl })
    await ensureV9PersonaIntent('s-cache', { fetchImpl })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('network error is swallowed (never rejects) and refs stay undefined', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('network down')
    })
    await expect(ensureV9PersonaIntent('s-net', { fetchImpl })).resolves.toBeUndefined()
    expect(getPersonaSnapshotRefFor('s-net')).toBeUndefined()
    expect(getIntentRefFor('s-net')).toBeUndefined()
  })

  it('undefined session ⇒ getters return undefined (no HTTP possible anyway)', () => {
    expect(getPersonaSnapshotRefFor(undefined)).toBeUndefined()
    expect(getIntentRefFor(undefined)).toBeUndefined()
  })
})
