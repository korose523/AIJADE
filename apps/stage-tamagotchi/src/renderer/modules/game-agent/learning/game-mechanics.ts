/**
 * 游戏机制画像与跨游戏相似度。
 *
 * 这是"像人类一样学习、并能把经验迁移到新游戏"的关键：
 * 人类之所以能快速上手新游戏，是因为他能把"WASD 移动""找掩体保命"
 * 这类**与具体游戏无关的底层技能**迁移过去，而不是死记某个游戏的像素坐标。
 *
 * 这里把每个游戏抽象成一个机制向量，再做余弦相似度——
 * 向量越像，A 游戏的技能就能越多地套到 B 游戏上。
 */
import type { GameMechanic, GameMechanics, GameProfile } from '../types'

import { GAME_MECHANICS } from '../types'

/** 把机制集合编码成固定长度、顺序稳定的 0/1 转移向量 */
export function buildTransferVector(mechanics: GameMechanic[]): number[] {
  const set = new Set(mechanics)
  return GAME_MECHANICS.map(m => (set.has(m) ? 1 : 0))
}

/** 余弦相似度，范围 [-1,1]，这里输入非负所以落在 [0,1] */
export function cosineSimilarity(a: number[], b: number[]): number {
  const len = Math.min(a.length, b.length)
  let dot = 0
  let na = 0
  let nb = 0
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i]
    na += a[i] * a[i]
    nb += b[i] * b[i]
  }
  if (na === 0 || nb === 0)
    return 0
  return dot / (Math.sqrt(na) * Math.sqrt(nb))
}

/** 若档案没显式给 mechanics，就从描述/允许动作里做一个兜底推断（够用即可） */
export function inferMechanics(profile: GameProfile): GameMechanics {
  if (profile.mechanics)
    return profile.mechanics
  const text = `${profile.name} ${profile.description} ${profile.actionSchema}`.toLowerCase()
  const mechanics: GameMechanic[] = []
  const has = (...keys: string[]) => keys.some(k => text.includes(k))
  if (has('wasd', '移动', 'move'))
    mechanics.push('movement-wasd')
  if (has('stick', '摇杆', '手柄'))
    mechanics.push('movement-stick')
  if (has('click', '点击移动', '点选'))
    mechanics.push('movement-click')
  if (has('aim', '瞄准', '准星'))
    mechanics.push('aiming')
  if (has('shoot', '射击', '开火', '枪'))
    mechanics.push('shooting')
  if (has('melee', '近战', '格斗', '普攻'))
    mechanics.push('melee')
  if (has('cooldown', '冷却', '技能栏', 'skill'))
    mechanics.push('skills-cooldown')
  if (has('hotbar', '物品栏', '快捷栏'))
    mechanics.push('skills-hotbar')
  if (has('dodge', '闪避', '翻滚', 'roll'))
    mechanics.push('dodge-roll')
  if (has('loot', '掉落', '拾取', '战利品', 'pickup'))
    mechanics.push('loot-pickup')
  if (has('harvest', '采集', '采矿', '砍伐'))
    mechanics.push('resource-harvest')
  if (has('inventory', '背包', '整理'))
    mechanics.push('inventory-management')
  if (has('regen', '回血', '生命恢复', '治疗'))
    mechanics.push('health-regen')
  if (has('cover', '掩体'))
    mechanics.push('cover-system')
  if (has('minimap', '小地图', '地图'))
    mechanics.push('minimap-navigation')
  if (has('quest', '任务', '目标', 'objective'))
    mechanics.push('quest-objective')
  if (has('boss', 'boss', '首领'))
    mechanics.push('boss-pattern')
  if (has('craft', '合成', '打造'))
    mechanics.push('crafting')
  if (has('build', '建造'))
    mechanics.push('building')
  if (has('dialogue', '对话', '选项'))
    mechanics.push('dialogue-choice')
  if (has('stealth', '潜行', '隐身'))
    mechanics.push('stealth')
  if (has('team', '队伍', '队友', '沟通'))
    mechanics.push('team-comms')
  if (has('trade', '交易', '买卖', '经济'))
    mechanics.push('economy-trade')
  if (has('resource', '资源', '管理'))
    mechanics.push('resource-management')
  if (!mechanics.length)
    mechanics.push('minimap-navigation')
  return { genre: 'other', mechanics }
}

/** 两个游戏档案的相似度（0~1），越大越能互相迁移经验 */
export function mechanicsSimilarity(a: GameProfile, b: GameProfile): number {
  const va = buildTransferVector(inferMechanics(a).mechanics)
  const vb = buildTransferVector(inferMechanics(b).mechanics)
  return cosineSimilarity(va, vb)
}
