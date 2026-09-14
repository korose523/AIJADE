import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * 游戏经验持久化（主进程）。
 *
 * AIJADE 学到的东西必须活过重启，否则每次开机都要从零开始看人类玩。存两类数据：
 *
 *  - knowledge.json：提炼后的经验条目（KnowledgeItem），体积小、频繁读写，整文件存。
 *  - episodes/<id>.json：原始学习素材（一次真机录制或一个视频的抽帧结果），
 *    体积大、按需读取，一素材一文件；列表接口只返回摘要，不加载正文。
 *
 * 存放位置：userData/game-agent/ 下，跟随 Electron 用户数据目录。
 */
import { app, ipcMain, shell } from 'electron'

interface StoredKnowledgeItem {
  id: string
  profileId: string
  [key: string]: unknown
}

interface StoredEpisode {
  id: string
  profileId: string
  title?: string
  source?: string
  startedAt?: number
  endedAt?: number
  durationMs?: number
  events?: unknown[]
  keyframes?: unknown[]
  [key: string]: unknown
}

function baseDir(): string {
  const dir = join(app.getPath('userData'), 'game-agent')
  mkdirSync(dir, { recursive: true })
  return dir
}

function episodesDir(): string {
  const dir = join(baseDir(), 'episodes')
  mkdirSync(dir, { recursive: true })
  return dir
}

function knowledgePath(): string {
  return join(baseDir(), 'knowledge.json')
}

function readKnowledge(): StoredKnowledgeItem[] {
  const path = knowledgePath()
  if (!existsSync(path))
    return []
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'))
    return Array.isArray(parsed) ? parsed as StoredKnowledgeItem[] : []
  }
  catch {
    return []
  }
}

function writeKnowledge(items: StoredKnowledgeItem[]): void {
  writeFileSync(knowledgePath(), JSON.stringify(items, null, 2), 'utf8')
}

/** 关键帧缩略图很占空间，落盘时限制数量，避免单个素材文件膨胀到几百 MB。 */
function shrinkEpisode(ep: StoredEpisode, maxThumbnails: number): StoredEpisode {
  if (!Array.isArray(ep.keyframes))
    return ep
  const frames = ep.keyframes as Record<string, unknown>[]
  if (frames.length <= maxThumbnails)
    return ep
  const step = frames.length / maxThumbnails
  const keep = new Set<number>()
  for (let i = 0; i < maxThumbnails; i++)
    keep.add(Math.floor(i * step))
  const trimmed = frames.map((f, i) => (keep.has(i) ? f : { ...f, thumbnail: undefined }))
  return { ...ep, keyframes: trimmed }
}

export function registerKnowledgeStore(): void {
  // —— 经验条目 ——
  ipcMain.handle('game-agent:knowledge:list', (_e, profileId?: string) => {
    const all = readKnowledge()
    return profileId ? all.filter(k => k.profileId === profileId) : all
  })

  /** 追加或按 id 覆盖写入若干条目。 */
  ipcMain.handle('game-agent:knowledge:upsert', (_e, items: StoredKnowledgeItem[]) => {
    if (!Array.isArray(items))
      return readKnowledge()
    const all = readKnowledge()
    const byId = new Map(all.map(k => [k.id, k]))
    for (const item of items) {
      if (item && typeof item.id === 'string')
        byId.set(item.id, { ...byId.get(item.id), ...item })
    }
    const merged = Array.from(byId.values())
    writeKnowledge(merged)
    return merged
  })

  ipcMain.handle('game-agent:knowledge:delete', (_e, id: string) => {
    const all = readKnowledge().filter(k => k.id !== id)
    writeKnowledge(all)
    return all
  })

  ipcMain.handle('game-agent:knowledge:clear', (_e, profileId?: string) => {
    const remaining = profileId ? readKnowledge().filter(k => k.profileId !== profileId) : []
    writeKnowledge(remaining)
    return remaining
  })

  // —— 学习素材 ——
  ipcMain.handle('game-agent:episode:save', (_e, episode: StoredEpisode, maxThumbnails = 40) => {
    if (!episode || typeof episode.id !== 'string')
      throw new Error('episode.id 缺失')
    const payload = shrinkEpisode(episode, maxThumbnails)
    writeFileSync(join(episodesDir(), `${episode.id}.json`), JSON.stringify(payload), 'utf8')
    return { id: episode.id, ok: true }
  })

  /** 只返回摘要，不含事件/帧正文。 */
  ipcMain.handle('game-agent:episode:list', (_e, profileId?: string) => {
    const dir = episodesDir()
    const files = readdirSync(dir).filter(f => f.endsWith('.json'))
    const out: Record<string, unknown>[] = []
    for (const f of files) {
      try {
        const ep = JSON.parse(readFileSync(join(dir, f), 'utf8')) as StoredEpisode
        if (profileId && ep.profileId !== profileId)
          continue
        out.push({
          id: ep.id,
          profileId: ep.profileId,
          title: ep.title,
          source: ep.source,
          origin: ep.origin,
          notes: ep.notes,
          startedAt: ep.startedAt,
          endedAt: ep.endedAt,
          durationMs: ep.durationMs,
          eventCount: Array.isArray(ep.events) ? ep.events.length : 0,
          frameCount: Array.isArray(ep.keyframes) ? ep.keyframes.length : 0,
          distilledCount: ep.distilledCount ?? 0,
        })
      }
      catch {
        // 跳过损坏文件
      }
    }
    return out.sort((a, b) => Number(b.startedAt ?? 0) - Number(a.startedAt ?? 0))
  })

  ipcMain.handle('game-agent:episode:get', (_e, id: string) => {
    const path = join(episodesDir(), `${id}.json`)
    if (!existsSync(path))
      return null
    try {
      return JSON.parse(readFileSync(path, 'utf8'))
    }
    catch {
      return null
    }
  })

  ipcMain.handle('game-agent:episode:delete', (_e, id: string) => {
    const path = join(episodesDir(), `${id}.json`)
    if (existsSync(path))
      rmSync(path)
    return { ok: true }
  })

  /** 在文件管理器里打开数据目录，方便用户备份/检查。 */
  ipcMain.handle('game-agent:store:reveal', () => {
    const dir = baseDir()
    void shell.openPath(dir)
    return dir
  })
}
