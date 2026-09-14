/**
 * 渲染进程 MIDI 桥接层（移植自 E:/Piano「泡泡钢琴」，为 AIJADE 桌宠裁剪）。
 *
 * 设计要点（针对「电钢琴使用蓝牙 MIDI 连接」）：
 * 1. **Web MIDI API**（`navigator.requestMIDIAccess`）：Chromium 在 Windows 10+ 上通过 WinRT MIDI、
 *    macOS 上通过 Core MIDI 枚举并连接**蓝牙 LE MIDI** 设备。适合「已在 Windows 系统蓝牙里配对过」的设备。
 * 2. **Web Bluetooth API**（`navigator.bluetooth.requestDevice`）：软件内部直接扫描并直连 BLE MIDI 设备，
 *    **无需在 Windows 系统蓝牙里预配对**。自己握 GATT 链路，把 BLE MIDI 包解析为音符（纯 JS，无原生模块）。
 *
 * 二者并存于同一个 MidiBridge 中：设备列表合并展示，连接/收发按来源路由到对应提供方。
 * 组件只面对 MidiBridge，不关心底层是 Web MIDI 还是 Web Bluetooth。
 *
 * 相比泡泡钢琴原版，本文件**去掉**了主进程 node-midi(IPC) 与 主进程 BLE 后端两个提供方——
 * AIJADE 主进程目前没有对应的 MIDI 后端，而 Web MIDI 在 Electron 渲染进程已原生支持 BLE MIDI，
 * 因此 Web MIDI + Web Bluetooth 双通道已足以覆盖「蓝牙 MIDI 链接电钢琴」。
 */

export type MidiSource = 'webmidi' | 'webbt'

export interface MidiDeviceInfo {
  id: string
  name: string
  manufacturer: string
  isConnected: boolean
  source: MidiSource
}

export interface MidiNoteEvent {
  type: 'note_on' | 'note_off'
  pitch: number
  velocity: number
  timestamp: number
  source: MidiSource
}

type NoteCb = (ev: MidiNoteEvent) => void
type DevicesCb = (devices: MidiDeviceInfo[]) => void

interface MidiProvider {
  readonly source: MidiSource
  init: () => Promise<void>
  listDevices: () => Promise<MidiDeviceInfo[]>
  connect: (id: string, name?: string) => Promise<boolean>
  disconnect: () => Promise<void>
  onNote: (cb: NoteCb) => () => void
  onDevicesChanged: (cb: DevicesCb) => () => void
  /** 向已连设备发送音符（自动演奏 / 伴奏）；无输出能力时 no-op */
  sendNote: (pitch: number, velocity: number, on: boolean) => void
  /** 点亮/熄灭电钢琴对应琴键指示灯（练习演示）；硬件灯依赖琴型 */
  lightNote: (pitch: number, on: boolean) => void
  /** 是否已连接输入设备 */
  isConnected: () => boolean
  /** 全部音符静音（防止电钢琴卡音） */
  panic: () => void
}

// BLE MIDI 服务与特征 UUID（Apple MIDI over BLE 标准）
const BLE_MIDI_SERVICE = '03b80e5a-ede8-4b33-a751-6ce34ec4c700'
const BLE_MIDI_CHAR = '7772e5db-3868-4112-a1a9-f2669d106bf3'

/** 解析标准 MIDI 字节流为音符事件；兼容 running status 与系统/实时消息。 */
export function parseMidiMessages(data: Uint8Array, ts: number): MidiNoteEvent[] {
  const out: MidiNoteEvent[] = []
  let running = 0
  let i = 0
  while (i < data.length) {
    let status = data[i]
    if (status < 0x80) {
      // 运行态：沿用上一条状态字节，当前字节为首个数据字节
      if (running === 0) {
        i++
        continue
      }
      status = running
    }
    else {
      running = status
      i++
    }
    const cmd = status & 0xF0
    if (cmd === 0x90 || cmd === 0x80) {
      const pitch = data[i] ?? 0
      const velocity = data[i + 1] ?? 0
      i += 2
      if (cmd === 0x90 && velocity > 0) {
        out.push({ type: 'note_on', pitch, velocity, timestamp: ts, source: 'webmidi' })
      }
      else {
        out.push({ type: 'note_off', pitch, velocity: 0, timestamp: ts, source: 'webmidi' })
      }
    }
    else if (cmd === 0xA0 || cmd === 0xB0 || cmd === 0xE0) {
      i += 2
    }
    else if (cmd === 0xC0 || cmd === 0xD0) {
      i += 1
    }
    else if (status === 0xF0 || status === 0xF7) {
      // System Exclusive：跳过直到 F7
      while (i < data.length && data[i] !== 0xF7) i++
      i++
    }
    else if (status >= 0xF8) {
      i++ // 实时消息：单字节
    }
    else {
      i++
    }
  }
  return out
}

