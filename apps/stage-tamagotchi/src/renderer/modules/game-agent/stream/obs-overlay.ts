import type { ObsCapture } from '../obs'
import type { ObservationState } from '../types'

/**
 * 观察叠层控制器 —— 把 AIJADE 的"观察注意力"渲染进 OBS 场景。
 *
 * 设计直接参考 obs-urlsource 的源码（royshil/obs-urlsource）：
 * 那个插件注册了一个 id 为 "url_source" 的 OBS 输入，它周期性地去 fetch 一个
 * URL/API、把拿到的文本/JSON 渲染到场景上。我们把 AIJADE 的观察状态也通过
 * "本地 HTTP 端点 + OBS 源"的方式呈现，于是有两种渲染后端可选：
 *
 *   - browser_source（默认，CEF/Chromium）：加载 /hud，富文本 + 注意力框，效果最好。
 *   - url_source（obs-urlsource 插件）：拉取 /hud.txt，纯文本叠层，兼容性更广。
 *
 * 本控制器只负责"在 OBS 场景里创建/更新/移除这个源"，真正的观察状态由
 * useGameStudio 的 observeOnce 循环算出后推给主进程 HUD 服务。
 *
 * 所有渲染都在 OBS 侧，AIJADE 不读游戏内存、不改游戏进程——纯感知可视化。
 */
export type OverlayKind = 'browser_source' | 'url_source'

export interface OverlayOptions {
  /** HUD 服务端口（主进程 startHud 返回） */
  port: number
  /** 渲染后端 */
  kind: OverlayKind
  /** 游戏画面来源名（叠层会盖在它上面） */
  gameSource?: string
  width?: number
  height?: number
  /** 叠层源名称，重复调用以同名复用 */
  name?: string
}

const DEFAULT_NAME = 'AIJADE 观察叠层'

export interface OverlayInfo {
  name: string
  scene: string
  kind: OverlayKind
}

export class ObsOverlayController {
  private readonly obs: ObsCapture

  constructor(obs: ObsCapture) {
    this.obs = obs
  }

  private async currentSceneName(): Promise<string> {
    try {
      const r: any = await this.obs.call('GetCurrentProgramScene')
      return r.currentProgramSceneName ?? r.currentScene ?? ''
    }
    catch {
      // 旧版 obs-websocket 用 GetCurrentScene
      const r: any = await this.obs.call('GetCurrentScene')
      return r.currentScene ?? ''
    }
  }

  private async sceneItemId(sceneName: string, sourceName: string): Promise<number | null> {
    try {
      const r: any = await this.obs.call('GetSceneItemId', { sceneName, sourceName })
      return typeof r.sceneItemId === 'number' ? r.sceneItemId : null
    }
    catch {
      return null
    }
  }

  /** 在 OBS 当前场景创建（或更新已存在的）观察叠层源。 */
  async ensureOverlay(opts: OverlayOptions): Promise<OverlayInfo> {
    const sceneName = await this.currentSceneName()
    const name = opts.name ?? DEFAULT_NAME
    const W = opts.width ?? 960
    const H = opts.height ?? 540
    const host = `127.0.0.1:${opts.port}`

    const settings
      = opts.kind === 'browser_source'
        ? {
            url: `http://${host}/hud`,
            width: W * 2,
            height: H * 2,
            fps: 30,
            reroute_audio: false,
            restart_when_active: true,
            css: 'body{background:transparent;margin:0;overflow:hidden;}',
          }
        : this.urlSourceSettings(opts.port)

    // 已存在则更新设置，避免重复创建
    const existingId = await this.sceneItemId(sceneName, name)
    if (existingId !== null) {
      await this.obs.call('SetInputSettings', { inputName: name, inputSettings: settings })
    }
    else {
      await this.obs.call('CreateInput', {
        sceneName,
        inputName: name,
        inputKind: opts.kind,
        inputSettings: settings,
        sceneItemEnabled: true,
      })
    }

    // 让叠层精确盖在游戏源之上（位置 + 缩放一致）
    if (opts.gameSource) {
      const gameId = await this.sceneItemId(sceneName, opts.gameSource)
      const overlayId = await this.sceneItemId(sceneName, name)
      if (gameId !== null && overlayId !== null) {
        try {
          const tr: any = await this.obs.call('GetSceneItemTransform', { sceneName, sceneItemId: gameId })
          const t = tr.sceneItemTransform ?? tr
          await this.obs.call('SetSceneItemTransform', {
            sceneName,
            sceneItemId: overlayId,
            sceneItemTransform: {
              positionX: t.positionX ?? 0,
              positionY: t.positionY ?? 0,
              scaleX: t.scaleX ?? 1,
              scaleY: t.scaleY ?? 1,
              rotation: t.rotation ?? 0,
              boundsType: t.boundsType ?? 'OBS_BOUNDS_NONE',
              boundsAlignment: t.boundsAlignment ?? 0,
              boundsWidth: t.boundsWidth ?? 0,
              boundsHeight: t.boundsHeight ?? 0,
            },
          })
        }
        catch {
          // 位置同步失败不致命，叠层仍会创建在原点
        }
      }
    }

    return { name, scene: sceneName, kind: opts.kind }
  }

  /** 移除叠层源。 */
  async removeOverlay(info: OverlayInfo): Promise<void> {
    try {
      await this.obs.call('RemoveInput', { inputName: info.name })
    }
    catch {
      // 源可能已被手动删除
    }
  }

  private urlSourceSettings(port: number): Record<string, unknown> {
    // 严格按 obs-urlsource 的 url_source_request_data 结构构造（nlohmann::json 反序列化）。
    // 拉取本地 HUD 纯文本端点，用 {{output}} 模板直接显示。
    const requestData = {
      source_name: '',
      url: `http://127.0.0.1:${port}/hud.txt`,
      url_or_file: 'url',
      method: 'GET',
      fail_on_http_error: false,
      body: '',
      inputs: {},
      sequence_number: 0,
      ssl_client_cert_file: '',
      ssl_client_key_file: '',
      ssl_client_key_pass: '',
      ssl_verify_peer: false,
      headers: [],
      output_type: 'text',
      output_json_path: '',
      output_json_pointer: '',
      output_xpath: '',
      output_xquery: '',
      output_regex: '',
      output_regex_flags: '',
      output_regex_group: '0',
      output_cssselector: '',
      post_process_regex: '',
      post_process_regex_is_replace: false,
      post_process_regex_replace: '',
      kv_delimiter: '=',
      ws_connected: false,
    }
    return {
      url: `http://127.0.0.1:${port}/hud.txt`,
      request_data: JSON.stringify(requestData),
      output_type: 'text',
      template: '{{output}}',
      update_timer: 1000,
      css_props: 'background-color: transparent; color: #9fe6ff; font-size: 28px; line-height: 1.4;',
      render_width: 640,
      is_image_url: false,
      run_while_not_visible: true,
      send_to_stream: false,
      text_sources: 'none',
    }
  }
}

/** 渲染端把观察状态推给主进程 HUD 服务（被 useGameStudio 的 observeOnce 调用）。 */
export function pushObservationToHud(state: ObservationState): void {
  window.electron.ipcRenderer.invoke('game-agent:hud:push', state).catch(() => {})
}
