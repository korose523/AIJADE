/**
 * 火炬之光无限（Torchlight Infinite）游戏档案。
 *
 * 这是一款 PvE 刷宝 ARPG（暗黑-like）。下面给出视觉/决策的提示词与动作 schema，
 * 仅用于「观察画面 → 理解状态 → 建议/执行操作」的合规自动化演示。
 *
 * 责任提示：自动化操作在线游戏可能违反其用户协议并导致账号封禁；此档案仅用于
 * 研究 / 无障碍 / 单机或许可场景，请勿用于破坏公平性的行为。
 */
import type { GameProfile } from '../types'

export const torchlightProfile: GameProfile = {
  id: 'torchlight-infinite',
  name: '火炬之光无限',
  description: 'PvE 刷宝 ARPG。观察画面中的角色、敌人、血量与掉落物，自动推进战斗与拾取。',
  defaultObsSource: '火炬之光无限',
  visionPrompt: [
    '这是《火炬之光无限》的游戏画面。请识别：',
    '1. 玩家角色位置（屏幕相对方位：左/中/右/上/下）；',
    '2. 玩家血量百分比与能量/法力百分比；',
    '3. 画面中可见敌人数量、与玩家的相对方位、距离（近/中/远）；',
    '4. 地面是否有可拾取掉落物（金色/彩色光点）及其方位；',
    '5. 当前是否处于战斗状态；',
    '6. 小地图是否有任务点/传送点提示。',
  ].join('\n'),
  plannerSystemPrompt: [
    '你是《火炬之光无限》的游戏 AI 副驾驶/操作 agent。',
    '你只能根据画面识别出的结构化状态做决策，不得假设看不到的信息。',
    '优先保证生存（血量低时后撤/闪避），其次清怪，最后拾取掉落物。',
    '动作要简洁、可执行，避免无意义的高频操作。',
  ].join('\n'),
  actionSchema: [
    'move(x,y)        把鼠标移到屏幕绝对坐标（0~1920, 0~1080 量级）',
    'moveRelative(dx,dy)  鼠标相对移动',
    'click(button)    点击：left=普攻 / right=技能',
    'key(key)         按键：w/a/s/d 移动，space 闪避，f 拾取，1~4 技能栏，q/e/r 技能',
    'hold(key,durationMs)  按住某键持续若干毫秒',
    'wheel(delta)     滚轮（delta 正负控制缩放/切换）',
    'wait(durationMs) 等待若干毫秒',
  ].join('\n'),
  allowedActions: ['move', 'moveRelative', 'click', 'key', 'hold', 'wheel', 'wait', 'noop'],
}
