<script setup lang="ts">
/**
 * Inochi2dModel.vue — AIJADE 的 Inochi2D 渲染组件（MVP：最小静态首帧渲染）。
 *
 * 路线 B（完全开源）的渲染后端入口。当前阶段只做：
 *   1. 拉取 `.inp`/`.inx` 模型 JSON（经 lib/inochi2d/parser）
 *   2. 解析贴图
 *   3. 在 <canvas> 上绘制**未形变的首帧静态姿态**（按部件 zsort 叠加网格三角面）
 *
 * TODO（等真机 .inp 资产后迭代）：
 *   - 参数化网格形变（Inochi2D `parameters[].binding` → 部件 transform 插值）
 *   - 表情/动作驱动（接 Emotion 枚举 → lib/inochi2d/emotion.ts）
 *   - 物理（头发/衣物摆动）
 *   - 父节点变换链合成（当前仅用部件自身 transform，未合成 parent）
 *   - 支持 `.zip` 打包模型
 *   - 唇形同步（接 mouthOpenSize / nowSpeaking，暂未使用）
 */

import type { LoadedInochi2DModel, Vec2 } from '../../../lib/inochi2d/types'

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { loadInochi2DModel } from '../../../lib/inochi2d/parser'

const props = withDefaults(defineProps<{
  /** 模型 `.inp`/`.inx` 的 URL（同源或允许 CORS） */
  modelSrc?: string
  modelId?: string
  paused?: boolean
  /** 唇形开合量 0..1（MVP 未使用，预留） */
  mouthOpenSize?: number
  /** 是否正在说话（MVP 未使用，预留） */
  nowSpeaking?: boolean
}>(), {
  paused: false,
  mouthOpenSize: 0,
  nowSpeaking: false,
})

const canvasRef = ref<HTMLCanvasElement | null>(null)
const status = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const errorMessage = ref<string>('')

let loaded: LoadedInochi2DModel | null = null

const DEG2RAD = Math.PI / 180

/** 解 3x3 线性方程组，求仿射矩阵把 src 三角形映射到 dst 三角形 */
function affineFromTriangles(src: [number, number][], dst: [number, number][]): [number, number, number, number, number, number] {
  const [ax, ay] = src[0]
  const [bx, by] = src[1]
  const [cx, cy] = src[2]
  const [dx, dy] = dst[0]
  const [ex, ey] = dst[1]
  const [fx, fy] = dst[2]

  const det = ax * (by - cy) - ay * (bx - cx) + (bx * cy - by * cx)
  if (Math.abs(det) < 1e-8)
    return [1, 0, 0, 1, 0, 0]

  const invDet = 1 / det
  // 解 x 系统: [a, c, e] 使得 a*P + c*Q + e = dst.x
  const a = ((dx - ex) * (by - cy) - (fx - dx) * (ay - by)) * invDet
  const c = ((fx - dx) * (ay - cy) - (dx - ex) * (ax - cx)) * invDet
  const e = dx - a * ax - c * ay
  const b = ((ey - dy) * (by - cy) - (fy - ey) * (ay - by)) * invDet
  const d = ((fy - ey) * (ay - cy) - (ey - dy) * (ax - cx)) * invDet
  const f = dy - b * ax - d * ay
  return [a, b, c, d, e, f]
}

function drawTexturedTriangle(
  ctx: CanvasRenderingContext2D,
  img: HTMLImageElement,
  srcTexel: [number, number][],
  dstCanvas: [number, number][],
) {
  const [a, b, c, d, e, f] = affineFromTriangles(srcTexel, dstCanvas)
  ctx.save()
  ctx.beginPath()
  ctx.moveTo(dstCanvas[0][0], dstCanvas[0][1])
  ctx.lineTo(dstCanvas[1][0], dstCanvas[1][1])
  ctx.lineTo(dstCanvas[2][0], dstCanvas[2][1])
  ctx.closePath()
  ctx.clip()
  ctx.transform(a, b, c, d, e, f)
  ctx.drawImage(img, 0, 0)
  ctx.restore()
}

/** 把部件局部顶点经 transform 转到世界坐标（MVP：仅部件自身 transform，未合成 parent） */
function partWorldVerts(part: LoadedInochi2DModel['puppet']['parts'][number]): Vec2[] {
  const { x, y, rotation, scaleX, scaleY } = part.transform
  const rad = rotation * DEG2RAD
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  return part.verts.map(([vx, vy]) => {
    const sx = vx * scaleX
    const sy = vy * scaleY
    return [x + (sx * cos - sy * sin), y + (sx * sin + sy * cos)] as Vec2
  })
}

