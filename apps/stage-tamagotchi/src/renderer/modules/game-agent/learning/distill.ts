/**
 * 经验提炼器 —— 把原始学习素材榨成可复用的知识。
 *
 * 原始素材（几万条键鼠事件 / 几十张截图）没法直接喂给决策模型，必须先压缩成
 * 少量、结构化、可检索的经验条目（KnowledgeItem）。
 *
 * 两条提炼路线，可叠加：
 *  1. 启发式（永远可用，不需要模型）：
 *     - 把时间上密集相邻的按键切成"连招片段"，统计高频组合 → combo 知识（可直接回放）
 *     - 统计按键使用频率 → hotkey 知识（这游戏主要在按什么）
 *  2. 语言模型（可选，更聪明）：
 *     - 把「画面描述 + 对应时刻人类的操作」配对样本交给 LLM，让它总结成条件-动作规则
 *     - 视频学习还会带上解说文本，规则质量明显更高
 */
import type { AgentAction, GameProfile } from '../types'
import type { InputEvent, KnowledgeItem, LearningEpisode } from './types'

import { inferMechanics } from './game-mechanics'
import { classifySkill } from './skill-taxonomy'

export interface DistillOptions {
  baseUrl?: string
  model?: string
  /** 是否调用语言模型做深度提炼 */
  useLLM: boolean
  /** 最多产出多少条 */
  maxItems?: number
  temperature?: number
}

function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/**
 * 给提炼出的经验打上"可迁移元数据"：横向技能类别、是否通用经验、涉及机制标签。
 * 这一步是跨游戏迁移的前提——没有这些标签，A 游戏的经验就无法被 B 游戏检索到。
 */
function attachSkillMeta(item: KnowledgeItem, profile: GameProfile): KnowledgeItem {
  const skillCategory = classifySkill({
    title: item.title,
    condition: item.condition,
    action: item.action,
    tags: item.tags,
  })
  const universal = skillCategory === 'meta' || item.tags.includes('通用') || item.tags.includes('universal')
  const gameTags = (profile.mechanics?.mechanics ?? inferMechanics(profile).mechanics) as string[]
  return { ...item, skillCategory, universal, gameTags }
}

// ———————————————————————————————————————————————
// 启发式：从操作流里挖连招
// ———————————————————————————————————————————————

interface ComboGroup {
  signature: string
  actions: AgentAction[]
  count: number
}

/**
 * 把按下事件按时间间隔切段：间隔小于 gapMs 的算同一次"操作意图"。
 * 例如 ARPG 里常见的 "位移→技能→普攻" 会稳定地聚成一段。
 */
export function extractCombos(events: InputEvent[], gapMs = 400, minLen = 2, maxLen = 6): ComboGroup[] {
  const downs = events
    .filter(e => (e.kind === 'key' || e.kind === 'mouse') && e.down)
    .sort((a, b) => a.t - b.t)

  const groups: InputEvent[][] = []
  let current: InputEvent[] = []
  let prevT = -1e9
  for (const ev of downs) {
    if (ev.t - prevT > gapMs && current.length) {
      groups.push(current)
      current = []
    }
    current.push(ev)
    prevT = ev.t
  }
  if (current.length)
    groups.push(current)

  const counter = new Map<string, ComboGroup>()
  for (const g of groups) {
    if (g.length < minLen)
      continue
    const seg = g.slice(0, maxLen)
    const signature = seg.map(e => (e.kind === 'mouse' ? `mouse:${e.button}` : e.key)).join(' → ')
    const existing = counter.get(signature)
    if (existing) {
      existing.count++
      continue
    }
    const actions: AgentAction[] = []
    for (let i = 0; i < seg.length; i++) {
      const e = seg[i]
      if (e.kind === 'mouse')
        actions.push({ type: 'click', button: e.button ?? 'left', reason: '来自真人示范' })
      else if (e.key)
        actions.push({ type: 'key', key: e.key, reason: '来自真人示范' })
      const next = seg[i + 1]
      if (next) {
        const gap = Math.max(30, Math.min(600, next.t - e.t))
        actions.push({ type: 'wait', durationMs: gap })
      }
    }
    counter.set(signature, { signature, actions, count: 1 })
  }

  return Array.from(counter.values()).sort((a, b) => b.count - a.count)
}