/**
 * 解析 BLE MIDI 数据包（Apple MIDI over BLE 编码）为音符事件。
 *
 * 编码规则：数据包由若干「时间戳头 + MIDI 消息」组成。时间戳头高位置 1，1~2 字节共 13 位时间戳；
 * MIDI 消息与标准 MIDI 字节流一致（含 running status）。本解析器只抽取 note_on/note_off，
 * 其余消息（CC/Pitch/系统）跳过。
 */
function parseBleMidi(data: Uint8Array, ts: number): MidiNoteEvent[] {
  const out: MidiNoteEvent[] = []
  let running = 0
  let i = 0
  while (i < data.length) {
    // 时间戳头（高位置 1）：1~2 字节，跳过
    if (data[i] & 0x80) {
      i++ // 时间戳高位
      if (i < data.length && (data[i] & 0x80))
        i++ // 可选时间戳低位
    }
    if (i >= data.length)
      break
    let status = data[i]
    if (status & 0x80) {
      running = status
      i++
    }
    else {
      // running status：沿用上一条状态，当前字节即首个数据字节（不前进 i）
      if (running === 0) {
        i++
        continue
      }
      status = running
    }
    const cmd = status & 0xF0
    if (cmd === 0x90 || cmd === 0x80) {
      const pitch = data[i] ?? 0
      const velocity = data[i + 1] ?? 0
      i += 2
      if (cmd === 0x90 && velocity > 0) {
        out.push({ type: 'note_on', pitch, velocity, timestamp: ts, source: 'webbt' })
      }
      else {
        out.push({ type: 'note_off', pitch, velocity: 0, timestamp: ts, source: 'webbt' })
      }
    }
    else if (cmd === 0xA0 || cmd === 0xB0 || cmd === 0xE0) {
      i += 2
    }
    else if (cmd === 0xC0 || cmd === 0xD0) {
      i += 1
    }
    else if (status === 0xF0 || status === 0xF7) {
      while (i < data.length && data[i] !== 0xF7) i++
      if (i < data.length)
        i++
    }
    else if (status >= 0xF8) {
      i++
    }
    else {
      i++
    }
  }
  return out
}

/** Web Bluetooth characteristicvaluechanged 的 value 可能是 DataView / ArrayBuffer / Uint8Array。 */
function toBytes(value: DataView | ArrayBuffer | Uint8Array | null): Uint8Array | null {
  if (!value)
    return null
  if (value instanceof Uint8Array)
    return value
  if (value instanceof ArrayBuffer)
    return new Uint8Array(value)
  if (value instanceof DataView)
    return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
  const buf = (value as { buffer?: ArrayBuffer }).buffer
  return buf ? new Uint8Array(buf) : null
}

/** 构造并发送一个 BLE MIDI 包（1 字节时间戳头 + 状态 + 2 数据字节）。 */
function writeBle(char: BluetoothRemoteGATTCharacteristic, status: number, d1: number, d2: number): void {
  const pkt = new Uint8Array([0x80, status & 0xFF, d1 & 0x7F, d2 & 0x7F])
  char.writeValue(pkt).catch(() => undefined)
}

/** Web MIDI 提供方（渲染进程，原生支持蓝牙 LE MIDI，适合已系统配对的设备）。 */
class WebMidiProvider implements MidiProvider {
  readonly source = 'webmidi' as const
  private access: MIDIAccess | null = null
  private selectedId: string | null = null
  private output: MIDIOutput | null = null
  private noteCbs = new Set<NoteCb>()
  private devCbs = new Set<DevicesCb>()
  private handler: ((e: MIDIMessageEvent) => void) | null = null

