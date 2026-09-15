import type { Episode } from './types'

import { describe, expect, it } from 'vitest'

import { buildMemory, loadLocomo } from './locomo'
import { BioticMemory } from './store'
import { DEFAULT_GATING, DEFAULT_MEMORY_CONFIG, NO_GATING } from './types'

/**
 * 实验用注入点的不变式测试。
 *
 * 背景：`eval/` 下的记忆线实验（oracle vs 预测显著性、分位保留扫描、并列打破对照）
 * 全部依赖 `EncodeInput.salienceOverride`、`consolidate({ selective, keepFraction })`
 * 与 `BuildMemoryOptions` 这三个**为实验而加**的注入点。
 *
 * 这些不变式若只存在于实验脚本的假定里，就是又一次"静默假设"——
 * 本仓库已经因此付出代价（`diag-gate-prunes-evidence.ts` 数错池子却给出绿灯）。
 * 因此在此固化为可执行断言。
 */

function mkMem(gating = NO_GATING, overrides: Partial<typeof DEFAULT_MEMORY_CONFIG> = {}): BioticMemory {
  return new BioticMemory({ ...DEFAULT_MEMORY_CONFIG, gating, ...overrides }, 1_000_000)
}

function enc(m: BioticMemory, i: number, content: string, salienceOverride?: number): Episode {
  return m.encode({
    id: `e${i}`,
    content,
    createdAt: 1_000 + i,
    context: { tags: [] },
    salienceOverride,
  })
}

describe('encodeInput.salienceOverride', () => {
  it('不传时与预测器路径逐位一致（向后兼容）', () => {
    const a = mkMem()
    const b = mkMem()
    const ea = enc(a, 0, 'Caroline went to the support group on Tuesday')
    const eb = enc(b, 0, 'Caroline went to the support group on Tuesday')
    expect(ea.encoding.salience).toBe(eb.encoding.salience)
    expect(ea.durability).toBe(eb.durability)
  })

  it('传入时覆盖预测值，并驱动 durability', () => {
    const low = enc(mkMem(DEFAULT_GATING), 0, 'haha yeah', 0)
    const high = enc(mkMem(DEFAULT_GATING), 1, 'haha yeah', 1)
    expect(low.encoding.salience).toBe(0)
    expect(high.encoding.salience).toBe(1)
    // durability = 1 + kSalience*salience + kSocial*social
    expect(high.durability).toBeGreaterThan(low.durability)
  })

  it('取值被 clamp 到 [0,1]', () => {
    expect(enc(mkMem(), 0, 'x', 5).encoding.salience).toBe(1)
    expect(enc(mkMem(), 1, 'x', -5).encoding.salience).toBe(0)
  })

  it('nO_GATING 下覆盖显著性不改变 durability（门控系数为 0）', () => {
    expect(enc(mkMem(NO_GATING), 0, 'x', 0).durability).toBe(1)
    expect(enc(mkMem(NO_GATING), 1, 'x', 1).durability).toBe(1)
  })
})

describe('consolidate 的 selective / keepFraction', () => {
  const N = 20

  async function consolidated(opts: { selective?: boolean, keepFraction?: number }, gating = DEFAULT_GATING) {
    const m = mkMem(gating, { consolidateThreshold: 1 })
    // 显著性递减：e0 最高、e{N-1} 最低
    for (let i = 0; i < N; i++) enc(m, i, `memory number ${i}`, (N - i) / N)
    await m.consolidate(undefined, opts)
    return m
  }

  it('selective=false 时零剪枝（即便门控系数非零）', async () => {
    const m = await consolidated({ selective: false })
    expect(m.episodes.filter(e => e.forgotten)).toHaveLength(0)
    expect(m.facts).toHaveLength(N)
  })

  it('selective=true 可强制剪枝（即便门控系数为 0）—— 分位臂依赖此行为', async () => {
    const m = await consolidated({ selective: true, keepFraction: 0.5 }, NO_GATING)
    expect(m.episodes.filter(e => e.forgotten)).toHaveLength(N / 2)
  })

  it('keepFraction 恰好保留 round(N*q) 条，且保留的是显著性最高的那批', async () => {
    const m = await consolidated({ keepFraction: 0.25 })
    const kept = m.episodes.filter(e => !e.forgotten).map(e => e.id)
    expect(kept).toHaveLength(5)
    // 显著性递减 ⇒ 最高的是 e0..e4
    expect(kept.sort()).toEqual(['e0', 'e1', 'e2', 'e3', 'e4'])
    // 每条被保留的 episode 恰好产出 1 条事实
    expect(m.facts).toHaveLength(5)
  })

  it('keepFraction=1 等价于不剪枝', async () => {
    const m = await consolidated({ keepFraction: 1 })
    expect(m.episodes.filter(e => e.forgotten)).toHaveLength(0)
    expect(m.facts).toHaveLength(N)
  })

  it('绝对阈值路径在显著性恒高时一条不剪 —— 这正是"剪枝通道静默禁用"的机制', async () => {
    const m = mkMem(DEFAULT_GATING, { consolidateThreshold: 1 })
    // salience 恒为 1，全部 > SALIENCE_THRESHOLD(0.5)
    for (let i = 0; i < N; i++) enc(m, i, `memory number ${i}`, 1)
    await m.consolidate(undefined, {})
    expect(m.episodes.filter(e => e.forgotten)).toHaveLength(0)
  })

  it('绝对阈值路径在显著性全低时全部剪掉', async () => {
    const m = mkMem(DEFAULT_GATING, { consolidateThreshold: 1 })
    for (let i = 0; i < N; i++) enc(m, i, `memory number ${i}`, 0)
    await m.consolidate(undefined, {})
    expect(m.episodes.filter(e => e.forgotten)).toHaveLength(N)
    expect(m.facts).toHaveLength(0)
  })
})

describe('buildMemory 的 BuildMemoryOptions', () => {
  it('salienceOf 返回 undefined 时走预测器（等价于不传）', async () => {
    const path = new URL('../eval/data/locomo10.json', import.meta.url).pathname
    let convs: ReturnType<typeof loadLocomo>
    try {
      convs = loadLocomo(path)
    }
    catch {
      return // 语料未下载（gitignored）时跳过：不引入对第三方数据的硬依赖
    }
    const conv = convs[0]
    const a = await buildMemory(conv, NO_GATING, undefined, { salienceOf: () => undefined })
    const b = await buildMemory(conv, NO_GATING)
    expect(a.episodes.map(e => e.encoding.salience)).toEqual(b.episodes.map(e => e.encoding.salience))
  })

  it('keepFraction 与 selectiveConsolidation 透传到 consolidate', async () => {
    const path = new URL('../eval/data/locomo10.json', import.meta.url).pathname
    let convs: ReturnType<typeof loadLocomo>
    try {
      convs = loadLocomo(path)
    }
    catch {
      return
    }
    const conv = convs[0]
    const off = await buildMemory(conv, NO_GATING, undefined, { selectiveConsolidation: false })
    expect(off.episodes.filter(e => e.forgotten)).toHaveLength(0)

    const q = await buildMemory(conv, DEFAULT_GATING, undefined, { keepFraction: 0.2 })
    const kept = q.episodes.filter(e => !e.forgotten).length
    expect(kept).toBeGreaterThan(0)
    expect(kept).toBeLessThan(conv.episodes.length)
  })
})
