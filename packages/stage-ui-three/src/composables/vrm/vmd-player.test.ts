import { Group, Mesh, MeshBasicMaterial, SkinnedMesh } from 'three'
import { describe, expect, it, vi } from 'vitest'

import { createVmdPlayer } from './vmd-player'

/**
 * `loadVmdClip` does real network I/O, so it is replaced with a stub that
 * returns a clip whose `.position` track is identifiable by URL. Everything
 * else — the mixer, the action, the generation guard, disposal — is the real
 * implementation, which is what makes these tests meaningful.
 */
const LOAD_DELAY: Record<string, number> = { 'slow.vmd': 60, 'fast.vmd': 0 }

vi.mock('./pmx-loader', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./pmx-loader')>()
  const three = await import('three')

  return {
    ...actual,
    loadVmdClip: vi.fn(async (url: string) => {
      const delay = LOAD_DELAY[url] ?? 0
      if (delay > 0)
        await new Promise(resolve => setTimeout(resolve, delay))

      return new three.AnimationClip(
        url,
        2,
        [new three.VectorKeyframeTrack('.position', [0, 1, 2], [0, 0, 0, 5, 0, 0, 0, 0, 0])],
      )
    }),
  }
})

function makeRoot(withSkinnedMesh = true): Group {
  const root = new Group()
  if (withSkinnedMesh) {
    // VMD bone/morph tracks are resolved against a SkinnedMesh, so the player
    // requires one on the model.
    root.add(new SkinnedMesh(undefined, new MeshBasicMaterial()))
  }
  else {
    root.add(new Mesh(undefined, new MeshBasicMaterial()))
  }
  return root
}

describe('createVmdPlayer', () => {
  it('reports not-ready before a clip is bound', () => {
    const player = createVmdPlayer(makeRoot())

    expect(player.ready).toBe(false)
    expect(player.duration).toBe(0)
    expect(player.time).toBe(0)
    expect(player.playing).toBe(false)
  })

  it('rejects a model with no skinned mesh instead of throwing an opaque TypeError', async () => {
    // MMDLoader's animation builder reads `mesh.skeleton` and
    // `mesh.morphTargetDictionary`; passing it a bare Group throws inside the
    // loader. The player must convert that into a typed error.
    const player = createVmdPlayer(makeRoot(false))

    await expect(player.load('motion.vmd')).rejects.toMatchObject({ code: 'parse-error' })
    player.dispose()
  })

  it('actually advances the model when driven by the render loop', async () => {
    const root = makeRoot()
    const player = createVmdPlayer(root, { fadeDuration: 0 })
    await player.load('motion.vmd')

    expect(player.ready).toBe(true)
    expect(player.duration).toBe(2)

    // This is the assertion that proves VMD playback is wired up at all: the
    // previous implementation had a loader but no player, so nothing moved.
    player.update(1)
    expect(root.position.x).toBeCloseTo(5, 3)

    player.dispose()
  })

  it('pauses and resumes rather than restarting', async () => {
    const root = makeRoot()
    const player = createVmdPlayer(root, { fadeDuration: 0 })
    await player.load('motion.vmd')

    player.update(1)
    expect(root.position.x).toBeCloseTo(5, 3)

    player.pause()
    expect(player.playing).toBe(false)
    player.update(1)
    expect(root.position.x).toBeCloseTo(5, 3)

    player.play()
    expect(player.playing).toBe(true)
    // Halfway between the 5 at t=1 and the 0 at t=2.
    player.update(0.5)
    expect(root.position.x).toBeCloseTo(2.5, 3)

    player.dispose()
  })

  it('stops and rewinds to the start', async () => {
    const root = makeRoot()
    const player = createVmdPlayer(root, { fadeDuration: 0 })
    await player.load('motion.vmd')

    player.update(1)
    player.stop()
    expect(player.time).toBe(0)
    expect(player.playing).toBe(false)

    player.dispose()
  })

  it('seeks to a clamped position', async () => {
    const player = createVmdPlayer(makeRoot(), { fadeDuration: 0 })
    await player.load('motion.vmd')

    player.seek(1.5)
    expect(player.time).toBe(1.5)

    // Clamped to the clip duration rather than running off the end.
    player.seek(99)
    expect(player.time).toBe(2)
    player.seek(-5)
    expect(player.time).toBe(0)

    player.dispose()
  })

  it('drops a slow motion that resolves after the user switched to another', async () => {
    // Guards the switch-while-loading race: without the generation check the
    // stale clip binds on top of the new one and the wrong motion plays.
    const player = createVmdPlayer(makeRoot(), { fadeDuration: 0 })

    const slow = player.load('slow.vmd')
    const fast = player.load('fast.vmd')
    await Promise.all([slow, fast])

    // The clip is named after the URL it was loaded from.
    expect(player.clip?.name).toBe('fast.vmd')

    player.dispose()
  })

  it('stops advancing after dispose, so a swapped-out model cannot keep animating', async () => {
    const root = makeRoot()
    const player = createVmdPlayer(root, { fadeDuration: 0 })
    await player.load('motion.vmd')

    player.update(1)
    expect(root.position.x).toBeCloseTo(5, 3)

    player.dispose()

    // `uncacheRoot` restores the properties the mixer was driving, so the model
    // returns to its bind pose. That is expected: disposing the player means
    // "stop animating this model", and the caller removes the model anyway.
    const poseAfterDispose = root.position.x

    // The mixer is gone; further frames must not resurrect it.
    player.update(1)
    player.update(1)
    expect(root.position.x).toBe(poseAfterDispose)

    expect(player.ready).toBe(false)
    expect(player.playing).toBe(false)
    expect(player.duration).toBe(0)
  })

  it('can be disposed more than once without throwing', async () => {
    const player = createVmdPlayer(makeRoot(), { fadeDuration: 0 })
    await player.load('motion.vmd')

    player.dispose()
    expect(() => player.dispose()).not.toThrow()
  })

  it('refuses to load into a disposed player', async () => {
    const player = createVmdPlayer(makeRoot(), { fadeDuration: 0 })
    player.dispose()

    await expect(player.load('motion.vmd')).rejects.toThrow(/disposed/)
  })

  it('tolerates playback commands before any clip is bound', () => {
    const player = createVmdPlayer(makeRoot())

    expect(() => {
      player.play()
      player.pause()
      player.stop()
      player.seek(1)
      player.update(0.016)
    }).not.toThrow()

    player.dispose()
  })
})