  async init(): Promise<void> {
    if (typeof navigator === 'undefined' || typeof navigator.requestMIDIAccess !== 'function') {
      throw new TypeError('Web MIDI 不可用')
    }
    this.access = await navigator.requestMIDIAccess({ sysex: false })
    this.handler = (e: MIDIMessageEvent) => this.onMessage(e)
    this.access.onstatechange = () => this.onStateChange()
    this.attachAll()
  }

  /** 给所有输入端口挂载消息处理器（幂等：已挂过的跳过）。 */
  private attachAll(): void {
    if (!this.access || !this.handler)
      return
    this.access.inputs.forEach((input) => {
      if (!input.onmidimessage)
        input.onmidimessage = this.handler
    })
  }

  private onStateChange(): void {
    this.attachAll()
    const list = this.snapshot()
    this.devCbs.forEach(cb => cb(list))
  }

  private snapshot(): MidiDeviceInfo[] {
    if (!this.access)
      return []
    const list: MidiDeviceInfo[] = []
    this.access.inputs.forEach((input) => {
      list.push({
        id: input.id,
        name: input.name ?? 'MIDI 设备',
        manufacturer: input.manufacturer || 'Unknown',
        isConnected: input.id === this.selectedId,
        source: 'webmidi',
      })
    })
    return list
  }

  async listDevices(): Promise<MidiDeviceInfo[]> {
    await this.init()
    return this.snapshot()
  }

  /**
   * 连接指定设备。蓝牙 MIDI 端口本就一直「活」着，connect 只记录用户选中的设备
   * （用于自动演奏/按键灯的输出路由），不依赖「按 id 取到端口」这一瞬时状态，
   * 避免 Windows 重枚举时 id 变化导致的误判失败。
   */
  async connect(id: string, name?: string): Promise<boolean> {
    await this.init()
    if (!this.access)
      return false
    this.selectedId = id
    this.attachAll()
    this.output = this.findOutput(id, name)
    return true
  }

  private findOutput(id: string, name?: string): MIDIOutput | null {
    if (!this.access)
      return null
    if (id) {
      const byId = this.access.outputs.get(id)
      if (byId)
        return byId
    }
    if (name) {
      let found: MIDIOutput | null = null
      this.access.outputs.forEach((o) => {
        if (o.name === name)
          found = o
      })
      if (found)
        return found
    }
    return null
  }

  async disconnect(): Promise<void> {
    this.selectedId = null
    this.output = null
  }

  private onMessage(e: MIDIMessageEvent): void {
    const data = e.data
    if (!data || data.byteLength === 0)
      return
    const events = parseMidiMessages(data, Date.now())
    for (const ev of events) this.noteCbs.forEach(cb => cb(ev))
  }

  sendNote(pitch: number, velocity: number, on: boolean): void {
    if (!this.output)
      return
    const status = on ? 0x90 : 0x80
    this.output.send([status, pitch, on ? velocity : 0])
  }

  lightNote(pitch: number, on: boolean): void {
    if (!this.output)
      return
    this.output.send(on ? [0x90, pitch, 1] : [0x80, pitch, 0])
  }

  isConnected(): boolean {
    return this.selectedId != null
  }

  panic(): void {
    if (!this.output)
      return
    for (let p = 0; p < 128; p++) this.output.send([0x80, p, 0])
  }

  onNote(cb: NoteCb): () => void {
    this.noteCbs.add(cb)
    return () => this.noteCbs.delete(cb)
  }

  onDevicesChanged(cb: DevicesCb): () => void {
    this.devCbs.add(cb)
    return () => this.devCbs.delete(cb)
  }
}

interface BtDevice {
  device: BluetoothDevice
  char: BluetoothRemoteGATTCharacteristic
  name: string
  connected: boolean
}

