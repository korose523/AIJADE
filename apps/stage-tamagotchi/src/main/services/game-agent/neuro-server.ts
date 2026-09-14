import type { Server } from 'node:http'
import type { Duplex } from 'node:stream'

import type { NeuroServerOptions, NeuroServerStatus } from '../../../renderer/modules/game-agent/types'

/**
 * Neuro SDK 服务器（主进程）—— 让 AIJADE 成为任何 neuro-sdk 游戏的「AI 大脑」。
 *
 * 参考：https://github.com/VedalAI/neuro-game-sdk
 * 该协议由 Vedal（Neuro-sama）提出：游戏作为 WebSocket 客户端连接 AI（默认 localhost:8000），
 * 注册可选动作、上报文本化游戏状态（可带截图），AI 决策后回传「动作 + say（旁白/语音）」。
 *
 * 本实现零外部依赖：用 Node 内置 http/crypto/net 完成 WebSocket 握手与帧编解码，
 * 主进程直接调用 Ollama /api/chat 做决策（支持 image 多模态）；无可用模型时自动 mock 兜底，
 * 保证链路随时可演示。仅暴露 start/stop/status 三个 IPC，由渲染进程面板控制启停。
 *
 * 安全：服务器只在用户于 UI 显式「启动」后监听；默认仅 localhost。决策的「真实按键」由游戏侧执行，
 * AIJADE 只输出动作意图与旁白，不在此处直接注入系统输入。
 */
import { createHash } from 'node:crypto'
import { createServer } from 'node:http'

import { ipcMain } from 'electron'

const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
const DEFAULT_PORT = 8000

export interface NeuroActionDef {
  name: string
  description?: string
}

export interface NeuroContextItem {
  role: string
  content: string
}

export interface NeuroDecision {
  action: string
  data: Record<string, unknown>
  say: string
}

function encodeWsFrame(data: string): Buffer {
  const payload = Buffer.from(data, 'utf8')
  const len = payload.length
  let header: Buffer
  if (len < 126) {
    header = Buffer.alloc(2)
    header[1] = len
  }
  else if (len < 65536) {
    header = Buffer.alloc(4)
    header[1] = 126
    header.writeUInt16BE(len, 2)
  }
  else {
    header = Buffer.alloc(10)
    header[1] = 127
    header.writeBigUInt64BE(BigInt(len), 2)
  }
  header[0] = 0x81 // FIN + text opcode
  return Buffer.concat([header, payload])
}

function decodeWsFrames(buf: Buffer<ArrayBufferLike>): { frames: { opcode: number, data: Buffer<ArrayBufferLike> }[], rest: Buffer<ArrayBufferLike> } {
  const frames: { opcode: number, data: Buffer<ArrayBufferLike> }[] = []
  let offset = 0
  while (offset + 2 <= buf.length) {
    const b0 = buf[offset]
    const b1 = buf[offset + 1]
    const fin = (b0 & 0x80) !== 0
    const opcode = b0 & 0x0F
    const masked = (b1 & 0x80) !== 0
    let len = b1 & 0x7F
    let p = offset + 2
    if (len === 126) {
      if (offset + 4 > buf.length)
        break
      len = buf.readUInt16BE(offset + 2)
      p = offset + 4
    }
    else if (len === 127) {
      if (offset + 10 > buf.length)
        break
      len = Number(buf.readBigUInt64BE(offset + 2))
      p = offset + 10
    }
    let maskKey: Buffer | null = null
    if (masked) {
      if (p + 4 > buf.length)
        break
      maskKey = buf.subarray(p, p + 4)
      p += 4
    }
    if (p + len > buf.length)
      break
    let data = buf.subarray(p, p + len)
    if (masked && maskKey) {
      const un = Buffer.alloc(len)
      for (let i = 0; i < len; i++)
        un[i] = data[i] ^ maskKey[i % 4]
      data = un
    }
    if (opcode === 0x0 && !fin) {
      // 续帧：累积，等 FIN
      ;(buf as unknown as { _frag?: Buffer })._frag = Buffer.concat([(buf as unknown as { _frag?: Buffer })._frag ?? Buffer.alloc(0), data])
      offset = p + len
      continue
    }
    if (opcode === 0x0 && fin) {
      const full = Buffer.concat([(buf as unknown as { _frag?: Buffer })._frag ?? Buffer.alloc(0), data])
      ;(buf as unknown as { _frag?: Buffer })._frag = Buffer.alloc(0)
      frames.push({ opcode: 0x1, data: full })
      offset = p + len
      continue
    }
    frames.push({ opcode, data })
    offset = p + len
  }
  return { frames, rest: buf.subarray(offset) }
}

class NeuroGameServer {
  private server: Server | null = null
  private socket: Duplex | null = null
  private recvBuf: Buffer<ArrayBufferLike> = Buffer.alloc(0)

