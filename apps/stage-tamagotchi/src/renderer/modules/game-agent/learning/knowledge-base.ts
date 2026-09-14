import type { GameProfile } from '../types'
import type { TransferredItem } from './transfer'
import type { KnowledgeItem, KnowledgeKind, LearningEpisode } from './types'

/**
 * 经验库 —— 学习成果的存取与检索，也是「学习」与「实操」之间的桥。
 *
 * 实操时不能把所有经验一股脑塞进提示词（上下文会爆，且噪声拉低决策质量），
 * 所以这里做了一个轻量检索：用当前游戏状态文本 + 目标做关键词重合度打分，
 * 叠加置信度与使用历史，取 top-K 渲染成提示词片段注入决策器。
 *
 * 不引入向量库/嵌入模型——游戏状态文本很短、经验条目也就几十条，
 * 关键词打分足够用，且完全离线、零延迟。
 */
import { computed, ref, shallowRef } from 'vue'

import { transferKnowledge } from './transfer'

/** 极简中英文分词：英文按单词，中文按二元组（能捕捉"血量""闪避"这类词） */
function tokenize(text: string): string[] {
  const lower = text.toLowerCase()
  const tokens: string[] = []
  const en = lower.match(/[a-z0-9]+/g)
  if (en)
    tokens.push(...en)
  const zh = lower.replace(/[^\u4E00-\u9FA5]/g, '')
  for (let i = 0; i < zh.length - 1; i++)
    tokens.push(zh.slice(i, i + 2))
  return tokens
}

function scoreItem(item: KnowledgeItem, queryTokens: Set<string>): number {
  if (!queryTokens.size)
    return item.confidence
  const text = `${item.title} ${item.condition} ${item.action} ${item.tags.join(' ')}`
  const itemTokens = tokenize(text)
  if (!itemTokens.length)
    return item.confidence * 0.5
  let hit = 0
  const seen = new Set<string>()
  for (const t of itemTokens) {
    if (queryTokens.has(t) && !seen.has(t)) {
      seen.add(t)
      hit++
    }
  }
  const overlap = hit / Math.sqrt(queryTokens.size)
  // 相关性为主，置信度次之，用过的略微加分（经过实战检验）
  return overlap * 1.6 + item.confidence * 0.8 + Math.min(item.usedCount, 5) * 0.03
}

export interface EpisodeSummary {
  id: string
  profileId: string
  title: string
  source: string
  origin?: string
  notes?: string
  startedAt: number
  durationMs: number
  eventCount: number
  frameCount: number
  distilledCount: number
}

function ipc() {
  return window.electron.ipcRenderer
}