/**
 * Web Bluetooth 提供方（渲染进程，软件内部直接扫描并直连 BLE MIDI 设备）。
 *
 * 与 Web MIDI 的区别：Web MIDI 走的是「系统已配对」的设备；本提供方用 navigator.bluetooth
 * 直接 requestDevice 扫描附近广播 MIDI 服务的 BLE 设备，自己握 GATT 链路并解析 BLE MIDI 包，
 * 因此**完全不需要在 Windows 系统蓝牙里预配对**。
 *
 * 注：浏览器要求 requestDevice 必须在「用户手势」中调用（点击按钮触发），且需在安全上下文
 * （Electron 的 file:// 或 localhost 均满足）。
 */
class WebBluetoothMidiProvider implements MidiProvider {
  readonly source = 'webbt' as const
  private devices = new Map<string, BtDevice>()
  private selectedId: string | null = null
  private noteCbs = new Set<NoteCb>()
  private devCbs = new Set<DevicesCb>()

  async init(): Promise<void> {
    if (typeof navigator === 'undefined' || !navigator.bluetooth) {
      throw new Error('Web Bluetooth 不可用')
    }
  }

  /**
   * 弹出系统设备选择器，扫描并直连一个 BLE MIDI 设备。
   *
   * 关键：用 `acceptAllDevices: true` 而非「按 MIDI 服务过滤」。很多电钢琴（尤其同时支持蓝牙音频的型号）
   * 只在 GATT 里暴露 MIDI 服务、**并不把它放进广播包**，按服务过滤会导致选择器里一个设备都看不到。
   * 改成「显示附近所有蓝牙设备」，PIANO MIDI 必然出现在列表里（它广播模式常开），用户按名字选中即可；
   * 连上后再在 GATT 里校验 MIDI 服务，选错设备会被明确报错拦下。
   */
  async addDevice(): Promise<MidiDeviceInfo | null> {
    const bluetooth = navigator.bluetooth
    if (!bluetooth)
      throw new Error('Web Bluetooth 不可用')
    let device: BluetoothDevice
    try {
      device = await bluetooth.requestDevice({
        acceptAllDevices: true,
        optionalServices: [BLE_MIDI_SERVICE],
      })
    }
    catch (err) {
      const e = err as { name?: string }
      if (e?.name === 'NotFoundError')
        return null // 用户取消或未选设备
      throw err
    }
    if (!device || !device.gatt)
      return null
    const char = await this.connectGatt(device)
    const id = device.id
    const name = device.name ?? '蓝牙 MIDI 设备'
    this.devices.set(id, { device, char, name, connected: true })
    this.selectedId = id
    device.addEventListener('gattserverdisconnected', () => {
      const d = this.devices.get(id)
      if (d)
        d.connected = false
      if (this.selectedId === id)
        this.selectedId = null
      void this.emitDevices()
    })
    await this.emitDevices()
    return { id, name, manufacturer: 'Bluetooth LE', isConnected: true, source: 'webbt' }
  }

