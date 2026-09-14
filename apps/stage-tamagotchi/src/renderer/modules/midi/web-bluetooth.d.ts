/**
 * 最小 Web Bluetooth 类型声明。
 *
 * 本仓库锁定的 TypeScript / lib.dom 版本未自带 Web Bluetooth（Bluetooth / BluetoothDevice /
 * BluetoothRemoteGATT*）类型，而 midi-bridge.ts 直连 BLE MIDI 需要它们。
 * 这里只声明 MIDI 桥接实际用到的成员，避免引入 @types/web 等额外依赖。
 *
 * 此文件为全局脚本声明（无顶层 import/export），用于补充全局 Navigator 等接口。
 */

interface BluetoothRemoteGATTCharacteristic {
  value: DataView | ArrayBuffer | Uint8Array | null
  writeValue: (value: BufferSource) => Promise<void>
  startNotifications: () => Promise<void>
  addEventListener: ((type: 'characteristicvaluechanged', listener: (event: Event) => void) => void) & ((type: string, listener: (event: Event) => void) => void)
}

interface BluetoothRemoteGATTService {
  uuid: string
  getCharacteristic: (characteristic: string) => Promise<BluetoothRemoteGATTCharacteristic>
}

interface BluetoothRemoteGATTServer {
  connect: () => Promise<BluetoothRemoteGATTServer>
  disconnect: () => void
  getPrimaryService: (service: string) => Promise<BluetoothRemoteGATTService>
  getPrimaryServices: () => Promise<BluetoothRemoteGATTService[]>
}

interface BluetoothDevice {
  id: string
  name?: string
  gatt?: BluetoothRemoteGATTServer | null
  addEventListener: ((type: 'gattserverdisconnected', listener: () => void) => void) & ((type: string, listener: () => void) => void)
}

interface Bluetooth {
  requestDevice: (options: { acceptAllDevices?: boolean, optionalServices?: string[] }) => Promise<BluetoothDevice>
}

interface Navigator {
  bluetooth?: Bluetooth
}
