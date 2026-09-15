/**
 * VMD motion player for MMD models.
 *
 * `loadVmdMotion` returns raw VMD data, which animates nothing on its own —
 * that was one of the reasons the original MMD path was dead code: there was a
 * loader but no player. This module closes that gap by binding a VMD file to a
 * `three` AnimationMixer, the same mechanism VRM uses, so bone tracks and morph
 * (表情) tracks are driven by one clock.
 *
 * Lifecycle is explicit: `dispose()` must be called when the owning model is
 * swapped or unmounted, otherwise the mixer keeps its bindings and the GPU
 * resources behind the clip's tracks are never released.
 */

import type { AnimationAction, AnimationClip, AnimationMixer, Object3D, SkinnedMesh } from 'three'

import { AnimationMixer as AnimationMixerCtor, LoopOnce, LoopRepeat } from 'three'

import { loadVmdClip, MmdLoadError } from './pmx-loader'

export interface VmdPlayerOptions {
  /** Start playing as soon as the clip resolves. Defaults to true. */
  autoPlay?: boolean
  /** Loop the motion. Defaults to true. */
  loop?: boolean
  /** Cross-fade duration in seconds when replacing an action. Defaults to 0.3. */
  fadeDuration?: number
  /** Playback rate. Defaults to 1. */
  timeScale?: number
}

export interface VmdPlayer {
  /** Root object the mixer is bound to. */
  readonly root: Object3D
  /** The clip currently bound, if any. */
  readonly clip: AnimationClip | undefined
  /** Total length of the current clip in seconds; 0 when no clip is bound. */
  readonly duration: number
  /** True once a clip is bound. */
  readonly ready: boolean
  /** True while an action is playing (not paused, not stopped). */
  readonly playing: boolean
  /** Current playback position in seconds. */
  readonly time: number

  /** Bind a VMD file. Replaces any previously bound clip. */
  load: (motionUrl: string, options?: { onProgress?: (ratio: number) => void }) => Promise<AnimationClip>
  play: () => void
  pause: () => void
  stop: () => void
  /** Seek to a position in seconds, clamped to the clip duration. */
  seek: (seconds: number) => void
  /** Drive playback. Call once per frame from the render loop with delta seconds. */
  update: (delta: number) => void
  /** Release the mixer and unbind the clip. Safe to call more than once. */
  dispose: () => void
}

/**
 * Create a VMD player bound to `root`.
 *
 * @param root The loaded PMX/PMD object (or one of its skinned meshes — VMD
 *   bone tracks are resolved against the object the clip was built for, so pass
 *   the same object that was handed to `loadVmdClip`).
 */
export function createVmdPlayer(root: Object3D, options?: VmdPlayerOptions): VmdPlayer {
  let mixer: AnimationMixer | undefined
  let action: AnimationAction | undefined
  let clip: AnimationClip | undefined
  let disposed = false
  let playing = false

  const fadeDuration = options?.fadeDuration ?? 0.3

  // A generation counter guards against the "user switched motion while the
  // previous VMD was still downloading" race: the stale load resolves after the
  // swap and would otherwise bind its clip on top of the new one.
  let loadGeneration = 0

  function ensureMixer(): AnimationMixer {
    if (!mixer)
      mixer = createMixer(root)
    return mixer
  }

  async function load(motionUrl: string, loadOptions?: { onProgress?: (ratio: number) => void }): Promise<AnimationClip> {
    if (disposed)
      throw new Error('[VmdPlayer] cannot load into a disposed player')

    const generation = ++loadGeneration

    // VMD clips are built against a specific object; a SkinnedMesh target gives
    // MMDLoader the morph dictionary it needs to resolve 表情 tracks.
    const target = resolveClipTarget(root)
    const nextClip = await loadVmdClip(motionUrl, target, { onProgress: loadOptions?.onProgress })

    // A newer load (or a dispose) happened while we were awaiting — drop it.
    if (disposed || generation !== loadGeneration) {
      return nextClip
    }

    bindClip(nextClip)
    return nextClip
  }

  function bindClip(nextClip: AnimationClip) {
    const activeMixer = ensureMixer()

    if (action) {
      action.fadeOut(fadeDuration)
      action.stop()
    }
    // Drop cached actions for the previous clip so a repeated motion name does
    // not resurrect a stale action.
    if (clip)
      activeMixer.uncacheClip(clip)
    activeMixer.stopAllAction()

    clip = nextClip
    action = activeMixer.clipAction(nextClip)
    action.setLoop(options?.loop === false ? LoopOnce : LoopRepeat, Number.POSITIVE_INFINITY)
    action.clampWhenFinished = options?.loop === false
    action.timeScale = options?.timeScale ?? 1
    action.reset()

    if (options?.autoPlay !== false) {
      action.fadeIn(fadeDuration)
      action.play()
      playing = true
    }
    else {
      playing = false
    }
  }

  function play() {
    if (!action || disposed)
      return
    action.paused = false
    action.play()
    playing = true
  }

  function pause() {
    if (!action || disposed)
      return
    action.paused = true
    playing = false
  }

  function stop() {
    if (!action || disposed)
      return
    action.reset()
    action.stop()
    playing = false
  }

  function seek(seconds: number) {
    if (!action || !clip || disposed)
      return
    action.time = Math.min(Math.max(0, seconds), clip.duration)
  }

  function update(delta: number) {
    if (!mixer || disposed)
      return
    mixer.update(delta)
  }

  function dispose() {
    if (disposed)
      return
    disposed = true
    loadGeneration++

    if (mixer) {
      mixer.stopAllAction()
      if (clip)
        mixer.uncacheClip(clip)
      // Releases the mixer's internal bindings to the object's bones.
      mixer.uncacheRoot(root)
    }

    mixer = undefined
    action = undefined
    clip = undefined
    playing = false
  }

  return {
    get root() {
      return root
    },
    get clip() {
      return clip
    },
    get duration() {
      return clip?.duration ?? 0
    },
    get ready() {
      return clip !== undefined
    },
    get playing() {
      return playing
    },
    get time() {
      return action?.time ?? 0
    },
    load,
    play,
    pause,
    stop,
    seek,
    update,
    dispose,
  }
}

/**
 * MMDLoader's animation builder reads `mesh.skeleton.bones` for bone tracks and
 * `mesh.morphTargetDictionary` for 表情 tracks, so the target MUST be a
 * SkinnedMesh — handing it a Group throws. `loadPmxModel` already rejects
 * models with no skinned mesh, so this is a defensive path rather than a
 * routine one; it surfaces a typed error instead of an opaque TypeError.
 */
function resolveClipTarget(root: Object3D): SkinnedMesh {
  let found: SkinnedMesh | undefined
  root.traverse((child) => {
    if (!found && (child as SkinnedMesh).isSkinnedMesh)
      found = child as SkinnedMesh
  })

  if (!found) {
    throw new MmdLoadError(
      'parse-error',
      '模型里没有蒙皮网格，无法绑定 VMD 动作（骨骼与表情轨道都需要 SkinnedMesh）',
    )
  }

  return found
}

function createMixer(root: Object3D): AnimationMixer {
  return new AnimationMixerCtor(root)
}
