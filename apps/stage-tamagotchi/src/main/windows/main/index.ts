import type { Rectangle } from 'electron'
import type { InferOutput } from 'valibot'

import type { I18n } from '../../libs/i18n'
import type { WindowAuthManager } from '../../services/aijade/auth'
import type { ServerChannel } from '../../services/aijade/channel-server'
import type { GodotStageManager } from '../../services/aijade/godot-stage'
import type { McpStdioManager } from '../../services/aijade/mcp-servers'
import type { AutoUpdater } from '../../services/electron/auto-updater'
import type { NoticeWindowManager } from '../notice'
import type { OnboardingWindowManager } from '../onboarding'
import type { SettingsWindowManager } from '../settings'
import type { WidgetsWindowManager } from '../widgets'

import { dirname, join, resolve } from 'node:path'
import { env } from 'node:process'
import { fileURLToPath } from 'node:url'

import clickDragPlugin from 'electron-click-drag-plugin'

import { is } from '@electron-toolkit/utils'
import { defineInvokeHandler } from '@moeru/eventa'
import { createContext } from '@moeru/eventa/adapters/electron/main'
import { initScreenCaptureForWindow } from '@proj-aijade/electron-screen-capture/main'
import { defu } from 'defu'
import { BrowserWindow, ipcMain, shell } from 'electron'
import { isLinux, isMacOS } from 'std-env'
import { array, number, object, optional, string } from 'valibot'

import icon from '../../../../resources/icon.png?asset'

import { electronStartDraggingWindow } from '../../../shared/eventa'
import { onAppBeforeQuit } from '../../libs/bootkit/lifecycle'
import { baseUrl, getElectronMainDirname, load } from '../../libs/electron/location'
import { createConfig } from '../../libs/electron/persistence'
import { registerHudServer } from '../../services/game-agent/hud-server'
import { registerInputRecorder } from '../../services/game-agent/input-recorder'
import { registerInputSafety } from '../../services/game-agent/input-safety'
import { registerKnowledgeStore } from '../../services/game-agent/knowledge-store'
import { registerNeuroServer } from '../../services/game-agent/neuro-server'
import { transparentWindowConfig } from '../shared'
import { setupMainWindowElectronInvokes } from './rpc/index.electron'

const appConfigSchema = object({
  windows: optional(array(object({
    title: optional(string()),
    tag: string(),
    x: optional(number()),
    y: optional(number()),
    width: optional(number()),
    height: optional(number()),
  }))),
})

type AppConfig = InferOutput<typeof appConfigSchema>

