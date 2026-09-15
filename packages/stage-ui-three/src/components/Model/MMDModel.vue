<script setup lang="ts">
/**
 * MMD (PMX/PMD) model renderer.
 *
 * Counterpart to `VRMModel.vue`: same lifecycle contract, same scene wiring
 * (it attaches to the TresJS scene supplied by `ThreeScene.vue` rather than
 * creating its own canvas), same progress/error emits. Keeping the two
 * symmetrical is deliberate — MMD used to be the one format with a loader but
 * no component, which is exactly how code ends up looking implemented while
 * doing nothing.
 *
 * Capabilities:
 * - PMX/PMD meshes with their own toon/sphere material system and textures
 * - skeleton (SkinnedMesh) driven by VMD bone tracks
 * - 表情 via morph targets, either from VMD morph tracks or set directly
 * - VMD motion playback with play/pause/stop and cross-fade
 */

import type { Group, Material, Mesh, SkinnedMesh, Texture } from 'three'

import type { LoadedMmdModel } from '../../composables/vrm/pmx-loader'
import type { VmdPlayer } from '../../composables/vrm/vmd-player'

import { useLoop, useTresContext } from '@tresjs/core'
import { until } from '@vueuse/core'
import { Box3, Vector3 } from 'three'
import { onUnmounted, ref, shallowRef, watch } from 'vue'

import { loadPmxModel, MmdLoadError, normalizeMmdTransform } from '../../composables/vrm/pmx-loader'
import { createVmdPlayer } from '../../composables/vrm/vmd-player'
import { describeWebGLSupport, detectWebGLSupport } from '../../composables/webgl-support'

const props = withDefaults(defineProps<{
  /** URL of the `.pmx` / `.pmd` file. */
  modelSrc?: string
  /** Directory the model's textures resolve against. Defaults to the model's own directory. */
  resourcePath?: string
  /** URL of a `.vmd` motion file to play once the model is ready. */
  motionSrc?: string
  /** Target height in metres. Defaults to 1.6 so MMD shares VRM's scale. */
  targetHeight?: number
  /** Extra Y rotation in radians. */
  modelRotationY?: number
  /** World-space offset applied after normalisation. */
  modelOffset?: [number, number, number]
  paused?: boolean
}>(), {
  targetHeight: 1.6,
  modelRotationY: 0,
  paused: false,
})

const emit = defineEmits<{
  (e: 'loadingProgress', value: number): void
  (e: 'loadStart', value: 'initial-load' | 'model-reload' | 'model-switch'): void
  (e: 'loaded', value: string): void
  (e: 'error', value: unknown): void
}>()

const { scene } = useTresContext()
const { onBeforeRender } = useLoop()

const modelLoaded = ref(false)
const loadingProgress = ref(0)

const activeGroup = shallowRef<Group | undefined>()
const activeModel = shallowRef<LoadedMmdModel | undefined>()
const activePlayer = shallowRef<VmdPlayer | undefined>()

/**
 * Guards the "user switched models while the previous one was still
 * downloading" race. Every load takes a token; when it resolves it is only
 * committed if it still holds the latest one, otherwise its resources are
 * released immediately instead of leaking into the scene.
 */
let loadToken = 0

/**
 * Full GPU-side release. Walking the graph is necessary: `MMDLoader` builds
 * materials that reference toon and sphere textures, and dropping the object
 * without disposing them leaves those textures resident for the page lifetime.
 */
function disposeMmdGroup(group?: Group) {
  if (!group)
    return

  group.traverse((child) => {
    const mesh = child as Mesh
    if (!mesh.isMesh)
      return

    mesh.geometry?.dispose()

    const materials: Material[] = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    for (const material of materials) {
      if (!material)
        continue
      for (const value of Object.values(material as unknown as Record<string, unknown>)) {
        const texture = value as Texture | null
        if (texture && (texture as Texture).isTexture)
          texture.dispose()
      }
      material.dispose()
    }
  })

  group.removeFromParent()
}

function releaseActive() {
  activePlayer.value?.dispose()
  activePlayer.value = undefined
  disposeMmdGroup(activeGroup.value)
  activeGroup.value = undefined
  activeModel.value = undefined
}

