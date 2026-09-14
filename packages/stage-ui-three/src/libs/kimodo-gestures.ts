/**
 * kimodo-gestures — offline gesture clip loader for VRM avatars.
 *
 * AIJADE generates body-motion clips offline (e.g. from NVIDIA KIMODO or HY-Motion)
 * and ships them as small JSON files under `public/kimodo/` and `public/hy-motion/`.
 * Each clip JSON is a neutral, skeleton-agnostic description:
 *
 *   {
 *     "name": "wave",
 *     "fps": 30,
 *     "duration": 3.0,
 *     "restHipsPosition": [0, 0.8, 0],
 *     "bones": {
 *       "leftUpperArm": { "times": [0, 1/30, ...], "rotation": [[x,y,z,w], ...] },
 *       ...
 *     },
 *     "translation": { "times": [...], "position": [[x,y,z], ...] },   // optional hips track
 *     "expressions": { "happy": { "times": [...], "weights": [...] } } // optional
 *   }
 *
 * This module fetches the per-source `manifest.json`, builds a `VRMAnimation`
 * from each clip, and returns ready-to-play `AnimationClip`s. The runtime only
 * needs the JSON — no Python / no GPU at view time.
 *
 * Mirrors the pattern documented in `apps/stage-web/public/kimodo/README.md`.
 */

import type { VRM, VRMHumanBoneName } from '@pixiv/three-vrm'
import type { VRMCore } from '@pixiv/three-vrm-core'
import type {
  AnimationClip,
} from 'three'

import type { MotionEntry, MotionIntent, MotionSource } from './motion-fusion'

import { createVRMAnimationClip, VRMAnimation } from '@pixiv/three-vrm-animation'
import {
  NumberKeyframeTrack,
  QuaternionKeyframeTrack,
  Vector3,
  VectorKeyframeTrack,
} from 'three'

/** Default offline gesture sources, searched in order. Both KIMODO and HY-Motion share this loader. */
export const OFFLINE_GESTURE_SOURCES: string[] = ['/kimodo', '/hy-motion']

export interface KimodoGestureBoneTrack {
  times: number[]
  rotation: [number, number, number, number][]
}

export interface KimodoGestureTranslationTrack {
  times: number[]
  position: [number, number, number][]
}

export interface KimodoGestureExpressionTrack {
  times: number[]
  weights: number[]
}

export interface KimodoGestureClipJSON {
  name: string
  fps: number
  duration?: number
  restHipsPosition?: [number, number, number]
  bones: Record<string, KimodoGestureBoneTrack>
  translation?: KimodoGestureTranslationTrack
  expressions?: Record<string, KimodoGestureExpressionTrack>
  /** Semantic motion intents this clip expresses (drives persona fusion). */
  intents?: MotionIntent[]
  /** Origin of the clip; inferred from the serving path when omitted. */
  source?: MotionSource
}

export interface OfflineGestureSource {
  baseUrl: string
}

const HUMANOID_BONE_NAMES = new Set<VRMHumanBoneName>([
  'hips',
  'spine',
  'chest',
  'upperChest',
  'neck',
  'head',
  'leftEye',
  'rightEye',
  'jaw',
  'leftShoulder',
  'leftUpperArm',
  'leftLowerArm',
  'leftHand',
  'rightShoulder',
  'rightUpperArm',
  'rightLowerArm',
  'rightHand',
  'leftUpperLeg',
  'leftLowerLeg',
  'leftFoot',
  'leftToes',
  'rightUpperLeg',
  'rightLowerLeg',
  'rightFoot',
  'rightToes',
])

function isHumanBoneName(name: string): name is VRMHumanBoneName {
  return HUMANOID_BONE_NAMES.has(name as VRMHumanBoneName)
}

/**
 * Build a VRM-compatible AnimationClip from a clip JSON + a live VRM.
 *
 * The clip JSON stores LOCAL rotations per human bone and an optional hips
 * translation track. We populate a `VRMAnimation` and let three-vrm resolve the
 * correct keyframe track names for this specific avatar.
 */
