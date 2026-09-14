/**
 * 跨游戏知识迁移引擎。
 *
 * 把"真人/视频在某游戏学到的经验"迁移到"当前正在上手的新游戏"上：
 *
 *   1. 机制相似度：用 game-mechanics 的余弦距离衡量两游戏有多像；
 *   2. 技能适配度：经验所属 skillCategory 是否对得上当前游戏的机制；
 *   3. 通用性加成：universal 经验（如"残血先保命"）对所有游戏都该优先考虑；
 *   4. 适配改写：把来源游戏的专有名词替换成当前游戏，并附"请按需调整"的提示。
 *
 * 这样 AIJADE 上手一个从没玩过的新游戏时，不会两眼一抹黑——
 * 它会先"回忆"起在其它同类游戏里学到的同类技能，快速建立先验，再边玩边修正。
 *
 * 注意：迁移只搬运"战术/操作知识"，绝不搬运任何绕过公平性的东西；
 * 所有动作仍需经安全层清洗，且 AIJADE 只通过模拟键鼠操作，不读内存、不挂钩子。
 */
import type { GameProfile } from '../types'
import type { KnowledgeItem } from './types'

import { buildTransferVector, cosineSimilarity, inferMechanics } from './game-mechanics'
import { classifySkill, skillFitsMechanics } from './skill-taxonomy'

export interface TransferredItem {
  item: KnowledgeItem
  /** 来源游戏档案 id */
  sourceProfileId: string
  /** 来源游戏名称（用于旁白/提示"我是从哪学来的"） */
  sourceProfileName: string
  /** 两游戏机制余弦相似度 0~1 */
  similarity: number
  /** 技能类别是否适配当前游戏机制（1/0） */
  skillFit: number
  /** 综合迁移得分（用于排序取 top-K） */
  transferScore: number
  /** 该经验是否为游戏无关通用经验 */
  universal: boolean
  /** 适配改写后的"适用条件" */
  adaptedCondition: string
  /** 适配改写后的"应对动作" */
  adaptedAction: string
  /** 给决策器的提示语（说明来源 + 需按需调整） */
  note: string
}

/** 跨游戏名词替换表（可扩展；用于把来源游戏专有词替换成当前游戏） */
const CROSS_GAME_GLOSSARY: Record<string, string[]> = {
  // 来源词 -> 可能被替换的目标同义词集合（仅做保守替换，避免误伤语义）
  闪避: ['翻滚', '冲刺', '位移'],
  普攻: ['基础攻击', '轻攻击'],
  技能: ['招式', '绝技'],
  敌人: ['怪物', '对手', '敌方单位'],
  掉落物: ['战利品', '物资'],
}

function adaptText(text: string, sourceName: string, targetName: string): string {
  let out = text
  // 保守地把来源游戏名替换成当前游戏名（让提示更贴合上下文）
  if (sourceName && targetName && sourceName !== targetName)
    out = out.replace(new RegExp(sourceName, 'g'), targetName)
  // 仅在文本里明确出现来源游戏名时才做名词替换，避免无谓改写
  if (out.includes(sourceName) || out === text) {
    for (const [from, tos] of Object.entries(CROSS_GAME_GLOSSARY)) {
      if (out.includes(from)) {
        // 只替换第一个命中，且用最通用的同义词
        out = out.replace(from, tos[0])
        break
      }
    }
  }
  return out
}

/**
 * 从候选经验（来自其它游戏）中挑选最适合当前游戏的前 N 条，并做适配改写。
 * @param target       当前正在上手的目标游戏档案
 * @param candidates   全部经验（跨所有游戏）
 * @param profiles     全部游戏档案（用于查候选经验来源游戏的机制）
 * @param topK        最多返回多少条
 */
export function transferKnowledge(
  target: GameProfile,
  candidates: KnowledgeItem[],
  profiles: GameProfile[],
  topK = 5,
): TransferredItem[] {
  const targetMech = inferMechanics(target)
  const targetVec = buildTransferVector(targetMech.mechanics)
  const profileById = new Map(profiles.map(p => [p.id, p]))

  const out: TransferredItem[] = []
  for (const item of candidates) {
    if (item.profileId === target.id)
      continue // 自己游戏的经验不算"迁移"
    const srcProfile = profileById.get(item.profileId)
    if (!srcProfile)
      continue

    const sim = cosineSimilarity(targetVec, buildTransferVector(inferMechanics(srcProfile).mechanics))
    const category = item.skillCategory ?? classifySkill(item)
    const fit = skillFitsMechanics(category, targetMech.mechanics) ? 1 : 0
    const universal = Boolean(item.universal) || category === 'meta'
    // 综合分：机制相似度为主，技能适配次之，通用性加成
    const score = sim * 1.4 + fit * 0.8 + (universal ? 0.6 : 0) + item.confidence * 0.3

    out.push({
      item,
      sourceProfileId: srcProfile.id,
      sourceProfileName: srcProfile.name,
      similarity: sim,
      skillFit: fit,
      transferScore: score,
      universal,
      adaptedCondition: adaptText(item.condition, srcProfile.name, target.name),
      adaptedAction: adaptText(item.action, srcProfile.name, target.name),
      note: `（来自《${srcProfile.name}》的「${category}」类经验，机制相似度 ${(sim * 100).toFixed(0)}%，请按本游戏实际情况调整）`,
    })
  }

  return out
    .sort((a, b) => b.transferScore - a.transferScore)
    .slice(0, topK)
}

/** 把迁移经验渲染成注入决策器的提示词片段 */
export function transferPromptBlock(transfers: TransferredItem[], topK = 5): string {
  const picked = transfers.slice(0, topK)
  if (!picked.length)
    return ''
  const lines = picked.map((t, i) => {
    const seq = t.item.sequence?.length
      ? `｜若本游戏按键一致可直接套用：${t.item.sequence.map(a => a.key ?? a.button ?? a.type).join('→')}`
      : ''
    return `${i + 1}. [${t.sourceProfileName}→${'本游戏'}] ${t.item.title}\n   条件：${t.adaptedCondition}\n   做法：${t.adaptedAction}${seq}\n   ${t.note}`
  })
  return [
    '以下是你在其它游戏里学到的、可迁移到当前游戏的同类经验（优先参考，但务必按本游戏机制核对后再用）：',
    ...lines,
  ].join('\n')
}