export function useKnowledgeBase(profileId: string) {
  const items = shallowRef<KnowledgeItem[]>([])
  const episodes = shallowRef<EpisodeSummary[]>([])
  /** 跨游戏迁移用：全部游戏的经验（不限 profileId），由 listAll() 填充 */
  const allItems = shallowRef<KnowledgeItem[]>([])
  const loading = ref(false)
  const error = ref('')

  const count = computed(() => items.value.length)
  const byKind = computed(() => {
    const m: Record<string, number> = {}
    for (const it of items.value)
      m[it.kind] = (m[it.kind] ?? 0) + 1
    return m
  })

  async function load() {
    loading.value = true
    try {
      items.value = await ipc().invoke('game-agent:knowledge:list', profileId) as KnowledgeItem[]
      error.value = ''
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
    finally {
      loading.value = false
    }
  }

  /** 拉取所有游戏的经验（跨游戏迁移检索用）。不修改当前 per-profile 的 items。 */
  async function listAll(): Promise<KnowledgeItem[]> {
    const all = await ipc().invoke('game-agent:knowledge:list') as KnowledgeItem[]
    allItems.value = all
    return all
  }

  /**
   * 跨游戏迁移检索：从其它游戏的经验里挑当前游戏最该参考的前 N 条。
   * 返回结构含来源游戏、相似度与适配改写后的条件/动作。
   */
  function searchTransfer(targetProfile: GameProfile, profiles: GameProfile[], topK = 5): TransferredItem[] {
    if (!allItems.value.length)
      return []
    return transferKnowledge(targetProfile, allItems.value, profiles, topK)
  }

  /** 迁移经验被成功采纳后回调：小幅提升其置信度，形成"越用越准"的正反馈。 */
  async function markTransferConfirmed(itemId: string): Promise<void> {
    const hit = allItems.value.find(i => i.id === itemId)
    if (!hit)
      return
    hit.usedCount++
    hit.confidence = Math.min(1, hit.confidence + 0.02)
    await ipc().invoke('game-agent:knowledge:upsert', JSON.parse(JSON.stringify([hit])))
  }

  async function loadEpisodes() {
    try {
      episodes.value = await ipc().invoke('game-agent:episode:list', profileId) as EpisodeSummary[]
    }
    catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    }
  }

  async function add(newItems: KnowledgeItem[]) {
    if (!newItems.length)
      return
    const payload = JSON.parse(JSON.stringify(newItems))
    items.value = await ipc().invoke('game-agent:knowledge:upsert', payload) as KnowledgeItem[]
    items.value = items.value.filter(i => i.profileId === profileId)
  }

  async function remove(id: string) {
    await ipc().invoke('game-agent:knowledge:delete', id)
    await load()
  }

  async function clear() {
    await ipc().invoke('game-agent:knowledge:clear', profileId)
    items.value = []
  }

  async function getEpisode(id: string): Promise<LearningEpisode | null> {
    return await ipc().invoke('game-agent:episode:get', id) as LearningEpisode | null
  }

  async function deleteEpisode(id: string) {
    await ipc().invoke('game-agent:episode:delete', id)
    await loadEpisodes()
  }

  async function revealDataDir(): Promise<string> {
    return await ipc().invoke('game-agent:store:reveal') as string
  }

  /** 按当前状态检索最相关的经验。 */
  function search(stateText?: string, goal?: string, limit = 6, kinds?: KnowledgeKind[]): KnowledgeItem[] {
    const query = [stateText ?? '', goal ?? ''].join(' ')
    const queryTokens = new Set(tokenize(query))
    let pool = items.value
    if (kinds?.length)
      pool = pool.filter(i => kinds.includes(i.kind))
    return pool
      .map(i => ({ item: i, score: scoreItem(i, queryTokens) }))
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map(x => x.item)
  }

  /** 渲染成注入决策器的提示词片段。 */
  function toPromptBlock(stateText?: string, goal?: string, limit = 6): string {
    const picked = search(stateText, goal, limit)
    if (!picked.length)
      return ''
    const lines = picked.map((it, i) => {
      const seq = it.sequence?.length
        ? `｜可直接执行：${it.sequence.map(a => a.key ?? a.button ?? a.type).join('→')}`
        : ''
      return `${i + 1}. [${it.kind}] ${it.title}\n   条件：${it.condition}\n   做法：${it.action}${seq}`
    })
    // 记录使用次数（本地即时更新，落盘留给下次 add/upsert）
    for (const it of picked)
      it.usedCount++
    return [
      '以下是你此前通过观察真人游玩与观看视频学到的经验，优先参考：',
      ...lines,
    ].join('\n')
  }

  /** 把使用计数写回磁盘，避免每次决策都写盘。 */
  async function persistUsage() {
    const dirty = items.value.filter(i => i.usedCount > 0)
    if (!dirty.length)
      return
    await ipc().invoke('game-agent:knowledge:upsert', JSON.parse(JSON.stringify(dirty)))
  }

  return {
    items,
    episodes,
    allItems,
    loading,
    error,
    count,
    byKind,
    load,
    listAll,
    searchTransfer,
    markTransferConfirmed,
    loadEpisodes,
    add,
    remove,
    clear,
    getEpisode,
    deleteEpisode,
    revealDataDir,
    search,
    toPromptBlock,
    persistUsage,
  }
}
