/**
 * Inochi2D 模型类型（best-effort，基于 Inochi2D Puppet 规范 / `modules/inp`）。
 *
 * 注意：Inochi2D 的 `.inp` 是 **JSON** 格式（INP1/INP2），与 Live2D 的 `.moc3`（私有二进制）**完全不同**。
 * 这些类型用于 MVP 解析 + 静态首帧渲染；字段以实际 Inochi Creator 导出为准，待真机校验后可能微调。
 *
 * 参考：Inochi2D/inochi2d `source/inochi2d/core` 与 `modules/inp`（INP1/INP2 序列化 + CRC）。
 */

/** 2D 向量 */
export type Vec2 = [number, number]

/** 部件变换（相对父节点的偏移） */
export interface Inochi2DTransform {
  /** 位移 X（像素，模型空间） */
  x: number
  /** 位移 Y（像素，模型空间，Y 向下为正） */
  y: number
  /** 旋转（度） */
  rotation: number
  /** 缩放 X */
  scaleX: number
  /** 缩放 Y */
  scaleY: number
}

/**
 * 一个 Inochi2D 部件（Part / 网格节点）。
 * 网格由 `verts`（模型局部坐标）+ `uvs`（贴图坐标 0..1）+ `indices`（三角形索引）定义。
 */
export interface Inochi2DPart {
  name: string
  uuid: string
  /** z 排序，数值越小越靠后 */
  zsort: number
  transform: Inochi2DTransform
  /** 网格顶点（局部坐标，相对部件原点） */
  verts: Vec2[]
  /** 贴图 UV 坐标（0..1） */
  uvs: Vec2[]
  /** 三角形索引（每 3 个一组） */
  indices: number[]
  /** 贴图相对路径（相对 .inp 所在目录） */
  texturePath?: string
  /** 父节点 uuid（根节点为 null / 空） */
  parent?: string | null
}

/**
 * 参数（驱动网格形变）。Inochi2D 通过 `binding` 把参数映射到各部件的 transform 取值区间。
 * MVP 仅记录，形变驱动为后续工作。
 */
export interface Inochi2DParameterBinding {
  /** 目标部件 uuid */
  target: string
  /** 沿 X 轴的最小值/最大值（参数=−1 / +1 时） */
  x?: [number, number]
  /** 沿 Y 轴的最小值/最大值 */
  y?: [number, number]
}

export interface Inochi2DParameter {
  uuid: string
  name: string
  binding: Inochi2DParameterBinding[]
}

/** 解析后的 Inochi2D 木偶模型（不含贴图位图） */
export interface Inochi2DPuppet {
  name: string
  /** 格式版本，如 "0.1" */
  version: string
  parts: Inochi2DPart[]
  parameters: Inochi2DParameter[]
}

/** 已加载、贴图已解析为可绘制图像的完整模型 */
export interface LoadedInochi2DModel {
  puppet: Inochi2DPuppet
  /**
   * 贴图位图，key = 解析后的绝对 URL 或相对 texturePath。
   * 渲染时按 part.texturePath 查找。
   */
  textures: Map<string, HTMLImageElement>
}
