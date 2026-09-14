/**
 * 游戏 Agent 核心类型定义。
 *
 * 设计参照 korose523/AI-collaborative-game（ScreenPlay）的「感知 → 记忆 → 决策 → 行动」
 * 合规架构：仅读取画面（不读内存、不挂钩子），再由视觉模型理解、由规划器产出动作，
 * 最后（仅在自主模式下）向系统注入输入。所有类型都是与具体游戏/模型解耦的接口。
 */

export type AgentActionType
  = | 'move' // 绝对移动到屏幕坐标 (x, y)
    | 'moveRelative' // 相对移动 (dx, dy)
    | 'click' // 鼠标点击 (button)
    | 'key' // 键盘按键 (key, down?)
    | 'hold' // 按住某键 durationMs 毫秒
    | 'wheel' // 滚轮 (delta)
    | 'wait' // 等待 durationMs 毫秒
    | 'noop'

export interface AgentAction {
  type: AgentActionType
  /** move / moveRelative 用 */
  x?: number
  y?: number
  /** click 用 */
  button?: 'left' | 'right' | 'middle'
  /** key / hold 用 */
  key?: string
  /** key 用：true=按下，false=抬起，省略=完整单击 */
  down?: boolean
  durationMs?: number
  /** wheel 用 */
  delta?: number
  reason?: string
  /** Neuro 风格旁白 / 语音文本（AI 边玩边说） */
  say?: string
}

export interface GameFrame {
  dataUrl: string
  width: number
  height: number
  timestamp: number
}

export interface GameState {
  raw: string
  structured: Record<string, unknown>
  timestamp: number
}

// ———————————————————————————————————————————————
// 观察叠层（OBS 作为 AIJADE 的"眼睛"）：把 AIJADE 当下的注意力呈现回 OBS 场景
// ———————————————————————————————————————————————

/**
 * 一个检测/注意目标的归一化包围框（相对捕获源画面，0~1）。
 * 渲染到 OBS 叠层时按百分比定位，因此不依赖实际分辨率。
 */
export interface ObservationBox {
  label: string
  x: number
  y: number
  w: number
  h: number
  color?: string
}

/**
 * AIJADE「像人类一样观察」时的瞬时状态。
 * 它会被推送到主进程的 HUD 服务（http://localhost/hud.json），
 * 再由 OBS 场景里的浏览器源 / obs-urlsource 的 url_source 渲染出来——
 * 正是参考 obs-urlsource 把"外部 URL/API 数据"拉进 OBS 场景的做法。
 */
export interface ObservationState {
  ts: number
  /** 是否正在观察（连着 OBS 且已取到画面） */
  observing: boolean
  /** 游戏（档案）名称 */
  game: string
  /** 画面来源（OBS 源名） */
  source: string
  /** 此刻最关注的对象/事态（一句话） */
  focus: string
  /** 当前意图/目标（接下来想做什么） */
  goal: string
  /** 像主播一样的口头解说（AIJADE 边看边说） */
  narration: string
  /** 置信度 0~1 */
  confidence: number
  /** 观察帧率 */
  fps: number
  /** 检测框（可选；HUD 上把它们画成注意力高亮） */
  boxes: ObservationBox[]
}

// ———————————————————————————————————————————————
// 跨游戏知识迁移：游戏机制画像
// ———————————————————————————————————————————————

/**
 * 游戏类型。用于跨游戏相似度计算的粗粒度分组。
 */
export type GameGenre
  = | 'arpg' | 'arpg-looter' | 'fps' | 'tps' | 'moba'
    | 'rts' | 'survival' | 'platformer' | 'fighting'
    | 'puzzle' | 'racing' | 'rhythm' | 'other'

/**
 * 可迁移的"游戏机制"原子。跨游戏迁移时，AIJADE 比较两份机制集合的重叠程度，
 * 重叠越高（如都是"WASD 移动 + 射击 + 掩体"），从 A 游戏学到的技能就越能套到 B 游戏。
 */
export type GameMechanic
  = | 'movement-wasd' | 'movement-stick' | 'movement-click'
    | 'aiming' | 'shooting' | 'melee' | 'skills-cooldown' | 'skills-hotbar'
    | 'dodge-roll' | 'loot-pickup' | 'resource-harvest' | 'inventory-management'
    | 'health-regen' | 'cover-system' | 'minimap-navigation' | 'quest-objective'
    | 'boss-pattern' | 'crafting' | 'building' | 'dialogue-choice'
    | 'stealth' | 'team-comms' | 'economy-trade' | 'resource-management'