function heuristicFromRealMachine(ep: LearningEpisode, profile: GameProfile, maxItems: number): KnowledgeItem[] {
  const out: KnowledgeItem[] = []
  const combos = extractCombos(ep.events)
  const totalCombos = combos.reduce((s, c) => s + c.count, 0) || 1

  for (const c of combos.slice(0, Math.max(1, Math.floor(maxItems / 2)))) {
    // 只出现一两次的多半是随手操作，不值得当经验
    if (c.count < 2)
      continue
    const share = c.count / totalCombos
    out.push({
      id: newId('kn'),
      profileId: profile.id,
      source: 'real-machine',
      kind: 'combo',
      title: `高频连招：${c.signature}`,
      condition: '战斗中需要输出或位移时（真人在本局中反复使用）',
      action: `依次执行 ${c.signature}`,
      sequence: c.actions.filter(a => profile.allowedActions.includes(a.type)),
      confidence: Math.min(0.92, 0.4 + share * 2),
      tags: ['连招', '真机示范'],
      createdAt: Date.now(),
      usedCount: 0,
      episodeId: ep.id,
    })
  }

  // 按键频率 → 操作习惯
  const keyCount = new Map<string, number>()
  for (const e of ep.events) {
    if (e.kind === 'key' && e.down && e.key)
      keyCount.set(e.key, (keyCount.get(e.key) ?? 0) + 1)
  }
  const topKeys = Array.from(keyCount.entries()).sort((a, b) => b[1] - a[1]).slice(0, 8)
  if (topKeys.length) {
    const minutes = Math.max(ep.durationMs / 60000, 1 / 60)
    out.push({
      id: newId('kn'),
      profileId: profile.id,
      source: 'real-machine',
      kind: 'hotkey',
      title: '真人常用按键分布',
      condition: '任何时候（作为操作习惯的先验）',
      action: `${topKeys.map(([k, n]) => `${k}×${n}`).join('、')
      }；整体 APM 约 ${Math.round(Array.from(keyCount.values()).reduce((a, b) => a + b, 0) / minutes)}`,
      confidence: 0.7,
      tags: ['按键习惯', '真机示范'],
      createdAt: Date.now(),
      usedCount: 0,
      episodeId: ep.id,
    })
  }

  return out.map(it => attachSkillMeta(it, profile))
}

function heuristicFromVideo(ep: LearningEpisode, profile: GameProfile): KnowledgeItem[] {
  const captions = ep.keyframes.map(k => k.caption).filter(Boolean) as string[]
  if (!captions.length)
    return []
  return [{
    id: newId('kn'),
    profileId: profile.id,
    source: 'video',
    kind: 'tip',
    title: `视频观察摘要（${ep.title}）`,
    condition: '作为该游戏的背景知识',
    action: captions.slice(0, 12).join('；').slice(0, 800),
    confidence: 0.45,
    tags: ['视频学习', '未提炼'],
    createdAt: Date.now(),
    usedCount: 0,
    episodeId: ep.id,
  }]
}

// ———————————————————————————————————————————————
// 语言模型深度提炼
// ———————————————————————————————————————————————