  /**
   * 连接 GATT 并订阅 MIDI 特征。
   * - 失败时重试一次（蓝牙瞬断常见）。
   * - 连上后若设备里找不到 MIDI 服务，明确告诉用户「选错设备」。
   * - 若 Windows 已抢先配对该设备，GATT 连接会被系统拒绝，错误信息引导用户先在系统蓝牙里删除配对。
   */
  private async connectGatt(device: BluetoothDevice): Promise<BluetoothRemoteGATTCharacteristic> {
    let lastErr: unknown = null
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const server = await device.gatt!.connect()
        let service: BluetoothRemoteGATTService
        try {
          service = await server.getPrimaryService(BLE_MIDI_SERVICE)
        }
        catch {
          // 服务不在广播包里很常见；连上后枚举全部服务再确认
          const all = await server.getPrimaryServices().catch(() => [] as BluetoothRemoteGATTService[])
          const found = all.find(s => s.uuid.toLowerCase() === BLE_MIDI_SERVICE)
          if (!found) {
            throw new Error(
              `所选设备「${device.name ?? '未知'}」不是蓝牙 MIDI 设备（未发现 MIDI 服务）。`
              + `请重新在列表中选择名为「PIANO MIDI」的设备。`,
            )
          }
          service = found
        }
        const char = await service.getCharacteristic(BLE_MIDI_CHAR)
        await char.startNotifications()
        char.addEventListener('characteristicvaluechanged', (e: Event) => {
          const cd = e.target as unknown as BluetoothRemoteGATTCharacteristic
          const bytes = toBytes(cd.value)
          if (!bytes)
            return
          const events = parseBleMidi(bytes, Date.now())
          for (const ev of events) this.noteCbs.forEach(cb => cb(ev))
        })
        return char
      }
      catch (err) {
        lastErr = err
        const msg = String((err as { message?: string })?.message ?? err)
        console.error(`[webbt] GATT 连接失败（尝试 ${attempt + 1}）：`, err)
        if (msg.includes('不是蓝牙 MIDI 设备'))
          throw err // 选错设备：直接报错，不再重试
        await new Promise(r => setTimeout(r, 600))
      }
    }
    const msg = String((lastErr as { message?: string })?.message ?? lastErr)
    throw new Error(
      `蓝牙 GATT 连接失败：${msg
      }。若 Windows 蓝牙设置里已「配对」过该设备，请先「删除/忘记」，再回到软件重新扫描——`
      + `Windows 不允许同一 BLE 设备被系统和软件同时握连接。`,
    )
  }

  async listDevices(): Promise<MidiDeviceInfo[]> {
    const list: MidiDeviceInfo[] = []
    this.devices.forEach((d, id) => {
      list.push({ id, name: d.name, manufacturer: 'Bluetooth LE', isConnected: d.connected, source: 'webbt' })
    })
    return list
  }

  async connect(id: string, _name?: string): Promise<boolean> {
    const d = this.devices.get(id)
    if (!d)
      return false
    if (!d.connected) {
      const char = await this.connectGatt(d.device)
      if (!char)
        return false
      d.char = char
      d.connected = true
    }
    this.selectedId = id
    return true
  }

  async disconnect(): Promise<void> {
    if (this.selectedId) {
      const d = this.devices.get(this.selectedId)
      try {
        await d?.device.gatt?.disconnect()
      }
      catch {
        /* ignore */
      }
      if (d)
        d.connected = false
      this.selectedId = null
    }
  }

  private get selectedChar(): BluetoothRemoteGATTCharacteristic | null {
    if (!this.selectedId)
      return null
    return this.devices.get(this.selectedId)?.char ?? null
  }

  sendNote(pitch: number, velocity: number, on: boolean): void {
    const c = this.selectedChar
    if (!c)
      return
    writeBle(c, on ? 0x90 : 0x80, pitch, on ? velocity : 0)
  }

  lightNote(pitch: number, on: boolean): void {
    const c = this.selectedChar
    if (!c)
      return
    writeBle(c, on ? 0x90 : 0x80, pitch, on ? 1 : 0)
  }

  isConnected(): boolean {
    return this.selectedId != null
  }

  panic(): void {
    const c = this.selectedChar
    if (!c)
      return
    for (let p = 0; p < 128; p++) writeBle(c, 0x80, p, 0)
  }

  onNote(cb: NoteCb): () => void {
    this.noteCbs.add(cb)
    return () => this.noteCbs.delete(cb)
  }

  onDevicesChanged(cb: DevicesCb): () => void {
    this.devCbs.add(cb)
    return () => this.devCbs.delete(cb)
  }

  private async emitDevices(): Promise<void> {
    const list = await this.listDevices()
    this.devCbs.forEach(cb => cb(list))
  }
}

/**
 * 统一 MIDI 桥接单例（多提供方聚合）。
 *
 * 提供方优先级（全部常驻，扫描结果合并展示）：
 *   Web MIDI（原生 BLE MIDI，已系统配对）> Web Bluetooth（软件内直连，无需系统配对）
 */
class MidiBridge {
  private providers: MidiProvider[] = []
  private started = false
  private startQueue: Promise<void> | null = null
  private noteCbs = new Set<NoteCb>()
  private devCbs = new Set<DevicesCb>()
  private activeProvider: MidiProvider | null = null

