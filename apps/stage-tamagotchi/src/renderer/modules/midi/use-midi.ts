import type { MidiDeviceInfo, MidiNoteEvent, MidiSource } from './midi-bridge'

/**
 * useMidi —— AIJADE 桌宠的蓝牙 MIDI 电钢琴 composable。
 *
 * 包装 midiBridge（Web MIDI + Web Bluetooth），对外暴露响应式设备列表 / 连接状态 / 最近音符，
 * 并提供：扫描、连接、演奏示例曲（小星星）、静音。
 *
 * 内置 Web Audio 双振荡器 + ADSR 合成，作为**无硬件时的兜底发声**——
 * 这样即使没连电钢琴，点「演奏示例曲」也能立刻听到声音；连上真实电钢琴时则同时发往硬件。
 *
 * 状态为模块级单例（在 pet 窗口内跨页面导航保持），首次调用 useMidi() 即共享同一份。
 */
import { ref } from 'vue'

import { midiBridge } from './midi-bridge'

export interface MidiNoteView {
  pitch: number
  velocity: number
  on: boolean
  ts: number
  name: string
}

const devices = ref<MidiDeviceInfo[]>([])
const connected = ref(false)
const activeDevice = ref<MidiDeviceInfo | null>(null)
const status = ref('')
const lastNotes = ref<MidiNoteView[]>([])
const playing = ref(false)
const currentNote = ref<MidiNoteView | null>(null)

let noteUnsub: (() => void) | null = null
let timers: ReturnType<typeof setTimeout>[] = []

// ---------------------------------------------------------------------------
// Web Audio 合成兜底
// ---------------------------------------------------------------------------
let audioCtx: AudioContext | null = null

function getAudioCtx(): AudioContext | null {
  if (typeof window === 'undefined')
    return null
  const Ctor = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor)
    return null
  if (!audioCtx) {
    try {
      audioCtx = new Ctor()
    }
    catch {
      return null
    }
  }
  return audioCtx
}

function midiToFreq(pitch: number): number {
  return 440 * 2 ** ((pitch - 69) / 12)
}

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

export function noteName(pitch: number): string {
  const name = NOTE_NAMES[((pitch % 12) + 12) % 12]
  const octave = Math.floor(pitch / 12) - 1
  return `${name}${octave}`
}

/** 用双振荡器 + ADSR 模拟钢琴音；durationMs 内淡出。 */
function synthTone(pitch: number, velocity: number, durationMs: number): void {
  const ctx = getAudioCtx()
  if (!ctx)
    return
  const now = ctx.currentTime
  const freq = midiToFreq(pitch)
  const vel = Math.max(0, Math.min(1, velocity / 127))

  const master = ctx.createGain()
  master.connect(ctx.destination)
  master.gain.setValueAtTime(0.0001, now)
  master.gain.exponentialRampToValueAtTime(0.22 * vel + 0.02, now + 0.008)
  master.gain.exponentialRampToValueAtTime(0.0001, now + durationMs / 1000)

  // 双振荡器：基频 + 八度泛音，钢琴感更厚
  const osc1 = ctx.createOscillator()
  osc1.type = 'triangle'
  osc1.frequency.value = freq
  const osc2 = ctx.createOscillator()
  osc2.type = 'sine'
  osc2.frequency.value = freq * 2

  const g2 = ctx.createGain()
  g2.gain.value = 0.35
  osc1.connect(master)
  osc2.connect(g2)
  g2.connect(master)

  osc1.start(now)
  osc2.start(now)
  const stopAt = now + durationMs / 1000 + 0.02
  osc1.stop(stopAt)
  osc2.stop(stopAt)
}

// ---------------------------------------------------------------------------
// 事件订阅（首次调用时建立，幂等）
// ---------------------------------------------------------------------------
function ensureSub(): void {
  if (noteUnsub)
    return
  noteUnsub = midiBridge.onNote((ev: MidiNoteEvent) => {
    const view: MidiNoteView = {
      pitch: ev.pitch,
      velocity: ev.velocity,
      on: ev.type === 'note_on',
      ts: ev.timestamp,
      name: noteName(ev.pitch),
    }
    lastNotes.value = [...lastNotes.value.slice(-11), view]
    if (view.on)
      currentNote.value = view
  })
  // 设备热插拔时刷新列表
  midiBridge.onDevicesChanged(() => void refresh())
}

function toView(d: MidiDeviceInfo): MidiDeviceInfo {
  return { ...d }
}

async function refresh(): Promise<void> {
  try {
    const list = await midiBridge.listDevices()
    devices.value = list.map(toView)
    // 同步连接状态
    if (activeDevice.value) {
      const still = list.find(d => d.id === activeDevice.value!.id && d.source === activeDevice.value!.source)
      connected.value = !!still && still.isConnected
      if (!still)
        activeDevice.value = null
    }
    else {
      connected.value = list.some(d => d.isConnected)
    }
  }
  catch (err) {
    console.warn('[useMidi] refresh failed:', err)
  }
}