export function buildVRMAnimation(json: KimodoGestureClipJSON, vrm: VRM | VRMCore): AnimationClip {
  const va = new VRMAnimation()

  va.duration = json.duration ?? ((json.bones && Object.values(json.bones)[0]?.times.at(-1)) ?? 0)
  va.restHipsPosition = new Vector3(...(json.restHipsPosition ?? [0, 0.8, 0]))

  // Rotation tracks (per human bone).
  for (const [boneName, track] of Object.entries(json.bones)) {
    if (!isHumanBoneName(boneName))
      continue
    const values: number[] = []
    for (const q of track.rotation)
      values.push(q[0], q[1], q[2], q[3])
    const kf = new QuaternionKeyframeTrack(boneName, track.times, values)
    va.humanoidTracks.rotation.set(boneName, kf)
  }

  // Hips translation track (enables dance / walk displacement).
  if (json.translation && json.translation.times.length > 0) {
    const values: number[] = []
    for (const p of json.translation.position)
      values.push(p[0], p[1], p[2])
    va.humanoidTracks.translation.set('hips', new VectorKeyframeTrack('hips', json.translation.times, values))
  }

  // Optional facial expression tracks (best-effort; ignored if the VRM lacks them).
  if (json.expressions) {
    for (const [exprName, track] of Object.entries(json.expressions)) {
      const kf = new NumberKeyframeTrack(exprName, track.times, track.weights)
      // three-vrm maps preset names; custom names fall through to the custom map.
      va.expressionTracks.preset.set(exprName as never, kf)
    }
  }

  return createVRMAnimationClip(va, vrm)
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok)
    throw new Error(`Failed to fetch ${url}: ${res.status} ${res.statusText}`)
  return (await res.json()) as T
}

interface KimodoManifest {
  version?: string
  clips?: string[] | { name: string, file?: string }[]
}

/**
 * Load all offline-generated gesture clips for a VRM.
 *
 * For each source we read `${baseUrl}/manifest.json` (an array/object of clip
 * names) and fetch `${baseUrl}/${name}.json`, then build a VRMAnimationClip.
 * Sources that are missing/empty simply contribute nothing (graceful degrade).
 */
export async function loadOfflineGestureClips(
  vrm: VRM | VRMCore,
  sources: OfflineGestureSource[] | string[] = OFFLINE_GESTURE_SOURCES,
): Promise<AnimationClip[]> {
  const baseUrls = sources.map(s => (typeof s === 'string' ? s : s.baseUrl))
  const clips: AnimationClip[] = []

  for (const baseUrl of baseUrls) {
    let manifest: KimodoManifest
    try {
      manifest = await fetchJson<KimodoManifest>(`${baseUrl}/manifest.json`)
    }
    catch {
      continue // source not deployed yet — skip
    }

    const names: string[] = []
    if (Array.isArray(manifest.clips))
      names.push(...manifest.clips.map(c => (typeof c === 'string' ? c : c.name)))

    for (const name of names) {
      try {
        const json = await fetchJson<KimodoGestureClipJSON>(`${baseUrl}/${name}.json`)
        const clip = buildVRMAnimation(json, vrm)
        clip.name = name
        clips.push(clip)
      }
      catch (err) {
        console.warn(`[kimodo-gestures] skipped clip "${name}" from ${baseUrl}:`, err)
      }
    }
  }

  return clips
}

/** Convenience wrapper that loads only the KIMODO source. */
export async function loadKimodoGestureClips(vrm: VRM | VRMCore, baseUrl = '/kimodo'): Promise<AnimationClip[]> {
  return loadOfflineGestureClips(vrm, [{ baseUrl }])
}

/**
 * Fallback intent tags for clips whose JSON/manifest does not carry `intents`.
 * Lets the fusion selector still match persona intents to named gestures even
 * for clips generated before intent tagging existed (e.g. `demo_dance.json`).
 */