  running = false
  port = DEFAULT_PORT
  baseUrl = 'http://localhost:11434'
  model = 'qwen2.5-vl'
  systemPrompt = '你是一个 AI 游戏玩家（参考 Neuro-sama 风格）。根据游戏上报的状态与已注册动作，选择最合理的动作，并给出一句简短的旁白（say）。'
  goal = ''
  connectedGame: string | null = null
  lastSay = ''
  registeredActions: NeuroActionDef[] = []
  logs: string[] = []

  start(opts: NeuroServerOptions = {}): void {
    if (this.running)
      return
    this.port = opts.port ?? DEFAULT_PORT
    this.baseUrl = opts.baseUrl ?? this.baseUrl
    this.model = opts.model ?? this.model
    if (opts.systemPrompt)
      this.systemPrompt = opts.systemPrompt
    this.goal = opts.goal ?? ''
    this.registeredActions = []
    this.connectedGame = null
    this.lastSay = ''
    this.logs = []
    this.recvBuf = Buffer.alloc(0)

    this.server = createServer((_req, res) => {
      res.writeHead(426, { 'Content-Type': 'text/plain' })
      res.end('WebSocket only')
    })
    this.server.on('upgrade', (req, socket, head) => this.handleUpgrade(req, socket, head))
    this.server.on('error', (err) => {
      this.log(`服务器错误：${err.message}`)
    })
    this.server.listen(this.port, '127.0.0.1', () => {
      this.running = true
      this.log(`Neuro SDK 服务器已启动：ws://localhost:${this.port}`)
    })
  }

  stop(): void {
    try {
      this.socket?.destroy()
    }
    catch { /* ignore */ }
    this.socket = null
    this.server?.close()
    this.server = null
    this.running = false
    this.connectedGame = null
    this.log('Neuro SDK 服务器已停止')
  }

  getStatus(): NeuroServerStatus {
    return {
      running: this.running,
      port: this.port,
      connectedGame: this.connectedGame,
      lastSay: this.lastSay,
      registeredActions: [...this.registeredActions],
      logs: [...this.logs],
    }
  }

  private log(m: string): void {
    const line = `[${new Date().toLocaleTimeString()}] ${m}`
    this.logs.push(line)
    if (this.logs.length > 200)
      this.logs.shift()
    console.info('[neuro-server]', m)
  }

