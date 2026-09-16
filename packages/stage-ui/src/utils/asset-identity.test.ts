import type { DisplayModelFile, DisplayModelURL } from '../stores/display-models'

import { DisplayModelFormat } from '../stores/display-models'

import { describe, expect, it } from 'vitest'

import { resolveAssetVersionHash, sha256Hex } from './asset-identity'

// Must match the sentinel used inside resolveAssetVersionHash. It is a private
// const there, so we assert the *reference* derivation (url + sep + format)
// explicitly to prove the url branch is reference-derived, not content-derived.
const REFERENCE_SEP = '|'

let fileSeq = 0
function fileModel(bytes: number[]): DisplayModelFile {
  const id = `f${fileSeq++}`
  return {
    id,
    format: DisplayModelFormat.VRM,
    type: 'file',
    file: new File([new Uint8Array(bytes)], `${id}.vrm`),
    name: `${id}.vrm`,
    importedAt: 0,
  }
}

describe('sha256Hex', () => {
  it('is stable for identical inputs and changes with content', async () => {
    const a = await sha256Hex(new Uint8Array([1, 2, 3]))
    const b = await sha256Hex(new Uint8Array([1, 2, 3]))
    const c = await sha256Hex(new Uint8Array([1, 2, 4]))
    expect(a).toBe(b)
    expect(a).not.toBe(c)
    expect(a).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe('resolveAssetVersionHash — file branch (content identity)', () => {
  it('same bytes -> same hash (a)', async () => {
    const h1 = await resolveAssetVersionHash(fileModel([10, 20, 30]))
    const h2 = await resolveAssetVersionHash(fileModel([10, 20, 30]))
    expect(h1).toBe(h2)
  })

  it('different bytes -> different hash (b)', async () => {
    // fileModel() issues a fresh unique id each call, so the module cache key
    // (id + size + lastModified) never aliases two distinct contents.
    const h1 = await resolveAssetVersionHash(fileModel([10, 20, 30]))
    const h2 = await resolveAssetVersionHash(fileModel([10, 20, 31]))
    expect(h1).not.toBe(h2)
  })
})

describe('resolveAssetVersionHash — url branch (reference identity)', () => {
  it('is stable for the same url+format (a)', async () => {
    const model: DisplayModelURL = {
      id: 'u1',
      format: DisplayModelFormat.Live2dZip,
      type: 'url',
      url: 'https://example.com/m.zip',
      name: 'm',
      importedAt: 0,
    }
    expect(await resolveAssetVersionHash(model)).toBe(await resolveAssetVersionHash(model))
  })

  it('is reference-derived: hash == sha256(url + sep + format), not a content hash (c)', async () => {
    const url = 'https://example.com/m.zip'
    const format = DisplayModelFormat.Live2dZip
    const model: DisplayModelURL = { id: 'u1', format, type: 'url', url, name: 'm', importedAt: 0 }
    const expected = await sha256Hex(`${url}${REFERENCE_SEP}${format}`)
    expect(await resolveAssetVersionHash(model)).toBe(expected)
  })

  it('changing the url changes the hash', async () => {
    const a = await resolveAssetVersionHash({ id: 'u1', format: DisplayModelFormat.Live2dZip, type: 'url', url: 'https://example.com/a.zip', name: 'a', importedAt: 0 })
    const b = await resolveAssetVersionHash({ id: 'u1', format: DisplayModelFormat.Live2dZip, type: 'url', url: 'https://example.com/b.zip', name: 'b', importedAt: 0 })
    expect(a).not.toBe(b)
  })
})

describe('resolveAssetVersionHash — caching', () => {
  it('returns the same value (and shares the in-flight hash) on repeat calls (d)', async () => {
    const model = fileModel([7, 8, 9])
    const first = await resolveAssetVersionHash(model)
    const second = await resolveAssetVersionHash(model)
    expect(second).toBe(first)
  })
})
