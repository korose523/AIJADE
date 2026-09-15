/**
 * PMX/MMD Model Loader for AIJADE
 *
 * Loads PMX/PMD models using `three-stdlib`'s MMDLoader, which handles the
 * format's own material system (toon + sphere maps), the shared textures they
 * reference, the skeleton, and the morph targets.
 *
 * Design note — why this file used to be dead code:
 * the previous version imported MMDLoader through a *variable* specifier and
 * swallowed every failure, returning `undefined` when `three-stdlib` was
 * absent. It therefore looked implemented while silently doing nothing. The
 * dependency is now a real dependency, and failures throw `MmdLoadError`
 * instead of returning `undefined`, so callers can surface a real message.
 */

import type { AnimationClip, Camera, Object3D, SkinnedMesh } from 'three'

import { Box3, Group, Vector3 } from 'three'
// Imported from the package root, not from `three-stdlib/loaders/MMDLoader`:
// three-stdlib's `exports` map only publishes the root entry point, so the
// subpath form does not resolve under `moduleResolution: Bundler`.
import { MMDLoader } from 'three-stdlib'

/** Why a PMX/PMD model could not be loaded. Callers should map these to user-facing text. */
export type MmdLoadErrorCode
  = | 'file-not-found'
    | 'network'
    | 'parse-error'
    | 'dependency-missing'
    | 'unsupported-browser'

const HTTP_STATUS_TEXT: Record<number, string> = {
  404: '模型文件不存在',
  403: '没有访问该模型文件的权限',
  401: '需要授权才能访问该模型文件',
  500: '服务器在读取模型文件时出错',
}

export class MmdLoadError extends Error {
  readonly code: MmdLoadErrorCode

  constructor(code: MmdLoadErrorCode, message: string, options?: { cause?: unknown }) {
    super(message, options)
    this.name = 'MmdLoadError'
    this.code = code
  }
}

/** Turn whatever `MMDLoader` hands to `onError` into a typed, message-bearing error. */
export function toMmdLoadError(err: unknown, modelUrl: string): MmdLoadError {
  const status = (err as { status?: number } | null)?.status
    ?? (err as { target?: { status?: number } } | null)?.target?.status

  if (typeof status === 'number' && HTTP_STATUS_TEXT[status]) {
    return new MmdLoadError('file-not-found', `${HTTP_STATUS_TEXT[status]}（HTTP ${status}）：${modelUrl}`, { cause: err })
  }

  if (err instanceof Error) {
    // A syntax/parse failure surfaces from the loader's internal DataView reads.
    if (err instanceof RangeError || /offset|byte|range|length/i.test(err.message)) {
      return new MmdLoadError('parse-error', `模型文件不是有效的 PMX/PMD，或已损坏：${modelUrl}`, { cause: err })
    }
    return new MmdLoadError('network', `加载模型失败：${modelUrl}（${err.message}）`, { cause: err })
  }

  return new MmdLoadError('network', `加载模型失败：${modelUrl}`, { cause: err })
}

export interface MmdMorphTarget {
  /** Morph (表情) name as authored in the model. */
  name: string
  /** Index into the owning mesh's `morphTargetInfluences`. */
  index: number
}

export interface LoadedMmdModel {
  /** Root object; add this to the scene. */
  group: Group
  /** Every skinned mesh found in the model (a PMX model may split by material). */
  meshes: SkinnedMesh[]
  /** Morph targets per mesh, keyed by morph name (表情变形). */
  morphs: Map<SkinnedMesh, MmdMorphTarget[]>
  /** Bounding-box centre of the *raw* model, before `normalizeMmdTransform`. */
  modelCenter: Vector3
  /** Bounding-box size of the *raw* model, before `normalizeMmdTransform`. */
  modelSize: Vector3
}

function collectSkinnedMeshes(root: Object3D): SkinnedMesh[] {
  const meshes: SkinnedMesh[] = []
  root.traverse((child: Object3D) => {
    if ((child as SkinnedMesh).isSkinnedMesh)
      meshes.push(child as SkinnedMesh)
  })
  return meshes
}