  private handleUpgrade(req: import('node:http').IncomingMessage, socket: Duplex, head: Buffer): void {
    const key = req.headers['sec-websocket-key']
    if (!key) {
      socket.destroy()
      return
    }
    const accept = createHash('sha1').update(key + WS_GUID).digest('base64')
    socket.write(
      'HTTP/1.1 101 Switching Protocols\r\n'
      + 'Upgrade: websocket\r\n'
      + 'Connection: Upgrade\r\n'
      + `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
    )
    this.socket = socket
    this.connectedGame = req.url && req.url.length > 1 ? decodeURIComponent(req.url.slice(1)) : 'neuro-game'
    this.log(`游戏已连接：${this.connectedGame}`)
    this.recvBuf = Buffer.from(head)

    socket.on('data', (chunk: Buffer) => this.onData(chunk))
    socket.on('close', () => {
      this.log('游戏断开连接')
      this.socket = null
      this.connectedGame = null
    })
    socket.on('error', err => this.log(`socket 错误：${err.message}`))
  }

  private onData(chunk: Buffer): void {
    this.recvBuf = Buffer.concat([this.recvBuf, chunk])
    const { frames, rest } = decodeWsFrames(this.recvBuf)
    this.recvBuf = rest
    for (const f of frames) {
      if (f.opcode === 0x8) {
        // close
        this.socket?.end()
        return
      }
      if (f.opcode === 0x9) {
        // ping -> pong
        this.socket?.write(Buffer.concat([Buffer.from([0x8A, f.data.length]), f.data]))
        continue
      }
      if (f.opcode === 0x1) {
        try {
          const text = f.data.toString('utf8')
          this.handleMessage(text)
        }
        catch (err) {
          this.log(`消息解析失败：${err instanceof Error ? err.message : String(err)}`)
        }
      }
    }
  }

  private send(obj: unknown): void {
    if (!this.socket || this.socket.destroyed)
      return
    try {
      this.socket.write(encodeWsFrame(JSON.stringify(obj)))
    }
    catch (err) {
      this.log(`发送失败：${err instanceof Error ? err.message : String(err)}`)
    }
  }

  private handleMessage(text: string): void {
    let msg: Record<string, any>
    try {
      msg = JSON.parse(text)
    }
    catch {
      this.log('收到非 JSON 消息，已忽略')
      return
    }
    const type = msg.type
    if (type === 'registerActions') {
      const actions = Array.isArray(msg.actions) ? msg.actions : []
      this.registeredActions = actions
        .filter((a: any) => a && typeof a.name === 'string')
        .map((a: any) => ({ name: a.name, description: typeof a.description === 'string' ? a.description : undefined }))
      this.log(`已注册 ${this.registeredActions.length} 个动作：${this.registeredActions.map(a => a.name).join(', ')}`)
    }
    else if (type === 'state') {
      const state = typeof msg.state === 'string' ? msg.state : ''
      const image = typeof msg.image === 'string' ? msg.image : undefined
      const context: NeuroContextItem[] = Array.isArray(msg.context) ? msg.context : []
      this.log(`收到状态（${state.length} 字${image ? ' + 截图' : ''}）`)
      this.decide(state, context, image).then((decision) => {
        this.lastSay = decision.say
        this.send({ type: 'action', action: decision.action, data: decision.data, say: decision.say })
        this.log(`决策 → 动作=${decision.action}；旁白=${decision.say.slice(0, 60)}`)
      }).catch((err) => {
        this.log(`决策出错：${err instanceof Error ? err.message : String(err)}`)
      })
    }
    else if (type === 'query') {
      const query = typeof msg.query === 'string' ? msg.query : ''
      this.log(`收到 query：${query.slice(0, 40)}`)
      this.decide(query, [], undefined, true).then((decision) => {
        this.lastSay = decision.say
        this.send({ type: 'response', response: decision.say })
        this.log(`回应 query：${decision.say.slice(0, 60)}`)
      }).catch((err) => {
        this.log(`query 出错：${err instanceof Error ? err.message : String(err)}`)
      })
    }
    else {
      this.log(`未知消息类型：${type}`)
    }
  }

  private async decide(
    state: string,
    context: NeuroContextItem[],
    image: string | undefined,
    isQuery = false,
  ): Promise<NeuroDecision> {
    const actionsText = this.registeredActions.length
      ? this.registeredActions.map(a => `- ${a.name}${a.description ? `：${a.description}` : ''}`).join('\n')
      : '- (无已注册动作，请回复空动作)'

    const goalLine = this.goal ? `\n\n你的总体目标：${this.goal}` : ''
    const systemContent = `${this.systemPrompt}\n\n你可以使用的动作（只能从中选一个）：\n${actionsText}${goalLine}\n\n请只输出一个 JSON 对象，不要任何额外文字，格式：{"action":"<动作名>","data":{},"say":"<一句简短旁白/语音>"}。${isQuery ? ' 这是观众的提问，请直接用 say 回答，action 置为 ""。' : ''}`

    const messages: any[] = [{ role: 'system', content: systemContent }]
    for (const c of context)
      messages.push({ role: c.role === 'user' || c.role === 'assistant' || c.role === 'system' ? c.role : 'user', content: c.content })
    if (image) {
      messages.push({ role: 'user', content: state || '（见截图）', images: [image] })
    }
    else {
      messages.push({ role: 'user', content: state || (isQuery ? '请回应。' : '请做出决策。') })
    }

    try {
      const res = await fetch(`${this.baseUrl.replace(/\/$/, '')}/api/chat`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ model: this.model, messages, stream: false }),
      })
      if (!res.ok)
        throw new Error(`Ollama HTTP ${res.status}`)
      const json: any = await res.json()
      const content: string = json?.message?.content ?? ''
      const decision = parseDecision(content, this.registeredActions)
      if (decision)
        return decision
      throw new Error('无法解析模型输出')
    }
    catch (err) {
      this.log(`模型不可用（${err instanceof Error ? err.message : String(err)}），使用 mock 兜底`)
      return mockDecision(this.registeredActions, isQuery)
    }
  }
}

function parseDecision(content: string, actions: NeuroActionDef[]): NeuroDecision | null {
  const start = content.indexOf('{')
  const end = content.lastIndexOf('}')
  if (start < 0 || end < 0 || end <= start)
    return null
  let obj: any
  try {
    obj = JSON.parse(content.slice(start, end + 1))
  }
  catch {
    return null
  }
  const actionName = typeof obj.action === 'string' ? obj.action : ''
  const valid = actions.find(a => a.name === actionName)
  return {
    action: valid ? valid.name : (actions[0]?.name ?? ''),
    data: typeof obj.data === 'object' && obj.data ? obj.data : {},
    say: typeof obj.say === 'string' ? obj.say : '',
  }
}

function mockDecision(actions: NeuroActionDef[], isQuery: boolean): NeuroDecision {
  if (isQuery)
    return { action: '', data: {}, say: '（离线演示）我听到你的问题啦，连上模型后我会认真回答～' }
  const pick = actions.length ? actions[Math.floor(Math.random() * actions.length)].name : 'noop'
  return { action: pick, data: {}, say: `（离线演示）我选择动作：${pick}` }
}

const server = new NeuroGameServer()

export function registerNeuroServer(): void {
  ipcMain.handle('game-agent:neuro-server:start', (_event, opts: NeuroServerOptions) => {
    server.start(opts)
    return server.getStatus()
  })
  ipcMain.handle('game-agent:neuro-server:stop', () => {
    server.stop()
    return server.getStatus()
  })
  ipcMain.handle('game-agent:neuro-server:status', () => server.getStatus())
}
