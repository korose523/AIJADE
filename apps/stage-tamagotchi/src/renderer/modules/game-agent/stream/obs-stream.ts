/**
 * OBS 直播控制器 —— 在「捕获画面」之外，把 OBS 的推流能力也接过来。
 *
 * 游戏 Agent 已经在用 obs-websocket 拉截图做感知，那条连接顺手就能控制推流、
 * 切场景、改字幕文本源。所以这里不新建连接，直接复用 ObsCapture 的 call()。
 *
 * 直播时 AIJADE 需要的四件事都在这里：
 *   1. 开/关推流与录制，并读取码率、丢帧等健康指标；
 *   2. 切场景（比如开场画面 → 游戏画面 → 结束画面）；
 *   3. 往文本源里写字幕（AI 的旁白同步显示给观众）；
 *   4. 显示/隐藏某个源（比如"AI 正在思考"的提示层）。
 */
import type { ObsCapture } from '../obs'
import type { StreamStatus } from '../types'

export interface SceneInfo {
  current: string
  scenes: string[]
}

export interface InputInfo {
  name: string
  kind: string
}

const EMPTY_STATUS: StreamStatus = {
  streaming: false,
  recording: false,
  durationMs: 0,
  kbitsPerSec: 0,
  skippedFrames: 0,
  totalFrames: 0,
}

export class ObsStreamController {
  private lastBytes = 0
  private lastBytesAt = 0

  constructor(private readonly obs: ObsCapture) {}

  /** 合并推流 + 录制状态，并按字节增量估算实时码率 */
  async getStatus(): Promise<StreamStatus> {
    const [stream, record] = await Promise.all([
      this.obs.call('GetStreamStatus').catch(() => null),
      this.obs.call('GetRecordStatus').catch(() => null),
    ])
    if (!stream && !record)
      return { ...EMPTY_STATUS }

    const now = Date.now()
    const bytes: number = stream?.outputBytes ?? 0
    let kbps = 0
    if (this.lastBytesAt && bytes > this.lastBytes) {
      const seconds = (now - this.lastBytesAt) / 1000
      if (seconds > 0.2)
        kbps = Math.round(((bytes - this.lastBytes) * 8) / 1000 / seconds)
    }
    if (!this.lastBytesAt || bytes >= this.lastBytes) {
      this.lastBytes = bytes
      this.lastBytesAt = now
    }

    return {
      streaming: Boolean(stream?.outputActive),
      recording: Boolean(record?.outputActive),
      durationMs: Math.round(stream?.outputDuration ?? record?.outputDuration ?? 0),
      kbitsPerSec: kbps,
      skippedFrames: stream?.outputSkippedFrames ?? 0,
      totalFrames: stream?.outputTotalFrames ?? 0,
    }
  }

  async startStreaming(): Promise<void> {
    await this.obs.call('StartStream')
  }

  async stopStreaming(): Promise<void> {
    await this.obs.call('StopStream')
    this.lastBytes = 0
    this.lastBytesAt = 0
  }

  async startRecording(): Promise<void> {
    await this.obs.call('StartRecord')
  }

  async stopRecording(): Promise<string> {
    const resp = await this.obs.call('StopRecord')
    return resp?.outputPath ?? ''
  }

  async listScenes(): Promise<SceneInfo> {
    const resp = await this.obs.call('GetSceneList')
    const scenes: string[] = Array.isArray(resp?.scenes)
      ? resp.scenes.map((s: any) => String(s.sceneName)).reverse()
      : []
    return { current: resp?.currentProgramSceneName ?? '', scenes }
  }

  async setScene(sceneName: string): Promise<void> {
    await this.obs.call('SetCurrentProgramScene', { sceneName })
  }

  /** 列出输入源，可按类型过滤（文本源常见 kind：text_gdiplus_v3 / text_ft2_source_v2） */
  async listInputs(inputKind?: string): Promise<InputInfo[]> {
    const resp = await this.obs.call('GetInputList', inputKind ? { inputKind } : undefined)
    if (!Array.isArray(resp?.inputs))
      return []
    return resp.inputs.map((i: any) => ({
      name: String(i.inputName),
      kind: String(i.unversionedInputKind ?? i.inputKind ?? ''),
    }))
  }

  /** 只挑出文本类输入源，供 UI 选字幕源 */
  async listTextInputs(): Promise<InputInfo[]> {
    const all = await this.listInputs()
    return all.filter(i => i.kind.includes('text'))
  }

  /** 写字幕。OBS 文本源的设置字段就叫 text。 */
  async setText(inputName: string, text: string): Promise<void> {
    if (!inputName)
      return
    await this.obs.call('SetInputSettings', {
      inputName,
      inputSettings: { text },
      overlay: true,
    })
  }

  async setSourceVisible(sceneName: string, sourceName: string, visible: boolean): Promise<void> {
    const resp = await this.obs.call('GetSceneItemId', { sceneName, sourceName })
    const sceneItemId = resp?.sceneItemId
    if (typeof sceneItemId !== 'number')
      return
    await this.obs.call('SetSceneItemEnabled', {
      sceneName,
      sceneItemId,
      sceneItemEnabled: visible,
    })
  }
}
