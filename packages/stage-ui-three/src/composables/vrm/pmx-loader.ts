/**
 * PMX/MMD Model Loader for AIJADE
 *
 * Loads PMX/PMD models using Three.js MMDLoader (via three-stdlib).
 * Supports VMD animation data as well.
 */

import type { Group, SkinnedMesh } from 'three'

/**
 * `three-stdlib` is an OPTIONAL peer for MMD/PMX support — it is intentionally
 * NOT a hard dependency. We import it via a variable specifier (rather than a
 * string literal) so `vue-tsc` does not statically resolve the module and fail
 * when it is absent; the surrounding try/catch degrades gracefully at runtime.
 * Install `three-stdlib` to actually enable PMX/PMD/VMD loading.
 */
const MMD_LOADER_SPEC = 'three-stdlib/loaders/MMDLoader'

/**
 * Load a PMX/PMD model file and return the Three.js group.
 * Uses dynamic import to keep the bundle size small.
 */
export async function loadPmxModel(
  modelUrl: string,
  onProgress?: (e: ProgressEvent) => void,
): Promise<{ group: Group, meshes: SkinnedMesh[] } | undefined> {
  try {
    // Dynamic import of three-stdlib MMDLoader
    const { MMDLoader } = await import(MMD_LOADER_SPEC)
    const THREE = await import('three')

    const loader = new MMDLoader()

    return new Promise((resolve, reject) => {
      loader.load(
        modelUrl,
        (pmx: any) => {
          // MMDLoader returns a SkinnedMesh for PMX models
          const group = new THREE.Group()
          if (pmx instanceof THREE.SkinnedMesh) {
            group.add(pmx)
            resolve({ group, meshes: [pmx] })
          }
          else if (pmx instanceof THREE.Group) {
            const meshes: SkinnedMesh[] = []
            pmx.traverse((child: any) => {
              if (child instanceof THREE.SkinnedMesh) {
                meshes.push(child)
              }
            })
            resolve({ group: pmx, meshes })
          }
          else {
            group.add(pmx as any)
            resolve({ group, meshes: [] })
          }
        },
        onProgress,
        (err: any) => {
          console.error('[PMXLoader] Failed to load model:', err)
          reject(err)
        },
      )
    })
  }
  catch (err) {
    console.error('[PMXLoader] Import failed:', err)
    return undefined
  }
}

/**
 * Load a VMD motion file for a PMX model.
 */
export async function loadVmdMotion(
  motionUrl: string,
  onProgress?: (e: ProgressEvent) => void,
): Promise<any | undefined> {
  try {
    const { MMDLoader } = await import(MMD_LOADER_SPEC)

    const loader = new MMDLoader()
    return new Promise((resolve, reject) => {
      loader.loadVMD(
        motionUrl,
        (vmd: any) => {
          resolve(vmd)
        },
        onProgress,
        (err: any) => {
          console.error('[VMDLoader] Failed to load motion:', err)
          reject(err)
        },
      )
    })
  }
  catch (err) {
    console.error('[VMDLoader] Import failed:', err)
    return undefined
  }
}

/**
 * Generate a preview thumbnail for a PMX model using offscreen WebGL.
 */
export async function generatePmxPreview(file: File): Promise<string | undefined> {
  try {
    const url = URL.createObjectURL(file)
    const { loadPmxModel } = await import('./pmx-loader')
    const THREE = await import('three')

    return new Promise((resolve) => {
      const canvas = document.createElement('canvas')
      canvas.width = 256
      canvas.height = 256

      const renderer = new THREE.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: false,
      })
      renderer.setSize(256, 256)
      renderer.setPixelRatio(1)

      const scene = new THREE.Scene()
      scene.background = null

      // Basic lighting
      scene.add(new THREE.AmbientLight(0xFFFFFF, 0.6))
      const dirLight = new THREE.DirectionalLight(0xFFFFFF, 0.8)
      dirLight.position.set(1, 2, 3)
      scene.add(dirLight)

      const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100)
      camera.position.set(0, 1, 5)
      camera.lookAt(0, 0.8, 0)

      loadPmxModel(url).then((result) => {
        if (result) {
          scene.add(result.group)

          // Center the model
          const box = new THREE.Box3()
          result.meshes.forEach((m) => {
            if (m.geometry) {
              m.geometry.computeBoundingBox()
              box.union(new THREE.Box3().copy(m.geometry.boundingBox!).applyMatrix4(m.matrixWorld))
            }
          })
          const center = box.getCenter(new THREE.Vector3())
          result.group.position.sub(center)

          renderer.render(scene, camera)
        }

        renderer.dispose()
        URL.revokeObjectURL(url)
        resolve(canvas.toDataURL('image/png'))
      }).catch(() => {
        renderer.dispose()
        URL.revokeObjectURL(url)
        resolve(undefined)
      })
    })
  }
  catch (err) {
    console.error('[PMXPreview] Failed:', err)
    return undefined
  }
}