function collectMorphs(meshes: SkinnedMesh[]): Map<SkinnedMesh, MmdMorphTarget[]> {
  const morphs = new Map<SkinnedMesh, MmdMorphTarget[]>()
  for (const mesh of meshes) {
    const dict = (mesh as unknown as { morphTargetDictionary?: Record<string, number> }).morphTargetDictionary
    if (!dict)
      continue
    morphs.set(mesh, Object.entries(dict).map(([name, index]) => ({ name, index })))
  }
  return morphs
}

/**
 * Load a PMX/PMD model.
 *
 * @param modelUrl   URL of the `.pmx` / `.pmd` file.
 * @param options.resourcePath  Directory the model's textures are resolved
 *   against. Defaults to the model's own directory, which is what MMDLoader
 *   does internally; pass it explicitly when the model is served from a blob
 *   URL and its textures live elsewhere.
 * @param options.onProgress  Receives 0..1 — normalised so all three formats
 *   report progress on the same scale.
 */
export async function loadPmxModel(
  modelUrl: string,
  options?: {
    resourcePath?: string
    onProgress?: (ratio: number) => void
  },
): Promise<LoadedMmdModel> {
  if (!modelUrl)
    throw new MmdLoadError('file-not-found', '没有指定模型文件路径')

  const loader = new MMDLoader()

  if (options?.resourcePath)
    loader.setResourcePath(options.resourcePath)

  const object = await new Promise<Object3D>((resolve, reject) => {
    loader.load(
      modelUrl,
      loaded => resolve(loaded as Object3D),
      (event) => {
        if (!options?.onProgress || !event || event.lengthComputable !== true)
          return
        options.onProgress(Math.min(1, Math.max(0, event.loaded / event.total)))
      },
      err => reject(toMmdLoadError(err, modelUrl)),
    )
  })

  // MMDLoader hands back a Group for multi-material PMX models, but a bare
  // SkinnedMesh for single-material ones. Always wrap so callers get one shape.
  let group: Group
  if ((object as unknown as { isGroup?: boolean }).isGroup === true) {
    group = object as unknown as Group
  }
  else {
    group = new Group()
    group.add(object)
  }

  const meshes = collectSkinnedMeshes(group)
  if (meshes.length === 0) {
    throw new MmdLoadError(
      'parse-error',
      `模型里没有找到可用的蒙皮网格，可能不是有效的 MMD 模型：${modelUrl}`,
    )
  }

  const box = new Box3().setFromObject(group)
  const modelSize = new Vector3()
  const modelCenter = new Vector3()
  if (!box.isEmpty()) {
    box.getSize(modelSize)
    box.getCenter(modelCenter)
  }

  return {
    group,
    meshes,
    morphs: collectMorphs(meshes),
    modelCenter,
    modelSize,
  }
}

/**
 * Normalise an MMD model so it shares one coordinate frame with VRM.
 *
 * MMD is authored in its own unit (1 MMD unit ≈ 0.08 m, so a typical model is
 * ~20 units tall) whereas VRM is in metres (~1.6). Without this the two formats
 * cannot share a camera: an MMD model would tower over a VRM one.
 *
 * Applied in place:
 * - uniformly scaled so the model's height equals `targetHeight` metres;
 * - translated so the model is centred on X/Z and its feet rest on `y = 0`;
 * - optionally yaw-rotated. Both formats end up facing +Z, so the default is
 *   0; `yawOffset` exists for models authored against a different forward axis.
 */