  private async start(): Promise<void> {
    if (this.started)
      return
    if (this.startQueue)
      return this.startQueue
    this.startQueue = (async () => {
      const rendererProviders: MidiProvider[] = [
        new WebMidiProvider(),
        new WebBluetoothMidiProvider(),
      ]
      for (const p of rendererProviders) {
        try {
          await p.init()
        }
        catch {
          continue
        }
        this.providers.push(p)
        p.onNote(ev => this.noteCbs.forEach(cb => cb(ev)))
        p.onDevicesChanged(() => void this.emitDevices())
      }
      this.started = true
    })()
    return this.startQueue
  }

  get source(): MidiSource | null {
    return this.activeProvider?.source ?? null
  }

  private async emitDevices(): Promise<void> {
    const all = await this.mergeProviders()
    this.devCbs.forEach(cb => cb(all))
  }

  async listDevices(): Promise<MidiDeviceInfo[]> {
    await this.start()
    return this.mergeProviders()
  }

  /** 合并所有提供方当前能看到的设备；按名字去重（同一台琴可能经多通道可见，只列一次）。 */
  private async mergeProviders(): Promise<MidiDeviceInfo[]> {
    const all: MidiDeviceInfo[] = []
    for (const p of this.providers) {
      try {
        all.push(...(await p.listDevices()))
      }
      catch {
        /* ignore */
      }
    }
    const prio = (s?: string): number => s === 'webmidi' ? 2 : s === 'webbt' ? 1 : 0
    all.sort((a, b) => prio(b.source) - prio(a.source))
    const seen = new Set<string>()
    const out: MidiDeviceInfo[] = []
    for (const d of all) {
      const key = String(d.name)
      if (seen.has(key))
        continue
      seen.add(key)
      out.push(d)
    }
    return out
  }

  async connect(id: string, name?: string, source?: MidiSource): Promise<boolean> {
    await this.start()
    const provider = (source ? this.providers.find(p => p.source === source) : this.providers[0]) ?? null
    if (!provider)
      return false
    const ok = await provider.connect(id, name)
    if (ok) {
      this.activeProvider = provider
    }
    return ok
  }

  async disconnect(): Promise<void> {
    await this.start()
    if (this.activeProvider)
      await this.activeProvider.disconnect()
    this.activeProvider = null
    await this.emitDevices()
  }

  /**
   * 软件内部扫描 BLE MIDI 设备。
   *
   * 先在用户手势中触发 Web Bluetooth 扫描（直接直连，无需系统配对），
   * 再合并 Web MIDI 已枚举到的已配对设备，统一列出。
   * 必须在用户手势（点击按钮）中调用。
   */
  async scanBluetooth(): Promise<MidiDeviceInfo[]> {
    await this.start()
    const bt = this.providers.find(p => p.source === 'webbt') as WebBluetoothMidiProvider | undefined
    if (bt) {
      try {
        await bt.addDevice()
      }
      catch (err) {
        // 用户取消 / 不支持：忽略，仍可回退到 Web MIDI 已枚举设备
        console.warn('[midi] Web Bluetooth 扫描未产生设备：', err)
      }
    }
    const all = await this.mergeProviders()
    await this.emitDevices()
    return all
  }

  /** 向已连电钢琴发送音符（自动演奏）。未连接时安全 no-op。 */
  sendNote(pitch: number, velocity: number, on: boolean): void {
    if (this.activeProvider)
      this.activeProvider.sendNote(pitch, velocity, on)
  }

  /** 点亮/熄灭电钢琴按键灯（练习演示）。 */
  lightNote(pitch: number, on: boolean): void {
    if (this.activeProvider)
      this.activeProvider.lightNote(pitch, on)
  }

  /** 当前是否已连接输入设备（用于决定是否静音软件合成声）。 */
  isConnected(): boolean {
    return this.activeProvider?.isConnected() ?? false
  }

  /** 全部音符静音，防止退出练习时电钢琴卡住某个音。 */
  panic(): void {
    if (this.activeProvider)
      this.activeProvider.panic()
  }

  onNote(cb: NoteCb): () => void {
    this.noteCbs.add(cb)
    return () => this.noteCbs.delete(cb)
  }

  onDevicesChanged(cb: DevicesCb): () => void {
    this.devCbs.add(cb)
    return () => this.devCbs.delete(cb)
  }
}

export const midiBridge = new MidiBridge()
