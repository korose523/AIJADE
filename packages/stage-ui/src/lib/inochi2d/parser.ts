/**
 * Inochi2D `.inp` / `.inx` 解析与加载（MVP：解析结构 + 解析贴图位图）。
 *
 * - `parseInp()`：把任意 JSON 结构化为 `Inochi2DPuppet`（容错，缺失字段给默认值）。
 * - `loadInochi2DModel()`：拉取模型 JSON + 相对贴图，返回 `LoadedInochi2DModel`。
 *
 * 设计前提（待真机校验）：
 *  - `.inp` 是 JSON，顶层含 `nodes`（部件树，扁平数组 + `parent` uuid 引用）与 `parameters`。
 *  - 贴图路径相对 `.inp` 所在目录解析。
 *  - 支持直接 `.inp`/`.inx` URL；`.zip` 打包支持为后续工作（见 Inochi2dModel.vue 的 TODO）。
 */

import type {
  Inochi2DParameter,
  Inochi2DPart,
  Inochi2DPuppet,
  Inochi2DTransform,
  LoadedInochi2DModel,
  Vec2,
} from './types'

function asVec2Array(input: unknown): Vec2[] {
  if (!Array.isArray(input))
    return []
  const out: Vec2[] = []
  for (const item of input) {
    if (Array.isArray(item) && item.length >= 2 && typeof item[0] === 'number' && typeof item[1] === 'number')
      out.push([item[0], item[1]])
  }
  return out
}

function asNumberArray(input: unknown): number[] {
  if (!Array.isArray(input))
    return []
  return input.filter((n: unknown): n is number => typeof n === 'number')
}

function parseTransform(input: unknown): Inochi2DTransform {
  const t = (input ?? {}) as Record<string, unknown>
  return {
    x: typeof t.x === 'number' ? t.x : 0,
    y: typeof t.y === 'number' ? t.y : 0,
    rotation: typeof t.rotation === 'number' ? t.rotation : 0,
    scaleX: typeof t.scaleX === 'number' ? t.scaleX : 1,
    scaleY: typeof t.scaleY === 'number' ? t.scaleY : 1,
  }
}

function parsePart(raw: Record<string, unknown>): Inochi2DPart {
  // 网格可能直接平铺在 part 上，也可能包在 `mesh` 对象里
  const mesh = (raw.mesh ?? raw) as Record<string, unknown>
  const texturePath
    = typeof (raw.texturePath ?? (raw.texture as Record<string, unknown> | undefined)?.texturePath) === 'string'
      ? (raw.texturePath ?? (raw.texture as Record<string, unknown>)?.texturePath) as string
      : undefined

  return {
    name: typeof raw.name === 'string' ? raw.name : 'unnamed',
    uuid: typeof raw.uuid === 'string' ? raw.uuid : crypto.randomUUID(),
    zsort: typeof raw.zsort === 'number' ? raw.zsort : 0,
    transform: parseTransform(raw.transform),
    verts: asVec2Array(mesh.verts),
    uvs: asVec2Array(mesh.uvs),
    indices: asNumberArray(mesh.indices),
    texturePath,
    parent: typeof raw.parent === 'string' ? raw.parent : null,
  }
}

function parseParameter(raw: Record<string, unknown>): Inochi2DParameter {
  const bindingRaw = Array.isArray(raw.binding) ? raw.binding : []
  return {
    uuid: typeof raw.uuid === 'string' ? raw.uuid : crypto.randomUUID(),
    name: typeof raw.name === 'string' ? raw.name : 'param',
    binding: bindingRaw
      .filter((b: unknown): b is Record<string, unknown> => typeof b === 'object' && b !== null)
      .map((b) => {
        const out: Inochi2DParameter['binding'][number] = { target: String(b.target ?? '') }
        if (Array.isArray(b.x) && b.x.length === 2)
          out.x = [Number(b.x[0]), Number(b.x[1])]
        if (Array.isArray(b.y) && b.y.length === 2)
          out.y = [Number(b.y[0]), Number(b.y[1])]
        return out
      }),
  }
}

/** 把任意 JSON 结构化为 Inochi2DPuppet（容错） */
export function parseInp(json: unknown): Inochi2DPuppet {
  const root = (json ?? {}) as Record<string, unknown>
  const nodes = Array.isArray(root.nodes) ? root.nodes : []
  const parameters = Array.isArray(root.parameters) ? root.parameters : []

  return {
    name: typeof root.name === 'string' ? root.name : 'Inochi2D Puppet',
    version: typeof root.version === 'string' ? root.version : '0.1',
    parts: nodes
      .filter((n: unknown): n is Record<string, unknown> => typeof n === 'object' && n !== null)
      .map(parsePart),
    parameters: parameters
      .filter((p: unknown): p is Record<string, unknown> => typeof p === 'object' && p !== null)
      .map(parseParameter),
  }
}

async function loadTexture(resolvedUrl: string): Promise<HTMLImageElement> {
  const img = new Image()
  img.crossOrigin = 'anonymous'
  img.src = resolvedUrl
  await img.decode()
  return img
}

/**
 * 加载 Inochi2D 模型：拉取 JSON + 相对贴图。
 * @param src 模型 `.inp`/`.inx` 的绝对或相对 URL（同源或允许 CORS）。
 */
export async function loadInochi2DModel(src: string): Promise<LoadedInochi2DModel> {
  const res = await fetch(src)
  if (!res.ok)
    throw new Error(`Failed to fetch Inochi2D model: ${res.status} ${res.statusText}`)
  const json = await res.json()
  const puppet = parseInp(json)

  const textures = new Map<string, HTMLImageElement>()
  const seen = new Set<string>()

  for (const part of puppet.parts) {
    if (!part.texturePath || seen.has(part.texturePath))
      continue
    seen.add(part.texturePath)
    try {
      const resolved = new URL(part.texturePath, src).href
      textures.set(part.texturePath, await loadTexture(resolved))
    }
    catch (err) {
      // 单张贴图失败不应阻断整体加载；渲染时该部件留空
      console.warn(`[inochi2d] texture load failed: ${part.texturePath}`, err)
    }
  }

  return { puppet, textures }
}
