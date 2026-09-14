/**
 * 视觉后端：把游戏画面变成结构化状态。
 *
 * - OllamaVisionBackend：调用本地 ollama 的多模态模型（如 qwen2.5-vl），输出 JSON。
 * - MockVisionBackend：无需模型，返回占位结构，便于在无 GPU/无模型时演示整条链路。
 */
import type { GameState, VisionBackend, VisionRequest } from './types'

export interface OllamaOptions {
  baseUrl?: string
  model: string
  temperature?: number
}

async function postOllama(baseUrl: string, model: string, prompt: string, images: string[], temperature: number): Promise<string> {
  const resp = await fetch(`${baseUrl.replace(/\/$/, '')}/api/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model,
      prompt,
      images,
      format: 'json',
      stream: false,
      options: { temperature },
    }),
  })
  if (!resp.ok)
    throw new Error(`Ollama 返回 ${resp.status}`)
  const data = await resp.json()
  return typeof data.response === 'string' ? data.response : JSON.stringify(data)
}

function stripDataUrlPrefix(dataUrl: string): string {
  const idx = dataUrl.indexOf(',')
  return idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl
}

export class OllamaVisionBackend implements VisionBackend {
  id = 'ollama-vision'
  name = 'Ollama 视觉模型'
  readonly available = true

  constructor(private readonly opts: OllamaOptions) {}

  async analyze(req: VisionRequest): Promise<GameState> {
    const { frame, profile, history } = req
    const historyLine = history && history.length
      ? `\n近期状态：\n${history.slice(-3).map(h => JSON.stringify(h.structured)).join('\n')}`
      : ''
    const prompt = [
      '你是游戏画面状态识别器。根据提供的游戏截图，提取结构化信息。',
      `游戏：${profile.name}`,
      profile.visionPrompt,
      '请只输出一个 JSON 对象（不要解释、不要 markdown 代码块），尽量包含：玩家血量/能量、敌人数量与相对方位、可拾取物品、是否在战斗、小地图提示等。',
      historyLine,
      req.instruction,
    ].filter(Boolean).join('\n')

    const raw = await postOllama(this.opts.baseUrl ?? 'http://localhost:11434', this.opts.model, prompt, [stripDataUrlPrefix(frame.dataUrl)], this.opts.temperature ?? 0.2)
    let structured: Record<string, unknown> = {}
    try {
      structured = JSON.parse(raw)
    }
    catch {
      structured = { note: '视觉模型未返回合法 JSON', raw }
    }
    return { raw, structured, timestamp: Date.now() }
  }
}

export class MockVisionBackend implements VisionBackend {
  id = 'mock-vision'
  name = '模拟视觉（无需模型）'
  readonly available = true

  async analyze(_req: VisionRequest): Promise<GameState> {
    const structured: Record<string, unknown> = {
      note: '模拟视觉输出',
      hp: 0.8,
      energy: 0.6,
      enemies: 3,
      inCombat: true,
      lootNearby: 1,
      playerPosition: '中心',
    }
    return { raw: JSON.stringify(structured), structured, timestamp: Date.now() }
  }
}
