import localforage from 'localforage'

import { until } from '@vueuse/core'
import { nanoid } from 'nanoid'
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { resolveAssetVersionHash } from '../utils/asset-identity'

export enum DisplayModelFormat {
  Live2dZip = 'live2d-zip',
  Live2dDirectory = 'live2d-directory',
  VRM = 'vrm',
  GLB = 'glb',
  SpineZip = 'spine-zip',
  PMXZip = 'pmx-zip',
  PMXDirectory = 'pmx-directory',
  PMD = 'pmd',
  Inochi2d = 'inochi2d',
}

export type DisplayModel
  = | DisplayModelFile
    | DisplayModelURL

const presetLive2dProUrl = new URL('../assets/live2d/models/hiyori_pro_zh.zip', import.meta.url).href
const presetLive2dFreeUrl = new URL('../assets/live2d/models/hiyori_free_zh.zip', import.meta.url).href
const presetLive2dPreview = new URL('../assets/live2d/models/hiyori/preview.png', import.meta.url).href
const presetJadeMaidUrl = new URL('../assets/live2d/models/jade_maid.zip', import.meta.url).href
const presetJadeMaidPreview = new URL('../assets/live2d/models/jade_maid/preview.jpg', import.meta.url).href
const presetVrmAvatarAUrl = new URL('../assets/vrm/models/AvatarSample-A/AvatarSample_A.vrm', import.meta.url).href
const presetVrmAvatarAPreview = new URL('../assets/vrm/models/AvatarSample-A/preview.png', import.meta.url).href
const presetVrmAvatarBUrl = new URL('../assets/vrm/models/AvatarSample-B/AvatarSample_B.vrm', import.meta.url).href
const presetVrmAvatarBPreview = new URL('../assets/vrm/models/AvatarSample-B/preview.png', import.meta.url).href

export interface DisplayModelFile {
  id: string
  format: DisplayModelFormat
  type: 'file'
  file: File
  name: string
  previewImage?: string
  importedAt: number
  /**
   * Deterministic version hash of the model asset (content hash for files,
   * reference hash for urls). Optional so that pre-existing IndexedDB records
   * and the in-module preset array (which are populated without a hash at load
   * time) remain valid; it is filled lazily via `getDisplayModelAssetVersionHash`.
   */
  assetVersionHash?: string
}

export interface DisplayModelURL {
  id: string
  format: DisplayModelFormat
  type: 'url'
  url: string
  name: string
  previewImage?: string
  importedAt: number
  /**
   * Deterministic version hash of the model asset (reference hash for urls).
   * Optional for the same backward-compatibility reason as `DisplayModelFile`.
   */
  assetVersionHash?: string
}

const displayModelsPresets: DisplayModel[] = [
  { id: 'preset-live2d-1', format: DisplayModelFormat.Live2dZip, type: 'url', url: presetLive2dProUrl, name: 'Hiyori (Pro)', previewImage: presetLive2dPreview, importedAt: 1733113886840 },
  { id: 'preset-live2d-2', format: DisplayModelFormat.Live2dZip, type: 'url', url: presetLive2dFreeUrl, name: 'Hiyori (Free)', previewImage: presetLive2dPreview, importedAt: 1733113886840 },
  { id: 'preset-live2d-jade', format: DisplayModelFormat.Live2dZip, type: 'url', url: presetJadeMaidUrl, name: 'Jade (Maid)', previewImage: presetJadeMaidPreview, importedAt: 1752247200000 },
  { id: 'preset-vrm-1', format: DisplayModelFormat.VRM, type: 'url', url: presetVrmAvatarAUrl, name: 'AvatarSample_A', previewImage: presetVrmAvatarAPreview, importedAt: 1733113886840 },
  { id: 'preset-vrm-2', format: DisplayModelFormat.VRM, type: 'url', url: presetVrmAvatarBUrl, name: 'AvatarSample_B', previewImage: presetVrmAvatarBPreview, importedAt: 1733113886840 },
]

