/**
 * 决策后端：根据结构化游戏状态产出动作序列。
 *
 * - OllamaPlanner：调用本地 ollama 文本模型（如 qwen3.6-35b-a3b），输出动作 JSON 数组。
 * - MockPlanner：脚本化动作，用于演示（默认在副驾驶模式下不会真正注入）。
 */
import type { AgentAction, Planner, PlannerRequest } from './types'

export interface OllamaPlannerOptions {
  baseUrl?: string
  model: string
  temperature?: number
}

async function postOllamaJson(baseUrl: string, model: string, system: string, user: string, temperature: number): Promise<any> {
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
    return { actions: [] }
  }
}

export class OllamaPlanner implements Planner {
  id = 'ollama-planner'
  name = 'Ollama 规划器'
  readonly available = true

  constructor(private readonly opts: OllamaPlannerOptions) {}

  async plan(req: PlannerRequest): Promise<AgentAction[]> {
    const { state, profile, history, goal } = req
    const historyLine = history && history.length
      ? `\n近期状态：\n${history.slice(-3).map(h => JSON.stringify(h.structured)).join('\n')}`
      : ''
    const goalLine = goal
      ? `\n你的总体目标（goal 模式）：${goal}`
      : ''
    const user = [
      `当前游戏状态：\n${JSON.stringify(state.structured)}`,
      historyLine,
      `目标：${goal || '推进游戏进程（刷怪 / 拾取 / 生存）'}`,
      '只输出 JSON，形如 {"actions":[{"type":"...","reason":"..."}],"say":"<一句简短旁白>"}，最多 5 个动作。',
      `可用动作（只能从下列类型中选，且必须属于该游戏允许集合）：\n${profile.actionSchema}`,
    ].join('\n')

    const parsed = await postOllamaJson(this.opts.baseUrl ?? 'http://localhost:11434', this.opts.model, profile.plannerSystemPrompt + goalLine, user, this.opts.temperature ?? 0.4)
    const actions = Array.isArray(parsed) ? parsed : parsed.actions
    if (!Array.isArray(actions))
      return []
    const filtered = actions.filter((a: AgentAction) => profile.allowedActions.includes(a.type)) as AgentAction[]
    const say = typeof (parsed as any)?.say === 'string' ? (parsed as any).say : undefined
    if (say && filtered.length)
      filtered[0].say = say
    return filtered
  }
}

export class MockPlanner implements Planner {
  id = 'mock-planner'
  name = '模拟规划器（脚本演示）'
  readonly available = true

  async plan(req: PlannerRequest): Promise<AgentAction[]> {
    // 演示用脚本：前进探索 + 普攻 + 闪避 + 拾取，循环往复。
    const goal = req.goal
    const roll = Math.random()
    if (roll < 0.4) {
      return [
        { type: 'key', key: 'w', down: true, reason: '向前移动探索', say: goal ? `去完成「${goal}」，先往前探探路。` : '往前探探路～' },
        { type: 'click', button: 'left', reason: '普攻' },
        { type: 'wait', durationMs: 400 },
        { type: 'key', key: 'w', down: false },
      ]
    }
    if (roll < 0.7) {
      return [
        { type: 'key', key: 'space', reason: '闪避/翻滚' },
        { type: 'click', button: 'right', reason: '技能' },
        { type: 'wait', durationMs: 300 },
      ]
    }
    return [
      { type: 'key', key: 'f', reason: '拾取附近物品' },
      { type: 'moveRelative', x: 40, y: 0, reason: '向敌人微调' },
      { type: 'wait', durationMs: 250 },
    ]
  }
}