// ---------------------------------------------------------------------------
// 对外动作
// ---------------------------------------------------------------------------
/** 扫描附近 BLE MIDI 设备（用户手势触发）。合并 Web MIDI 已配对设备后返回列表。 */
async function scan(): Promise<void> {
  status.value = '正在扫描蓝牙 MIDI 设备…'
  try {
    const list = await midiBridge.scanBluetooth()
    devices.value = list.map(toView)
    status.value = list.length
      ? `找到 ${list.length} 个 MIDI 设备`
      : '未找到设备。请确认电钢琴已开机并处于蓝牙配对/广播状态。'
  }
  catch (err) {
    status.value = `扫描出错：${(err as { message?: string })?.message ?? err}`
  }
}

/** 连接指定设备。 */
async function connect(device: MidiDeviceInfo): Promise<boolean> {
  status.value = `正在连接 ${device.name}…`
  try {
    const ok = await midiBridge.connect(device.id, device.name, device.source as MidiSource)
    if (ok) {
      activeDevice.value = device
      connected.value = true
      status.value = `已连接：${device.name}`
      await refresh()
      return true
    }
    status.value = '连接失败。'
    return false
  }
  catch (err) {
    status.value = `连接出错：${(err as { message?: string })?.message ?? err}`
    return false
  }
}

async function disconnect(): Promise<void> {
  await midiBridge.disconnect()
  connected.value = false
  activeDevice.value = null
  status.value = '已断开。'
  await refresh()
}

/** 静音：发往真实电钢琴的所有音符全部 note_off，并停止示例曲。 */
function panic(): void {
  stopDemo()
  midiBridge.panic()
  status.value = '已静音。'
}

// ---------------------------------------------------------------------------
// 示例曲：小星星（C 大调）
// ---------------------------------------------------------------------------
interface MelodyNote {
  pitch: number
  beats: number
}

const STAR_MELODY: MelodyNote[] = [
  { pitch: 60, beats: 1 },
  { pitch: 60, beats: 1 },
  { pitch: 67, beats: 1 },
  { pitch: 67, beats: 1 },
  { pitch: 69, beats: 1 },
  { pitch: 69, beats: 1 },
  { pitch: 67, beats: 2 },
  { pitch: 65, beats: 1 },
  { pitch: 65, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 62, beats: 1 },
  { pitch: 62, beats: 1 },
  { pitch: 60, beats: 2 },
  { pitch: 67, beats: 1 },
  { pitch: 67, beats: 1 },
  { pitch: 65, beats: 1 },
  { pitch: 65, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 62, beats: 2 },
  { pitch: 67, beats: 1 },
  { pitch: 67, beats: 1 },
  { pitch: 65, beats: 1 },
  { pitch: 65, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 62, beats: 2 },
  { pitch: 60, beats: 1 },
  { pitch: 60, beats: 1 },
  { pitch: 67, beats: 1 },
  { pitch: 67, beats: 1 },
  { pitch: 69, beats: 1 },
  { pitch: 69, beats: 1 },
  { pitch: 67, beats: 2 },
  { pitch: 65, beats: 1 },
  { pitch: 65, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 64, beats: 1 },
  { pitch: 62, beats: 1 },
  { pitch: 62, beats: 1 },
  { pitch: 60, beats: 2 },
]

const BEAT_MS = 420

/** 演奏示例曲：同时驱动真实电钢琴（sendNote）与 Web Audio 合成兜底。 */
async function playDemo(): Promise<void> {
  stopDemo()
  const ctx = getAudioCtx()
  if (ctx && ctx.state === 'suspended')
    await ctx.resume().catch(() => undefined)

  playing.value = true
  status.value = 'AIJADE 正在演奏《小星星》…'
  let t = 0
  for (const n of STAR_MELODY) {
    const dur = n.beats * BEAT_MS
    const at = t
    const vel = 96
    // note on
    timers.push(setTimeout(() => {
      currentNote.value = { pitch: n.pitch, velocity: vel, on: true, ts: Date.now(), name: noteName(n.pitch) }
      midiBridge.sendNote(n.pitch, vel, true)
      synthTone(n.pitch, vel, dur * 0.95)
    }, at))
    // note off
    timers.push(setTimeout(() => {
      midiBridge.sendNote(n.pitch, vel, false)
    }, at + dur * 0.9))
    t += dur
  }
  // 收尾
  timers.push(setTimeout(() => {
    playing.value = false
    status.value = connected.value ? '演奏完毕。' : '演奏完毕（合成器发声，未连接电钢琴）。'
  }, t + BEAT_MS))
}

function stopDemo(): void {
  for (const id of timers) clearTimeout(id)
  timers = []
  playing.value = false
}

export function useMidi() {
  ensureSub()
  return {
    // 状态
    devices,
    connected,
    activeDevice,
    status,
    lastNotes,
    playing,
    currentNote,
    // 动作
    scan,
    connect,
    disconnect,
    panic,
    playDemo,
    stopDemo,
    refresh,
    noteName,
  }
}
