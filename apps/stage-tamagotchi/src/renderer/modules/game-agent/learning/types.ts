/**
 * 游戏「学习」子系统类型定义。
 *
 * 学习分两条路径：
 *  1. 真机学习（real-machine）：监控真人玩游戏——同步采集「屏幕画面 + 键鼠操作」，
 *     得到带动作标注的示范序列（类似模仿学习中的 demonstration）。
 *  2. 视频学习（video）：观看游戏录像 / 直播 / 解析视频——只有画面（可能带解说），
 *     没有真实操作标注，靠视觉模型描述画面并由语言模型提炼战术知识。
 *
 * 两条路径最终都收敛到统一产物：KnowledgeItem（可检索、可注入决策提示词的经验条目）。
 */
import type { AgentAction, SkillCategory } from '../types'

/** 学习来源 */
export type LearningSource = 'real-machine' | 'video' | 'manual'

/** 真人操作事件（由主进程录制器采集，时间戳相对录制起点） */
export interface InputEvent {
  /** 相对录制开始的毫秒数 */
  t: number
  kind: 'key' | 'mouse' | 'move' | 'wheel'
  /** kind=key 时的按键名（小写，如 'w' / 'space' / 'shift'） */
  key?: string
  /** kind=mouse 时的按钮 */
  button?: 'left' | 'right' | 'middle'
  /** 按下 true / 抬起 false */
  down?: boolean
  /** kind=move 时的屏幕坐标 */
  x?: number
  y?: number
  /** kind=wheel 时的滚动量 */
  delta?: number
}

/** 关键帧：某一时刻的画面 + 视觉理解结果 */
export interface LearningKeyframe {
  /** 相对录制开始的毫秒数 */
  t: number
  /** 缩略图（dataURL）。为控制体积，落盘时可被剔除 */
  thumbnail?: string
  /** 视觉模型对该帧的自然语言描述 */
  caption?: string
  /** 视觉模型输出的结构化状态 */
  structured?: Record<string, unknown>
  /** 该帧附近（±window）真人做了哪些操作，用于「看到什么 → 做了什么」配对 */
  nearbyActions?: string[]
}

/** 一段学习素材（一次真机录制，或一个视频的学习结果） */
export interface LearningEpisode {
  id: string
  source: LearningSource
  profileId: string
  title: string
  startedAt: number
  endedAt: number
  /** 素材时长（毫秒） */
  durationMs: number
  /** 真机学习：真人操作序列；视频学习为空 */
  events: InputEvent[]
  /** 抽帧后的关键帧序列 */
  keyframes: LearningKeyframe[]
  /** 视频学习时的来源描述（文件名 / URL / OBS 源名） */
  origin?: string
  /** 用户补充的备注（例如「这局是 BD 教学，重点看技能循环」） */
  notes?: string
  /** 已由该素材提炼出的知识条目数 */
  distilledCount?: number
}

/** 知识条目类型 */
export type KnowledgeKind
  = | 'rule' // 条件-动作规则："血量低于 30% 时后撤并吃药"
    | 'combo' // 连招 / 技能循环：可直接回放的动作序列
    | 'hotkey' // 按键映射："Q 是位移技能"
    | 'tip' // 战术要点 / 常识
    | 'mistake' // 反面教材："不要站在红圈里"

export interface KnowledgeItem {
  id: string
  profileId: string
  source: LearningSource
  kind: KnowledgeKind
  /** 简短标题 */
  title: string
  /** 适用条件（自然语言，用于检索匹配当前状态） */
  condition: string
  /** 应当采取的行为（自然语言） */
  action: string
  /** 若是 combo，可直接执行的动作序列 */
  sequence?: AgentAction[]
  /** 置信度 0~1 */
  confidence: number
  tags: string[]
  createdAt: number
  /** 被注入决策上下文的次数，用于淘汰低价值知识 */
  usedCount: number
  /** 来源素材 id */
  episodeId?: string
  // —— 跨游戏迁移相关（缺省视为未分类，不影响既有检索）——
  /** 横向可迁移技能类别（与具体游戏解耦） */
  skillCategory?: SkillCategory
  /** 该经验是否为"游戏无关"的通用经验（如"保持血量健康"），跨游戏迁移优先级更高 */
  universal?: boolean
  /** 该经验涉及的机制标签（取自 GameMechanic），用于跨游戏相似度加权 */
  gameTags?: string[]
}

/** 录制器实时状态（主进程 → 渲染进程） */
export interface RecorderStatus {
  running: boolean
  /** 已采集事件总数 */
  eventCount: number
  /** 录制开始时间戳（毫秒，绝对时间） */
  startedAt: number
  /** 最近一次错误 */
  error?: string
}

/** 录制器增量拉取结果 */
export interface RecorderPollResult extends RecorderStatus {
  events: InputEvent[]
}

/** 真机学习运行期统计 */
export interface RealMachineStats {
  /** 每分钟操作数 */
  apm: number
  /** 按键使用次数（按下计数） */
  keyCounts: Record<string, number>
  /** 鼠标点击次数 */
  clickCounts: Record<string, number>
  /** 已捕获关键帧数 */
  frameCount: number
  /** 已录制时长（毫秒） */
  elapsedMs: number
}

/** 视频学习的素材来源 */
export type VideoSourceKind
  = | 'file' // 本地视频文件
    | 'url' // 可直接播放的视频直链
    | 'obs' // OBS 源（用于「看直播」：把播放器/浏览器窗口做成 OBS 源）

export interface VideoLearningOptions {
  kind: VideoSourceKind
  /** file: 由 <input type=file> 得到的对象 URL；url: 直链；obs: 源名称 */
  target: string
  /** 抽帧间隔（毫秒，按素材时间轴计算） */
  sampleIntervalMs: number
  /** 最多抽多少帧，防止长视频撑爆内存 */
  maxFrames: number
  /** 是否让视觉模型逐帧描述（关掉则只存帧，学习速度快但知识少） */
  captionFrames: boolean
}

/** 知识检索请求 */
export interface KnowledgeQuery {
  profileId: string
  /** 当前游戏状态的文本形式，用于相关性打分 */
  stateText?: string
  goal?: string
  limit?: number
  kinds?: KnowledgeKind[]
}