async function askOllamaJson(baseUrl: string, model: string, system: string, user: string, temperature: number): Promise<any> {
  const resp = await fetch(`${baseUrl.replace(/\/$/, '')}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      prompt: `${system}\n\n${user}`,
      format: 'json',
      stream: false,
      options: { temperature },
    }),
  })
  if (!resp.ok)
    throw new Error(`Ollama 返回 ${resp.status}`)
  const data = await resp.json()
  const text = typeof data.response === 'string' ? data.response : JSON.stringify(data)
  try {
    return JSON.parse(text)
  }
  catch {
    return null
  }
}

/** 把素材压缩成给 LLM 的文本样本，避免把几万条事件全塞进去。 */
function buildSamples(ep: LearningEpisode, limit = 24): string {
  const lines: string[] = []
  const frames = ep.keyframes.slice(0, limit)
  for (const f of frames) {
    const sec = (f.t / 1000).toFixed(1)
    const desc = f.caption
      ?? (f.structured ? JSON.stringify(f.structured) : '(画面未描述)')
    const acts = f.nearbyActions?.length ? `｜人类操作：${f.nearbyActions.join(' ')}` : ''
    lines.push(`[${sec}s] ${String(desc).slice(0, 300)}${acts}`)
  }
  return lines.join('\n')
}

async function llmDistill(ep: LearningEpisode, profile: GameProfile, opts: DistillOptions): Promise<KnowledgeItem[]> {
  const baseUrl = opts.baseUrl ?? 'http://localhost:11434'
  const model = opts.model ?? 'qwen3.6-35b-a3b'
  const maxItems = opts.maxItems ?? 8

  const isReal = ep.source === 'real-machine'
  const combos = isReal ? extractCombos(ep.events).slice(0, 8) : []
  const comboLine = combos.length
    ? `\n真人高频操作组合（按出现次数排序）：\n${combos.map(c => `- ${c.signature}（${c.count} 次）`).join('\n')}`
    : ''
  const noteLine = ep.notes ? `\n补充材料（备注 / 解说 / 字幕）：\n${ep.notes.slice(0, 3000)}` : ''

  const system = [
    `你是《${profile.name}》的游戏教练，正在把一段学习素材总结成可执行的经验条目。`,
    isReal
      ? '素材来自「观察真人玩游戏」：包含画面描述与该时刻真人的按键操作。请重点还原"看到什么情况 → 人类怎么应对"。'
      : '素材来自「观看游戏视频」：只有画面描述（可能附带解说文字）。请重点提炼战术要点与常见误区。',
    '输出必须是 JSON，不要任何解释文字。',
  ].join('\n')

  const user = [
    `游戏：${profile.name}（${profile.description}）`,
    `素材标题：${ep.title}，时长 ${(ep.durationMs / 1000).toFixed(0)} 秒，关键帧 ${ep.keyframes.length} 个`,
    comboLine,
    noteLine,
    '\n时间轴样本：',
    buildSamples(ep),
    '',
    `请提炼最多 ${maxItems} 条经验，输出格式：`,
    '{"items":[{"kind":"rule|combo|tip|hotkey|mistake","title":"简短标题","condition":"什么情况下适用","action":"应该怎么做","confidence":0.0~1.0,"tags":["标签"]}]}',
    '要求：condition 必须是能从游戏画面判断出来的客观条件；action 必须具体到按键或鼠标操作；不要输出泛泛而谈的废话。',
  ].join('\n')

  const parsed = await askOllamaJson(baseUrl, model, system, user, opts.temperature ?? 0.3)
  const rawItems = Array.isArray(parsed) ? parsed : parsed?.items
  if (!Array.isArray(rawItems))
    return []

  return rawItems.slice(0, maxItems).map((it: any) => ({
    id: newId('kn'),
    profileId: profile.id,
    source: ep.source,
    kind: ['rule', 'combo', 'tip', 'hotkey', 'mistake'].includes(it?.kind) ? it.kind : 'tip',
    title: String(it?.title ?? '未命名经验').slice(0, 120),
    condition: String(it?.condition ?? '').slice(0, 500),
    action: String(it?.action ?? '').slice(0, 800),
    confidence: typeof it?.confidence === 'number' ? Math.max(0, Math.min(1, it.confidence)) : 0.6,
    tags: Array.isArray(it?.tags) ? it.tags.map((t: unknown) => String(t).slice(0, 20)).slice(0, 6) : [],
    createdAt: Date.now(),
    usedCount: 0,
    episodeId: ep.id,
  })) as KnowledgeItem[]
}

/**
 * 提炼入口。启发式结果始终产出（保证离线可用），LLM 结果作为增量叠加。
 */
export async function distillEpisode(
  ep: LearningEpisode,
  profile: GameProfile,
  opts: DistillOptions,
): Promise<{ items: KnowledgeItem[], llmError?: string }> {
  const maxItems = opts.maxItems ?? 8
  const heuristic = ep.source === 'real-machine'
    ? heuristicFromRealMachine(ep, profile, maxItems)
    : heuristicFromVideo(ep, profile)

  if (!opts.useLLM)
    return { items: heuristic }

  try {
    const llm = await llmDistill(ep, profile, opts)
    // LLM 版摘要比启发式摘要好，视频素材就不保留占位摘要了
    const merged = ep.source === 'video' && llm.length
      ? llm
      : heuristic.concat(llm)
    return { items: merged }
  }
  catch (err) {
    return {
      items: heuristic,
      llmError: err instanceof Error ? err.message : String(err),
    }
  }
}
