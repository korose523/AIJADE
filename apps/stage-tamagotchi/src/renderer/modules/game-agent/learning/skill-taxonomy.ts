/**
 * 技能分类法（Skill Taxonomy）——把知识条目归到与游戏无关的横向能力上。
 *
 * 人类学游戏时，长期记忆里沉淀的不是"在某游戏按某键"，而是"遇到 X 情况就做 Y 类应对"。
 * 给每条经验打上 skillCategory，跨游戏迁移时就能按"同类技能"精准匹配：
 * 比如 A 游戏学到的"残血就找掩体"属于 survival，B 游戏里同样归 survival 的经验
 * 就能直接拿来用，哪怕两个游戏按键、画面完全不同。
 */
import type { GameMechanic, SkillCategory } from '../types'

export const SKILL_CATEGORY_LABELS: Record<SkillCategory, string> = {
  'navigation': '找路/导航',
  'combat': '战斗',
  'resource': '资源获取',
  'survival': '生存保命',
  'ui-interaction': '界面/菜单交互',
  'objective': '目标推进',
  'economy': '交易/经济',
  'meta': '通用元策略',
}

/** 每类技能对应的机制关键词（用于把"迁移匹配"和"机制相似度"联动起来） */
export const SKILL_RELATED_MECHANICS: Record<SkillCategory, GameMechanic[]> = {
  'navigation': ['movement-wasd', 'movement-stick', 'movement-click', 'minimap-navigation'],
  'combat': ['aiming', 'shooting', 'melee', 'skills-cooldown', 'skills-hotbar', 'boss-pattern'],
  'resource': ['loot-pickup', 'resource-harvest', 'inventory-management'],
  'survival': ['dodge-roll', 'health-regen', 'cover-system', 'stealth'],
  'ui-interaction': ['dialogue-choice', 'crafting', 'building'],
  'objective': ['quest-objective', 'team-comms'],
  'economy': ['economy-trade', 'resource-management'],
  'meta': [],
}

interface KeywordRule {
  category: SkillCategory
  zh: string[]
  en: string[]
}

const RULES: KeywordRule[] = [
  { category: 'navigation', zh: ['去', '路', '导航', '小地图', '前往', '转移', '跑图', '走位'], en: ['go to', 'navigate', 'path', 'route', 'map', 'move toward', 'reposition'] },
  { category: 'combat', zh: ['攻击', '射击', '开火', '打', '敌人', 'boss', '技能', '连招', '瞄准', '输出'], en: ['attack', 'shoot', 'fire', 'enemy', 'boss', 'combo', 'aim', 'damage', 'fight'] },
  { category: 'resource', zh: ['拾取', '掉落', '采集', '背包', '物资', '资源', '金币', '装备'], en: ['loot', 'pickup', 'harvest', 'inventory', 'item', 'resource', 'gear'] },
  { category: 'survival', zh: ['血量', '回血', '闪避', '翻滚', '掩体', '保命', '撤退', '治疗', '毒圈', '潜行'], en: ['hp', 'health', 'heal', 'dodge', 'roll', 'cover', 'survive', 'retreat', 'stealth'] },
  { category: 'ui-interaction', zh: ['菜单', '界面', '对话', '选项', '合成', '打造', '建造', '商店'], en: ['menu', 'ui', 'dialogue', 'option', 'craft', 'build', 'shop'] },
  { category: 'objective', zh: ['任务', '目标', '完成', '据点', '占领', '推进'], en: ['quest', 'objective', 'complete', 'capture', 'progress', 'goal'] },
  { category: 'economy', zh: ['交易', '买卖', '经济', '市场', '价格'], en: ['trade', 'buy', 'sell', 'market', 'price', 'economy'] },
  { category: 'meta', zh: ['节奏', '习惯', '通用', '心态', '优先', '原则'], en: ['tempo', 'habit', 'generic', 'mindset', 'priority', 'principle', 'general'] },
]

/**
 * 根据经验标题/条件/动作/标签，推断其横向技能类别。
 * 命中多个时取权重最高（关键词最多）的那类；都未命中回退 meta。
 */
export function classifySkill(input: {
  title?: string
  condition?: string
  action?: string
  tags?: string[]
}): SkillCategory {
  const text = [
    input.title ?? '',
    input.condition ?? '',
    input.action ?? '',
    (input.tags ?? []).join(' '),
  ].join('\n').toLowerCase()

  let best: SkillCategory = 'meta'
  let bestScore = 0
  for (const rule of RULES) {
    let score = 0
    for (const kw of rule.zh) {
      if (text.includes(kw))
        score += 2
    }
    for (const kw of rule.en) {
      if (text.includes(kw))
        score += 1
    }
    if (score > bestScore) {
      bestScore = score
      best = rule.category
    }
  }
  return best
}

/** 该技能类别是否与目标游戏的机制相关（用于迁移时加权） */
export function skillFitsMechanics(category: SkillCategory, mechanics: GameMechanic[]): boolean {
  const related = SKILL_RELATED_MECHANICS[category]
  if (!related.length)
    return true // meta 类对所有游戏都有价值
  const set = new Set(mechanics)
  return related.some(m => set.has(m))
}