/** 机制全集（顺序即转移向量的维度顺序，必须稳定） */
export const GAME_MECHANICS: readonly GameMechanic[] = [
  'movement-wasd',
  'movement-stick',
  'movement-click',
  'aiming',
  'shooting',
  'melee',
  'skills-cooldown',
  'skills-hotbar',
  'dodge-roll',
  'loot-pickup',
  'resource-harvest',
  'inventory-management',
  'health-regen',
  'cover-system',
  'minimap-navigation',
  'quest-objective',
  'boss-pattern',
  'crafting',
  'building',
  'dialogue-choice',
  'stealth',
  'team-comms',
  'economy-trade',
  'resource-management',
]

/** 一份游戏的机制画像：类型 + 机制集合。 */
export interface GameMechanics {
  genre: GameGenre
  mechanics: GameMechanic[]
}

/**
 * 经验条目的"可迁移技能类别"——与具体游戏解耦的横向能力。
 * 例如"怎么保命""怎么找路""怎么打 Boss"，不同游戏都能复用同一类技能。
 */
export type SkillCategory
  = | 'navigation' // 怎么去该去的地方
    | 'combat' // 怎么打
    | 'resource' // 怎么捡/管资源
    | 'survival' // 怎么保命
    | 'ui-interaction' // 怎么操作界面/菜单
    | 'objective' // 怎么推进目标/任务
    | 'economy' // 怎么交易/买卖
    | 'meta' // 通用元策略（节奏、心态、习惯）

export interface GameProfile {
  id: string
  name: string
  description: string
  /** OBS 中该游戏画面的源名称（用户可在 UI 覆盖） */
  defaultObsSource?: string
  /** 真实游戏进程名（用于"锁定 OBS 到游戏"时监控进程、重新获取捕获源），如 'game.exe' */
  executable?: string
  /** 交给视觉模型的提示词（让其输出结构化状态） */
  visionPrompt: string
  /** 交给规划器的系统提示词 */
  plannerSystemPrompt: string
  /** 规划器可用动作 schema 描述 */
  actionSchema: string
  /** 该档案允许的动作类型（安全限制） */
  allowedActions: AgentActionType[]
  /** 跨游戏迁移所需的机制画像；缺省时按描述做兜底推断 */
  mechanics?: GameMechanics
}

export interface VisionRequest {
  frame: GameFrame
  profile: GameProfile
  history?: GameState[]
  /**
   * 可选的额外指令。观察模式会注入"像人类一样观察并解说"的提示，
   * 让视觉模型额外输出 focus / goal / narration / boxes，供 OBS 观察叠层使用。
   */
  instruction?: string
}

export interface VisionBackend {
  id: string
  name: string
  readonly available: boolean
  analyze: (req: VisionRequest) => Promise<GameState>
}

export interface PlannerRequest {
  state: GameState
  profile: GameProfile
  history?: GameState[]
  goal?: string
  /**
   * 学习子系统注入的经验知识（已渲染为提示词片段）。
   * 来自真机学习 / 视频学习提炼出的 KnowledgeItem，让决策"有据可依"。
   */
  knowledge?: string
}

export interface Planner {
  id: string
  name: string
  readonly available: boolean
  plan: (req: PlannerRequest) => Promise<AgentAction[]>
}

export interface InputBackend {
  id: string
  name: string
  /** true = 不实际注入（演练），false = 真实注入 */
  readonly safe: boolean
  execute: (actions: AgentAction[]) => Promise<void>
}

/**
 * Neuro SDK 服务器（VedalAI 协议）与渲染端共享的状态/配置类型。
 * 放在渲染侧 types，主进程 neuro-server 以 type-only 方式复用，避免渲染→主进程反向依赖。
 */
export interface NeuroServerOptions {
  port?: number
  baseUrl?: string
  model?: string
  systemPrompt?: string
  goal?: string
}

export interface NeuroServerStatus {
  running: boolean
  port: number
  connectedGame: string | null
  lastSay: string
  registeredActions: { name: string, description?: string }[]
  logs: string[]
}

/** 输入注入安全网状态（主进程持有，渲染端轮询） */
export interface InputSafetyStatus {
  /** 紧急停止是否被触发（全局热键 F9） */
  panic: boolean
  /** 注册的紧急停止热键 */
  panicHotkey: string
  /** 热键是否注册成功 */
  hotkeyRegistered: boolean
  /** 累计注入的动作数 */
  injectedActions: number
  /** 最近一次注入时间戳 */
  lastInjectedAt: number
}

/** OBS 直播状态 */
export interface StreamStatus {
  streaming: boolean
  recording: boolean
  /** 已推流时长（毫秒） */
  durationMs: number
  /** 当前比特率（kbps） */
  kbitsPerSec: number
  /** 丢帧数 */
  skippedFrames: number
  /** 总帧数 */
  totalFrames: number
}