async function loadModel(src: string) {
  const token = ++loadToken

  // Without this the failure happens somewhere inside three.js and the user is
  // left with an empty stage and no explanation.
  const webgl = detectWebGLSupport()
  if (!webgl.supported) {
    emit('error', new MmdLoadError('unsupported-browser', describeWebGLSupport(webgl)))
    return
  }

  emit('loadStart', activeGroup.value ? 'model-switch' : 'initial-load')
  modelLoaded.value = false
  loadingProgress.value = 0

  let loaded: LoadedMmdModel
  try {
    loaded = await loadPmxModel(src, {
      resourcePath: props.resourcePath,
      onProgress: (ratio) => {
        if (token === loadToken)
          loadingProgress.value = ratio
        emit('loadingProgress', ratio)
      },
    })
  }
  catch (error) {
    // Only the newest load gets to report an error; a superseded one is noise.
    if (token === loadToken)
      emit('error', error)
    return
  }

  // Superseded while downloading — free what we built and stay silent.
  if (token !== loadToken) {
    disposeMmdGroup(loaded.group)
    return
  }

  // Free the outgoing model *before* adding the incoming one, so the scene
  // never holds two avatars at once.
  releaseActive()

  normalizeMmdTransform(loaded.group, {
    size: loaded.modelSize,
    center: loaded.modelCenter,
    targetHeight: props.targetHeight,
    yawOffset: props.modelRotationY,
  })

  if (props.modelOffset)
    loaded.group.position.add(new Vector3(...props.modelOffset))

  activeModel.value = loaded
  activeGroup.value = loaded.group
  activePlayer.value = createVmdPlayer(loaded.group)

  await until(() => scene.value).toBeTruthy()
  if (token !== loadToken) {
    releaseActive()
    return
  }

  scene.value?.add(loaded.group)
  modelLoaded.value = true
  loadingProgress.value = 1
  emit('loadingProgress', 1)
  emit('loaded', src)

  if (props.motionSrc)
    await loadMotion(props.motionSrc, token)
}

async function loadMotion(src: string, token: number) {
  const player = activePlayer.value
  if (!player)
    return

  try {
    await player.load(src, {
      onProgress: ratio => emit('loadingProgress', ratio),
    })
  }
  catch (error) {
    if (token === loadToken)
      emit('error', error)
  }
}

watch(() => props.modelSrc, (src) => {
  if (!src) {
    loadToken++
    releaseActive()
    modelLoaded.value = false
    return
  }
  void loadModel(src)
}, { immediate: true })

watch(() => props.motionSrc, (src) => {
  const player = activePlayer.value
  if (!player)
    return
  if (!src) {
    player.stop()
    return
  }
  void loadMotion(src, loadToken)
})

watch(() => props.paused, (paused) => {
  const player = activePlayer.value
  if (!player)
    return
  if (paused)
    player.pause()
  else
    player.play()
})

// `useLoop().onBeforeRender` returns a handle, not a teardown function.
const renderLoopHandle = onBeforeRender(({ delta }) => {
  if (props.paused)
    return
  activePlayer.value?.update(delta)
})

onUnmounted(() => {
  renderLoopHandle?.off?.()
  loadToken++
  releaseActive()
  modelLoaded.value = false
})

/** Morph (表情) names available on the loaded model. */
const morphNames = ref<string[]>([])

watch(activeModel, (model) => {
  const names = new Set<string>()
  if (model) {
    for (const targets of model.morphs.values()) {
      for (const target of targets)
        names.add(target.name)
    }
  }
  morphNames.value = [...names]
})

/**
 * Set a morph (表情) weight by name, across every mesh that defines it.
 * Returns how many meshes were affected — 0 means the name is not on this
 * model, which callers should treat as "expression unavailable", not success.
 */
function setMorph(name: string, weight: number): number {
  const model = activeModel.value
  if (!model)
    return 0

  let affected = 0
  for (const [mesh, targets] of model.morphs) {
    const target = targets.find(t => t.name === name)
    if (!target)
      continue
    const influences = (mesh as SkinnedMesh).morphTargetInfluences
    if (!influences || target.index >= influences.length)
      continue
    influences[target.index] = Math.min(1, Math.max(0, weight))
    affected++
  }
  return affected
}

/** Current world-space bounding box of the loaded model, or undefined. */
function getBounds(): { size: Vector3, center: Vector3 } | undefined {
  const group = activeGroup.value
  if (!group)
    return undefined
  const box = new Box3().setFromObject(group)
  if (box.isEmpty())
    return undefined
  return { size: box.getSize(new Vector3()), center: box.getCenter(new Vector3()) }
}

function toMessage(error: unknown): string {
  const code = (error as MmdLoadError | undefined)?.code
  if (error instanceof Error && code)
    return error.message
  if (error instanceof Error)
    return `MMD 模型加载失败：${error.message}`
  return 'MMD 模型加载失败：未知错误'
}

defineExpose({
  modelLoaded,
  loadingProgress,
  morphNames,
  /** The TresJS scene this model was attached to. */
  scene: () => scene.value,
  setMorph,
  getBounds,
  play: () => activePlayer.value?.play(),
  pause: () => activePlayer.value?.pause(),
  stop: () => activePlayer.value?.stop(),
  seek: (seconds: number) => activePlayer.value?.seek(seconds),
  duration: () => activePlayer.value?.duration ?? 0,
  toMessage,
})
</script>

<template>
  <slot v-if="modelLoaded" />
</template>