export const useDisplayModelsStore = defineStore('display-models', () => {
  const displayModels = ref<DisplayModel[]>([])

  let generateLive2DPreview: (file: File) => Promise<string | undefined>
  let generateVrmPreview: (file: File) => Promise<string | undefined>
  let generateSpinePreview: (file: File) => Promise<string | undefined>

  const displayModelsFromIndexedDBLoading = ref(false)

  async function loadDisplayModelsFromIndexedDB() {
    await until(displayModelsFromIndexedDBLoading).toBe(false)

    displayModelsFromIndexedDBLoading.value = true
    const models = [...displayModelsPresets]

    try {
      await localforage.iterate<{ format: DisplayModelFormat, file: File, importedAt: number, previewImage?: string }, void>((val, key) => {
        if (key.startsWith('display-model-')) {
          models.push({ id: key, format: val.format, type: 'file', file: val.file, name: val.file.name, importedAt: val.importedAt, previewImage: val.previewImage })
        }
      })
    }
    catch (err) {
      console.error(err)
    }

    displayModels.value = models.sort((a, b) => b.importedAt - a.importedAt)
    displayModelsFromIndexedDBLoading.value = false
  }

  async function getDisplayModel(id: string) {
    await until(displayModelsFromIndexedDBLoading).toBe(false)
    // NOTICE:
    // Newly imported file models are inserted into displayModels before callers pick them.
    // Reading memory first keeps updateStageModel from racing an IndexedDB write and treating
    // a just-imported display-model id as missing, which used to fall back to the default model.
    // Source/context: model-selector confirmImport/handleAddVRMModel -> model-settings handleModelPick.
    // Removal condition: custom model imports and selection are handled by a single transactional API.
    const modelFromMemory = displayModels.value.find(model => model.id === id)
    if (modelFromMemory)
      return modelFromMemory

    const modelFromFile = await localforage.getItem<DisplayModelFile>(id)
    if (modelFromFile) {
      return modelFromFile
    }

    // Fallback to in-memory presets if not found in localforage
    return displayModelsPresets.find(model => model.id === id)
  }

  const loadLive2DModelPreview = (file: File) => generateLive2DPreview(file)
  const loadVrmModelPreview = (file: File) => generateVrmPreview(file)
  const loadSpineModelPreview = (file: File) => generateSpinePreview(file)

  async function addDisplayModel(format: DisplayModelFormat, file: File) {
    await until(displayModelsFromIndexedDBLoading).toBe(false)
    const newDisplayModel: DisplayModelFile = { id: `display-model-${nanoid()}`, format, type: 'file', file, name: file.name, importedAt: Date.now() }

    if (format === DisplayModelFormat.Live2dZip) {
      const previewImage = await loadLive2DModelPreview(file)
      newDisplayModel.previewImage = previewImage
    }
    else if (format === DisplayModelFormat.VRM || format === DisplayModelFormat.GLB) {
      const previewImage = await loadVrmModelPreview(file)
      newDisplayModel.previewImage = previewImage
    }
    else if (format === DisplayModelFormat.SpineZip) {
      const previewImage = await loadSpineModelPreview(file)
      newDisplayModel.previewImage = previewImage
    }
    else if (format === DisplayModelFormat.PMXZip || format === DisplayModelFormat.PMXDirectory || format === DisplayModelFormat.PMD) {
      // PMX/MMD models — no preview generation (complex rendering pipeline)
      // Preview will show a placeholder
    }
    else if (format === DisplayModelFormat.Inochi2d) {
      // Inochi2D (.inp/.inx) — preview generation deferred to the Inochi2D renderer.
      // The renderer draws a first-frame static preview; no placeholder generation here.
    }

    // Compute the asset version hash and persist it together with the record, so
    // a model is always auditable once it lands in IndexedDB. Keep this before
    // the awaited `localforage.setItem` below (see the NOTICE on that call).
    newDisplayModel.assetVersionHash = await resolveAssetVersionHash(newDisplayModel)

    displayModels.value.unshift(newDisplayModel)

    // NOTICE:
    // Keep this awaited. The settings model pick flow can call getDisplayModel immediately
    // after import; fire-and-forget persistence creates a race where the selected custom model
    // exists in the UI but is not yet readable from IndexedDB in a later route/render pass.
    // Source/context: model-selector import flow -> settings-stage-model.updateStageModel().
    // Removal condition: imported display models are persisted through a transactional queue
    // that blocks pick/navigation until the write is durably complete.
    await localforage.setItem<DisplayModelFile>(newDisplayModel.id, newDisplayModel)
      .catch(err => console.error(err))

    return newDisplayModel
  }

  /**
   * Lazily resolve and cache the asset version hash for any display model by id.
   *
   * The preset array is populated at module load *without* a hash (we must not
   * make that array async), so the hash is computed on demand here — going
   * through `getDisplayModel` and `resolveAssetVersionHash` (which memoises by
   * `id` + a cheap change token). Returns `undefined` if the model is unknown.
   */
  async function getDisplayModelAssetVersionHash(id: string): Promise<string | undefined> {
    const model = await getDisplayModel(id)
    if (!model)
      return undefined
    return resolveAssetVersionHash(model)
  }

  async function renameDisplayModel(id: string, name: string) {
    await until(displayModelsFromIndexedDBLoading).toBe(false)
    const displayModel = id.startsWith('display-model-')
      ? await localforage.getItem<DisplayModelFile>(id)
      : displayModels.value.find(m => m.id === id)

    if (!displayModel)
      return

    displayModel.name = name

    // Update reactive state
    const index = displayModels.value.findIndex(m => m.id === id)
    if (index !== -1) {
      displayModels.value[index].name = name
    }

    // Persist if it's a file-based model
    if (id.startsWith('display-model-')) {
      await localforage.setItem(id, displayModel)
    }
  }

  async function removeDisplayModel(id: string) {
    await until(displayModelsFromIndexedDBLoading).toBe(false)
    await localforage.removeItem(id)
    displayModels.value = displayModels.value.filter(model => model.id !== id)
  }

  async function resetDisplayModels() {
    await loadDisplayModelsFromIndexedDB()
    const userModelIds = displayModels.value.filter(model => model.type === 'file').map(model => model.id)
    for (const id of userModelIds) {
      await removeDisplayModel(id)
    }

    displayModels.value = [...displayModelsPresets].sort((a, b) => b.importedAt - a.importedAt)
  }

  async function initialize() {
    await import('@proj-aijade/stage-ui-live2d/utils/live2d-zip-loader')
    await import('@proj-aijade/stage-ui-live2d/utils/live2d-opfs-registration')

    const { loadLive2DModelPreview } = await import('@proj-aijade/stage-ui-live2d/utils/live2d-preview')
    const { loadVrmModelPreview } = await import('@proj-aijade/stage-ui-three/utils/vrm-preview')
    const { loadSpineModelPreview } = await import('@proj-aijade/stage-ui-spine/utils/spine-preview')

    generateLive2DPreview = loadLive2DModelPreview
    generateVrmPreview = loadVrmModelPreview
    generateSpinePreview = loadSpineModelPreview
  }

  return {
    displayModels,
    displayModelsFromIndexedDBLoading,

    initialize,
    loadDisplayModelsFromIndexedDB,
    getDisplayModel,
    getDisplayModelAssetVersionHash,
    addDisplayModel,
    renameDisplayModel,
    removeDisplayModel,
    resetDisplayModels,
  }
})