export async function setupMainWindow(params: {
  settingsWindow: SettingsWindowManager
  chatWindow: () => Promise<BrowserWindow>
  widgetsManager: WidgetsWindowManager
  noticeWindow: NoticeWindowManager
  autoUpdater: AutoUpdater
  onWindowCreated?: (window: BrowserWindow) => void
  serverChannel: ServerChannel
  godotStageManager: GodotStageManager
  mcpStdioManager: McpStdioManager
  i18n: I18n
  onboardingWindowManager: OnboardingWindowManager
  windowAuthManager: WindowAuthManager
}) {
  const {
    setup: setupConfig,
    get: getConfigRaw,
    update: updateConfig,
  } = createConfig('app', 'config.json', appConfigSchema, {
    default: { windows: [] },
    autoHeal: true,
  })
  const getConfig = (): AppConfig => getConfigRaw() ?? { windows: [] }

  setupConfig()

  const mainWindowConfig = getConfig().windows?.find(w => w.title === 'AIJADE' && w.tag === 'main')

  const window = new BrowserWindow({
    title: 'AIJADE',
    width: mainWindowConfig?.width ?? 450.0,
    height: mainWindowConfig?.height ?? 600.0,
    x: mainWindowConfig?.x,
    y: mainWindowConfig?.y,
    show: false,
    icon,
    webPreferences: {
      preload: join(dirname(fileURLToPath(import.meta.url)), '../preload/index.mjs'),
      sandbox: false,
    },
    // Thanks to [@HeartArmy](https://github.com/HeartArmy) for the tip implementation.
    //
    // https://github.com/electron/electron/issues/10078#issuecomment-3410164802
    // https://stackoverflow.com/questions/39835282/set-browserwindow-always-on-top-even-other-app-is-in-fullscreen-electron-mac
    type: 'panel',
    ...transparentWindowConfig(),
  })

  if (params.onWindowCreated) {
    params.onWindowCreated(window)
  }

  let allowClose = false
  onAppBeforeQuit(() => {
    allowClose = true
  })

  // NOTICE: in development mode, open devtools by default
  if (is.dev || env.MAIN_APP_DEBUG || env.APP_DEBUG) {
    try {
      window.webContents.openDevTools({ mode: 'detach' })
    }
    catch (err) {
      console.error('failed to open devtools:', err)
    }
  }

  function handleNewBounds(newBounds: Rectangle) {
    const config = getConfig()
    if (!config.windows || !Array.isArray(config.windows)) {
      config.windows = []
    }

    const existingConfigIndex = config.windows.findIndex(w => w.title === 'AIJADE' && w.tag === 'main')

    if (existingConfigIndex === -1) {
      config.windows.push({
        title: 'AIJADE',
        tag: 'main',
        x: newBounds.x,
        y: newBounds.y,
        width: newBounds.width,
        height: newBounds.height,
      })
    }
    else {
      const mainWindowConfig = defu(config.windows[existingConfigIndex], { title: 'AIJADE', tag: 'main' })

      mainWindowConfig.x = newBounds.x
      mainWindowConfig.y = newBounds.y
      mainWindowConfig.width = newBounds.width
      mainWindowConfig.height = newBounds.height

      config.windows[existingConfigIndex] = mainWindowConfig
    }

    updateConfig(config)
  }

  window.on('resize', () => handleNewBounds(window.getBounds()))
  window.on('move', () => handleNewBounds(window.getBounds()))
  window.on('close', (event) => {
    if (allowClose) {
      return
    }

    event.preventDefault()
    window.hide()
  })

  // Thanks to [@HeartArmy](https://github.com/HeartArmy) for the tip implementation.
  //
  // https://github.com/electron/electron/issues/10078#issuecomment-3410164802
  // https://stackoverflow.com/questions/39835282/set-browserwindow-always-on-top-even-other-app-is-in-fullscreen-electron-mac
  window.setAlwaysOnTop(true, 'screen-saver', 1)
  window.setFullScreenable(false)
  window.setVisibleOnAllWorkspaces(true)
  if (isMacOS) {
    window.setWindowButtonVisibility(false)
  }

  window.on('ready-to-show', () => window!.show())
  window.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url)
    return { action: 'deny' }
  })

  // 放行渲染进程的 Web MIDI（含蓝牙 LE MIDI）与 Web Bluetooth 权限。
  // Electron 不会自动允许 requestMIDIAccess / navigator.bluetooth，必须在主进程显式批准，
  // 否则「蓝牙 MIDI 链接电钢琴」在渲染进程会被静默拒绝。
  // 参考 E:/Piano（泡泡钢琴）的 window.ts 实现。
  const midiSession = window.webContents.session
  midiSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    // 注：当前 Electron 类型里的 Permission 联合未含 bluetooth / bluetoothLeScan，
    // 故按 string 比较；运行时 Electron 仍会把这些权限名传给回调并按 callback(true) 放行。
    const p = permission as string
    if (
      p === 'midi'
      || p === 'midiSysex'
      || p === 'bluetooth'
      || p === 'bluetoothLeScan'
    ) {
      callback(true)
    }
    else {
      callback(false)
    }
  })
  midiSession.setPermissionCheckHandler((_webContents, permission) => {
    const p = permission as string
    return (
      p === 'midi'
      || p === 'midiSysex'
      || p === 'bluetooth'
      || p === 'bluetoothLeScan'
    )
  })

  // 游戏 Agent 实操：输入注入统一经安全网（全局 F9 紧急停止 + 限速）。
  // 仅自主模式、由渲染进程显式调用时触发；默认不启用。
  registerInputSafety()

  // 真机学习：录制真人键鼠操作（渲染端点「开始录制」后才启动子进程）。
  registerInputRecorder()

  // 学习成果持久化：经验条目 + 学习素材。
  registerKnowledgeStore()

  // Neuro SDK 服务器（VedalAI 协议）：让 AIJADE 成为任何 neuro-sdk 游戏的 AI 大脑。
  // 仅在渲染进程面板「启动」后监听 localhost；默认不启用。
  registerNeuroServer()

  // 观察叠层 HUD 服务：把 AIJADE 的"观察/解说"推到本地 HTTP，供 OBS 作为"眼睛"渲染。
  registerHudServer()

  await setupMainWindowElectronInvokes({
    window,
    settingsWindow: params.settingsWindow,
    chatWindow: params.chatWindow,
    widgetsManager: params.widgetsManager,
    noticeWindow: params.noticeWindow,
    autoUpdater: params.autoUpdater,
    serverChannel: params.serverChannel,
    godotStageManager: params.godotStageManager,
    mcpStdioManager: params.mcpStdioManager,
    i18n: params.i18n,
    onboardingWindowManager: params.onboardingWindowManager,
    windowAuthManager: params.windowAuthManager,
  })

  await load(window, baseUrl(resolve(getElectronMainDirname(), '..', 'renderer')))

  /**
   * This is a know issue (or expected behavior maybe) to Electron.
   * We don't use this approach on Linux because it's not working.
   *
   * Discussion: https://github.com/electron/electron/issues/37789
   * Workaround: https://github.com/noobfromph/electron-click-drag-plugin
   */
  if (!isLinux) {
    function handleStartDraggingWindow() {
      try {
        const windowId = window.getNativeWindowHandle()
        clickDragPlugin.startDrag(windowId)
      }
      catch (error) {
        console.error(error)
      }
    }

    // TODO: once we refactored eventa to support window-namespaced contexts,
    // we can remove the setMaxListeners call below since eventa will be able to dispatch and
    // manage events within eventa's context system.
    ipcMain.setMaxListeners(0)

    const { context } = createContext(ipcMain, window)
    const cleanUpWindowDraggingInvokeHandler = defineInvokeHandler(context, electronStartDraggingWindow, handleStartDraggingWindow)

    window.on('closed', () => {
      cleanUpWindowDraggingInvokeHandler()
    })
  }

  initScreenCaptureForWindow(window)

  return window
}