export function normalizeMmdTransform(
  group: Object3D,
  options?: {
    /** Raw bounding box, if already computed by the caller. */
    size?: Vector3
    center?: Vector3
    /** Desired height in metres. Defaults to a 1.6 m human-scale avatar. */
    targetHeight?: number
    /** Extra Y rotation in radians. */
    yawOffset?: number
  },
): { scale: number, height: number } {
  const targetHeight = options?.targetHeight ?? 1.6
  const box = new Box3().setFromObject(group)
  const size = options?.size ?? (box.isEmpty() ? new Vector3(0, 0, 0) : box.getSize(new Vector3()))
  const center = options?.center ?? (box.isEmpty() ? new Vector3() : box.getCenter(new Vector3()))

  // Guard against degenerate/empty bounds — scaling by 0 would erase the model.
  const height = size.y > 1e-6 ? size.y : 0
  const scale = height > 0 ? targetHeight / height : 1

  group.scale.multiplyScalar(scale)

  if (options?.yawOffset)
    group.rotation.y += options.yawOffset

  // Re-measure after scaling so the translation lands the feet on y = 0.
  const scaledBox = new Box3().setFromObject(group)
  if (!scaledBox.isEmpty()) {
    const scaledCenter = scaledBox.getCenter(new Vector3())
    group.position.x -= scaledCenter.x
    group.position.z -= scaledCenter.z
    group.position.y -= scaledBox.min.y
  }
  else if (center.lengthSq() > 0) {
    group.position.sub(center.multiplyScalar(scale))
  }

  return { scale, height }
}

/**
 * Load a VMD motion file as a `three` AnimationClip bound to `object`.
 *
 * `loadAnimation` (rather than the raw `loadVMD`) is used because it resolves
 * both the bone tracks and the morph tracks into one clip, so a single
 * `AnimationMixer` drives the whole motion — the same mechanism VRM uses.
 */
export async function loadVmdClip(
  motionUrl: string,
  target: SkinnedMesh | Camera,
  options?: { onProgress?: (ratio: number) => void },
): Promise<AnimationClip> {
  if (!motionUrl)
    throw new MmdLoadError('file-not-found', '没有指定动作文件路径')

  const loader = new MMDLoader()

  return new Promise<AnimationClip>((resolve, reject) => {
    loader.loadAnimation(
      motionUrl,
      target,
      clip => resolve(clip as AnimationClip),
      (event) => {
        if (!options?.onProgress || !event || event.lengthComputable !== true)
          return
        options.onProgress(Math.min(1, Math.max(0, event.loaded / event.total)))
      },
      err => reject(toMmdLoadError(err, motionUrl)),
    )
  })
}

/**
 * Load raw VMD data.
 *
 * Retained for callers that inspect the motion themselves. Most callers should
 * use `loadVmdClip` (or `createVmdPlayer`) instead — raw VMD does not animate
 * anything on its own.
 */
export async function loadVmdMotion(
  motionUrl: string,
  onProgress?: (ratio: number) => void,
): Promise<unknown> {
  if (!motionUrl)
    throw new MmdLoadError('file-not-found', '没有指定动作文件路径')

  const loader = new MMDLoader()

  return new Promise((resolve, reject) => {
    loader.loadVMD(
      motionUrl,
      vmd => resolve(vmd),
      (event) => {
        if (!onProgress || !event || event.lengthComputable !== true)
          return
        onProgress(Math.min(1, Math.max(0, event.loaded / event.total)))
      },
      err => reject(toMmdLoadError(err, motionUrl)),
    )
  })
}

/**
 * Generate a preview thumbnail for a PMX model using offscreen WebGL.
 */
export async function generatePmxPreview(file: File): Promise<string | undefined> {
  let url: string | undefined
  try {
    url = URL.createObjectURL(file)
    const THREE = await import('three')

    const loaded = await loadPmxModel(url)
    normalizeMmdTransform(loaded.group)

    const canvas = document.createElement('canvas')
    canvas.width = 256
    canvas.height = 256

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false })
    renderer.setSize(256, 256)
    renderer.setPixelRatio(1)

    const scene = new THREE.Scene()
    scene.background = null
    scene.add(new THREE.AmbientLight(0xFFFFFF, 0.6))

    const dirLight = new THREE.DirectionalLight(0xFFFFFF, 0.8)
    dirLight.position.set(1, 2, 3)
    scene.add(dirLight)

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100)
    camera.position.set(0, 0.8, 2.2)
    camera.lookAt(0, 0.8, 0)

    scene.add(loaded.group)
    renderer.render(scene, camera)

    const dataUrl = canvas.toDataURL('image/png')
    renderer.dispose()
    return dataUrl
  }
  catch (err) {
    console.error('[PMXPreview] Failed:', err)
    return undefined
  }
  finally {
    if (url)
      URL.revokeObjectURL(url)
  }
}
