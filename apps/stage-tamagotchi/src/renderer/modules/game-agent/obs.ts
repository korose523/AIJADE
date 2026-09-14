/**
 * OBS 捕获客户端（obs-websocket v5）。
 *
 * 渲染进程原生支持 WebSocket，因此无需任何 npm 依赖即可连接本机 OBS。
 * 「OBS 吸附」即指用 OBS 把游戏窗口画面捕获后交给 AIJADE 的 AI 分析——
 * 这里通过 GetSourceScreenshot 拉取指定源的截图（base64 PNG），作为感知输入。
 *
 * 参考 obs-websocket v5 协议：Hello(op0) → Identified(op2) → Request(op6)/RequestResponse(op7)。
 */
import type { GameFrame } from './types'

export interface ObsConnectionOptions {
  url: string
  password?: string
  sourceName: string
  imageFormat?: 'png' | 'jpg' | 'webp'
  width?: number
  height?: number
  quality?: number
}

export type ObsStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

interface PendingRequest {
  resolve: (value: any) => void
  reject: (reason: Error) => void
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (let i = 0; i < bytes.length; i++)
    binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

async function sha256Bytes(input: Uint8Array): Promise<Uint8Array> {
  const buf = await crypto.subtle.digest('SHA-256', input as BufferSource)
  return new Uint8Array(buf)
}

export class ObsCapture {
  private ws: WebSocket | null = null
  private readonly options: ObsConnectionOptions
  private pending = new Map<string, PendingRequest>()
  private msgId = 0
  status: ObsStatus = 'disconnected'
  onStatus?: (status: ObsStatus, detail?: string) => void

  constructor(options: ObsConnectionOptions) {
    this.options = options
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.status = 'connecting'
      this.onStatus?.('connecting')

      let ws: WebSocket
      try {
        ws = new WebSocket(this.options.url)
      }
      catch (err) {
        this.status = 'error'
        this.onStatus?.('error', String(err))
        reject(err as Error)
        return
      }
      this.ws = ws

      let connectedResolved = false

      ws.onopen = () => {
        // 等待 Hello(op0) 后回送 Identified(op1)
      }

      ws.onerror = () => {
        this.status = 'error'
        this.onStatus?.('error', 'WebSocket 连接失败')
        if (!connectedResolved) {
          connectedResolved = true
          reject(new Error('OBS WebSocket 连接失败'))
        }
      }

      ws.onclose = () => {
        this.status = 'disconnected'
        this.onStatus?.('disconnected')
      }

      ws.onmessage = (ev: MessageEvent) => {
        let msg: any
        try {
          msg = JSON.parse(ev.data as string)
        }
        catch {
          return
        }
        const op = msg.op
        const d = msg.d
        if (op === 0) {
          this.handleHello(d)
        }
        else if (op === 2) {
          this.status = 'connected'
          this.onStatus?.('connected')
          if (!connectedResolved) {
            connectedResolved = true
            resolve()
          }
        }
        else if (op === 7) {
          const id = d.requestId as string
          const pending = this.pending.get(id)
          if (!pending)
            return
          this.pending.delete(id)
          const status = d.requestStatus
          if (status && status.result === false) {
            pending.reject(new Error(status.comment || `OBS 请求失败 (code ${status.code})`))
          }
          else {
            pending.resolve(d.responseData)
          }
        }
      }
    })
  }

  private handleHello(d: any): void {
    const payload: any = { rpcVersion: d.rpcVersion ?? 1, eventSubscriptions: 0 }
    const auth = d.authentication
    if (auth && this.options.password) {
      // obs-websocket v5 挑战-应答认证
      const salt = auth.salt as string
      const challenge = auth.challenge as string
      const secretB64 = (async () => {
        const secretHash = await sha256Bytes(new TextEncoder().encode(this.options.password + salt))
        const authHash = await sha256Bytes(new TextEncoder().encode(bytesToBase64(secretHash) + challenge))
        return bytesToBase64(authHash)
      })()
      secretB64.then((authB64) => {
        payload.authentication = authB64
        this.ws?.send(JSON.stringify({ op: 1, d: payload }))
      }).catch(() => {
        this.ws?.send(JSON.stringify({ op: 1, d: payload }))
      })
      return
    }
    this.ws?.send(JSON.stringify({ op: 1, d: payload }))
  }

  /**
   * 发起一次 obs-websocket 请求。
   * 公开出来是为了让直播模块复用同一条连接做推流/场景/文本源控制，
   * 而不必为了改一行字幕再开一个 WebSocket。
   */
  call(requestType: string, requestData?: Record<string, unknown>): Promise<any> {
    return new Promise((resolve, reject) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
        reject(new Error('OBS 未连接'))
        return
      }
      const id = `req-${++this.msgId}`
      this.pending.set(id, { resolve, reject })
      this.ws.send(JSON.stringify({
        op: 6,
        d: { requestType, requestId: id, requestData },
      }))
    })
  }

  /** 抓取当前 OBS 源的截图，返回 GameFrame。 */
  async capture(): Promise<GameFrame> {
    const fmt = this.options.imageFormat ?? 'png'
    const resp: any = await this.call('GetSourceScreenshot', {
      sourceName: this.options.sourceName,
      imageFormat: fmt,
      imageWidth: this.options.width,
      imageHeight: this.options.height,
      imageCompressionQuality: this.options.quality ?? 80,
    })
    const imageData: string = resp.imageData
    const dataUrl = imageData.startsWith('data:')
      ? imageData
      : `data:image/${fmt};base64,${imageData}`
    return {
      dataUrl,
      width: resp.imageWidth ?? 0,
      height: resp.imageHeight ?? 0,
      timestamp: Date.now(),
    }
  }

  disconnect(): void {
    if (this.ws) {
      try {
        this.ws.close()
      }
      catch {
        // ignore
      }
      this.ws = null
    }
  }
}
