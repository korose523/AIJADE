import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const INSTALL_ID_KEY = 'aijade:web-extension:install-id'

function installBrowserMock(store: Record<string, unknown>) {
  const get = vi.fn(async (key: string) => ({ [key]: store[key] }))
  const set = vi.fn(async (obj: Record<string, unknown>) => {
    Object.assign(store, obj)
  })
  ;(globalThis as any).browser = { storage: { local: { get, set } } }
  return { get, set }
}

/** 重新求值 storage 模块，使模块级 `installIdPromise` 缓存回到 null（模拟 SW 重启）。 */
async function freshStorageModule() {
  vi.resetModules()
  return await import('./storage')
}

describe('getOrCreateInstallId', () => {
  let originalBrowser: unknown

  beforeEach(() => {
    originalBrowser = (globalThis as any).browser
  })

  afterEach(() => {
    ;(globalThis as any).browser = originalBrowser
    vi.resetModules()
    vi.restoreAllMocks()
  })

  it('mints once and returns the same persisted id on subsequent calls (not re-minted each call)', async () => {
    const store: Record<string, unknown> = {}
    const { set } = installBrowserMock(store)
    const { getOrCreateInstallId } = await freshStorageModule()

    const first = await getOrCreateInstallId()
    const second = await getOrCreateInstallId()

    expect(first).toBe(second)
    expect(typeof first).toBe('string')
    expect(first.length).toBeGreaterThan(0)
    // 已落盘：store 里确实写进了这个 id（SW 重启后能读回 → 跨重启稳定）。
    expect(store[INSTALL_ID_KEY]).toBe(first)
    // 关键断言：第二次调用没有任何写入 → 证明不是"每次新铸"，而是读回已落盘的同一 id。
    expect(set).toHaveBeenCalledTimes(1)
  })

  it('reads an already-persisted id without minting (survives SW restart)', async () => {
    const store: Record<string, unknown> = { [INSTALL_ID_KEY]: 'seeded-install-id' }
    const { get, set } = installBrowserMock(store)
    const { getOrCreateInstallId } = await freshStorageModule()

    const id = await getOrCreateInstallId()

    // 直接返回落盘值，与"重启后重新铸造"形成对照。
    expect(id).toBe('seeded-install-id')
    expect(get).toHaveBeenCalled()
    // 已有值时不写入（不重铸）。
    expect(set).not.toHaveBeenCalled()
  })

  it('returns a UUID-shaped id and never a Date.now()-style numeric id', async () => {
    const store: Record<string, unknown> = {}
    installBrowserMock(store)
    const { getOrCreateInstallId } = await freshStorageModule()

    const id = await getOrCreateInstallId()
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i)
    expect(id).not.toMatch(/^\d+$/)
  })
})