export const DEFAULT_INTENT_MAP: Record<string, MotionIntent[]> = {
  // KIMODO procedural gestures
  wave: ['playful', 'open'],
  nod: ['agreeable'],
  agree: ['agreeable', 'confident'],
  point: ['alert', 'confident'],
  shrug: ['bashful', 'thoughtful'],
  think: ['thoughtful'],
  dance: ['playful'],
  celebrate: ['playful', 'open'],
  cheer: ['playful', 'open'],
  // HY-Motion expressive (learned, full-body) clips
  reach_out: ['open', 'tender'],
  lean_in: ['open', 'confident'],
  sway: ['playful', 'wistful'],
  fidget: ['restless'],
  look_away: ['wistful', 'bashful'],
  affirm: ['agreeable', 'confident'],
}

export interface OfflineGestureManifestClip {
  name: string
  intents?: MotionIntent[]
  source?: MotionSource
}

export interface OfflineGestureManifest {
  version?: string
  clips?: (string | OfflineGestureManifestClip)[]
}

/**
 * Pure resolver for a clip's fused-motion metadata. Precedence:
 *   manifest entry > clip JSON > {@link DEFAULT_INTENT_MAP} (by name) > [].
 * Extracted so it can be unit-tested without a real VRM instance.
 */
export function resolveMotionMeta(
  name: string,
  manifestEntry: OfflineGestureManifestClip | undefined,
  clipJson: KimodoGestureClipJSON | undefined,
  baseUrl: string,
): { source: MotionSource, intents: MotionIntent[] } {
  const source: MotionSource = manifestEntry?.source
    ?? clipJson?.source
    ?? (baseUrl.includes('hy-motion') ? 'hy-motion' : 'kimodo')
  const intents: MotionIntent[] = manifestEntry?.intents
    ?? clipJson?.intents
    ?? DEFAULT_INTENT_MAP[name]
    ?? []
  return { source, intents }
}

/**
 * Load the merged KIMODO + HY-Motion clip set as a persona-fusable motion
 * library. For each source we read `${baseUrl}/manifest.json`, then fetch each
 * `${baseUrl}/${name}.json` and wrap it as a {@link MotionEntry} tagged with:
 *  - `intents`: manifest entry > clip JSON > {@link DEFAULT_INTENT_MAP} > []
 *  - `source` : manifest entry > clip JSON > inferred from the serving path
 *
 * Sources that are missing/empty (no manifest, no clips) contribute nothing, so
 * the runtime degrades gracefully to a pure-emote avatar when no motions ship.
 */
export async function loadMotionLibrary(
  vrm: VRM | VRMCore,
  sources: OfflineGestureSource[] | string[] = OFFLINE_GESTURE_SOURCES,
): Promise<MotionEntry[]> {
  const baseUrls = sources.map(s => (typeof s === 'string' ? s : s.baseUrl))
  const entries: MotionEntry[] = []

  for (const baseUrl of baseUrls) {
    let manifest: OfflineGestureManifest
    try {
      manifest = await fetchJson<OfflineGestureManifest>(`${baseUrl}/manifest.json`)
    }
    catch {
      continue // source not deployed yet — skip
    }

    const clipsMeta: OfflineGestureManifestClip[] = []
    if (Array.isArray(manifest.clips)) {
      for (const c of manifest.clips) {
        if (typeof c === 'string')
          clipsMeta.push({ name: c })
        else
          clipsMeta.push({ name: c.name, intents: c.intents, source: c.source })
      }
    }

    for (const meta of clipsMeta) {
      try {
        const json = await fetchJson<KimodoGestureClipJSON>(`${baseUrl}/${meta.name}.json`)
        const { source, intents } = resolveMotionMeta(meta.name, meta, json, baseUrl)
        const clip = buildVRMAnimation(json, vrm)
        clip.name = meta.name
        entries.push({ name: meta.name, source, intents, clip, baseWeight: 1 })
      }
      catch (err) {
        console.warn(`[kimodo-gestures] skipped clip "${meta.name}" from ${baseUrl}:`, err)
      }
    }
  }

  return entries
}
