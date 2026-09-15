import { Box3, BoxGeometry, Group, Mesh, MeshBasicMaterial, Vector3 } from 'three'
import { describe, expect, it } from 'vitest'

import { loadPmxModel, loadVmdClip, MmdLoadError, normalizeMmdTransform, toMmdLoadError } from './pmx-loader'

/**
 * These tests exist because the previous PMX path failed *silently*: it caught
 * every error and returned `undefined`, so a missing dependency or a corrupt
 * model produced no model and no message. The assertions below pin the opposite
 * contract — failures must throw a typed, message-bearing error.
 */
describe('mmd load error classification', () => {
  it('maps an HTTP 404 to file-not-found with a Chinese message', () => {
    const error = toMmdLoadError({ status: 404 }, '/models/miku.pmx')

    expect(error).toBeInstanceOf(MmdLoadError)
    expect(error.code).toBe('file-not-found')
    expect(error.message).toContain('模型文件不存在')
    expect(error.message).toContain('/models/miku.pmx')
  })

  it('maps a range/offset failure to parse-error', () => {
    // MMDLoader reads the PMX header through a DataView; a truncated or
    // wrong-format file surfaces as a RangeError from those reads.
    const error = toMmdLoadError(new RangeError('Offset is outside the bounds of the DataView'), '/models/broken.pmx')

    expect(error.code).toBe('parse-error')
    expect(error.message).toContain('不是有效的 PMX/PMD')
  })

  it('maps an unrecognised Error to network rather than swallowing it', () => {
    const error = toMmdLoadError(new Error('socket hang up'), '/models/miku.pmx')

    expect(error.code).toBe('network')
    expect(error.message).toContain('socket hang up')
  })

  it('never returns undefined for a non-Error rejection', () => {
    const error = toMmdLoadError('boom', '/models/miku.pmx')

    expect(error).toBeInstanceOf(MmdLoadError)
    expect(error.code).toBe('network')
  })
})

describe('loadPmxModel', () => {
  it('rejects instead of silently resolving to undefined when no path is given', async () => {
    // The old implementation returned `undefined` here, which is how a missing
    // model turned into a permanently empty stage rather than an error.
    await expect(loadPmxModel('')).rejects.toMatchObject({ code: 'file-not-found' })
  })
})

describe('loadVmdClip', () => {
  it('rejects instead of silently resolving when no motion path is given', async () => {
    const group = new Group()
    await expect(loadVmdClip('', group as never)).rejects.toMatchObject({ code: 'file-not-found' })
  })
})

/**
 * MMD is authored in its own unit (~20 units tall) while VRM is in metres
 * (~1.6). Without normalisation the two cannot share a camera, so these tests
 * pin the shared frame rather than trusting the maths by eye.
 */
describe('normalizeMmdTransform', () => {
  function makeModel(height: number): Group {
    const group = new Group()
    const mesh = new Mesh(new BoxGeometry(1, height, 1), new MeshBasicMaterial())
    // Feet on y = 0, so the box spans 0..height.
    mesh.position.y = height / 2
    group.add(mesh)
    return group
  }

  it('rescales an MMD-scale model to the target metre height', () => {
    const group = makeModel(20)
    const result = normalizeMmdTransform(group, { targetHeight: 1.6 })

    expect(result.scale).toBeCloseTo(0.08, 6)

    const box = measure(group)
    expect(box.size.y).toBeCloseTo(1.6, 6)
  })

  it('centres the model on X/Z and rests its feet on y = 0', () => {
    const group = makeModel(20)
    // Deliberately off-centre; the model must still end up centred.
    group.position.set(5, 0, 3)

    normalizeMmdTransform(group, { targetHeight: 1.6 })

    const box = measure(group)
    expect(box.center.x).toBeCloseTo(0, 6)
    expect(box.center.z).toBeCloseTo(0, 6)
    expect(box.min.y).toBeCloseTo(0, 6)
    expect(box.max.y).toBeCloseTo(1.6, 6)
  })

  it('defaults to a 1.6 m avatar so MMD and VRM share one camera', () => {
    const group = makeModel(20)
    normalizeMmdTransform(group)

    expect(measure(group).size.y).toBeCloseTo(1.6, 6)
  })

  it('does not erase a model whose bounds are degenerate', () => {
    const group = new Group()
    // An empty group has an empty bounding box; scaling by zero would make the
    // model invisible, so the scale must fall back to 1.
    const result = normalizeMmdTransform(group, { targetHeight: 1.6 })

    expect(result.scale).toBe(1)
    expect(result.height).toBe(0)
    expect(group.scale.x).toBe(1)
  })

  it('applies a yaw offset when the model was authored facing another axis', () => {
    const group = makeModel(20)
    normalizeMmdTransform(group, { yawOffset: Math.PI })

    expect(group.rotation.y).toBeCloseTo(Math.PI, 6)
  })
})

function measure(group: Group) {
  const box = new Box3().setFromObject(group)
  return {
    size: box.getSize(new Vector3()),
    center: box.getCenter(new Vector3()),
    min: { ...box.min },
    max: { ...box.max },
  }
}