function renderStatic() {
  const canvas = canvasRef.value
  if (!canvas || !loaded)
    return
  const ctx = canvas.getContext('2d')
  if (!ctx)
    return

  const dpr = window.devicePixelRatio || 1
  const cssW = canvas.clientWidth || 512
  const cssH = canvas.clientHeight || 512
  canvas.width = Math.round(cssW * dpr)
  canvas.height = Math.round(cssH * dpr)
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, cssW, cssH)

  const parts = [...loaded.puppet.parts].sort((p, q) => p.zsort - q.zsort)
  if (parts.length === 0)
    return

  // 计算世界包围盒，居中绘制
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  const worldByPart = new Map<string, Vec2[]>()
  for (const part of parts) {
    const world = partWorldVerts(part)
    worldByPart.set(part.uuid, world)
    for (const [wx, wy] of world) {
      if (wx < minX)
        minX = wx
      if (wy < minY)
        minY = wy
      if (wx > maxX)
        maxX = wx
      if (wy > maxY)
        maxY = wy
    }
  }
  const modelW = Math.max(maxX - minX, 1)
  const modelH = Math.max(maxY - minY, 1)
  const scale = Math.min((cssW * 0.9) / modelW, (cssH * 0.9) / modelH)
  const offsetX = (cssW - modelW * scale) / 2 - minX * scale
  const offsetY = (cssH - modelH * scale) / 2 - minY * scale

  for (const part of parts) {
    if (!part.texturePath)
      continue
    const img = loaded!.textures.get(part.texturePath)
    if (!img)
      continue
    const world = worldByPart.get(part.uuid)!
    const tw = img.naturalWidth || img.width
    const th = img.naturalHeight || img.height
    const idx = part.indices
    for (let i = 0; i + 2 < idx.length; i += 3) {
      const i0 = idx[i]
      const i1 = idx[i + 1]
      const i2 = idx[i + 2]
      const u0 = part.uvs[i0]
      const u1 = part.uvs[i1]
      const u2 = part.uvs[i2]
      if (!u0 || !u1 || !u2)
        continue
      const srcTexel: [number, number][] = [
        [u0[0] * tw, u0[1] * th],
        [u1[0] * tw, u1[1] * th],
        [u2[0] * tw, u2[1] * th],
      ]
      const dstCanvas: [number, number][] = [
        [world[i0][0] * scale + offsetX, world[i0][1] * scale + offsetY],
        [world[i1][0] * scale + offsetX, world[i1][1] * scale + offsetY],
        [world[i2][0] * scale + offsetX, world[i2][1] * scale + offsetY],
      ]
      drawTexturedTriangle(ctx, img, srcTexel, dstCanvas)
    }
  }
}

async function loadAndRender() {
  if (!props.modelSrc) {
    status.value = 'idle'
    return
  }
  status.value = 'loading'
  errorMessage.value = ''
  try {
    loaded = await loadInochi2DModel(props.modelSrc)
    status.value = 'ready'
    // 等 DOM 尺寸就绪后绘制
    await new Promise(resolve => requestAnimationFrame(resolve))
    renderStatic()
  }
  catch (err) {
    status.value = 'error'
    errorMessage.value = err instanceof Error ? err.message : String(err)
    console.error('[Inochi2dModel] load failed', err)
  }
}

watch(() => props.modelSrc, loadAndRender)
onMounted(loadAndRender)
onBeforeUnmount(() => {
  loaded = null
})
</script>

<template>
  <div class="relative h-full w-full flex items-center justify-center bg-transparent">
    <canvas
      v-show="status === 'ready'"
      ref="canvasRef"
      class="h-full w-full"
    />
    <div
      v-if="status === 'loading'"
      class="absolute inset-0 flex items-center justify-center text-sm text-neutral-400"
    >
      加载 Inochi2D 模型中…
    </div>
    <div
      v-else-if="status === 'error'"
      class="absolute inset-0 flex flex-col items-center justify-center gap-1 px-4 text-center text-sm text-red-400"
    >
      <span>Inochi2D 模型加载失败</span>
      <span class="text-xs text-red-300/80">{{ errorMessage }}</span>
    </div>
    <div
      v-else-if="status === 'idle'"
      class="absolute inset-0 flex items-center justify-center text-sm text-neutral-400"
    >
      未选择 Inochi2D 模型
    </div>
  </div>
</template>
