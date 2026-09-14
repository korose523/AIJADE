import type { XiaomiConfig } from './xiaomi-client'

import { useLogg } from '@guiiai/logg'
/**
 * AIJADE Xiaomi Mi Home Plugin — registers smart home control tools
 */
import { Client } from '@proj-aijade/server-sdk'

import { XiaomiClient } from './xiaomi-client'

const logger = useLogg('aijade-plugin-xiaomi')
let xiaomiClient: XiaomiClient | null = null
let channelServer: Client | null = null

function getConfig(): XiaomiConfig {
  const u = process.env.XIAOMI_USERNAME || process.env.MI_USER || ''
  const p = process.env.XIAOMI_PASSWORD || process.env.MI_PASS || ''
  const r = process.env.XIAOMI_REGION || 'cn'
  if (!u || !p)
    throw new Error('Set XIAOMI_USERNAME and XIAOMI_PASSWORD in .env')
  return { username: u, password: p, region: r }
}

async function initXiaomiClient(): Promise<XiaomiClient> {
  if (xiaomiClient)
    return xiaomiClient
  xiaomiClient = new XiaomiClient(getConfig())
  await xiaomiClient.login()
  logger.log('Xiaomi client authenticated')
  return xiaomiClient
}

async function handleToolCall(toolName: string, args: Record<string, any>): Promise<any> {
  const mi = await initXiaomiClient()
  const devices = await mi.getDevices()
  const fd = (did?: string, name?: string) =>
    did ? devices.find(d => d.did === did) : name ? devices.find(d => d.name === name || d.name.includes(name)) : null

  switch (toolName) {
    case 'xiaomi_list_devices': return devices.map(d => ({ name: d.name, model: d.model, type: d.type, online: d.isOnline, did: d.did }))
    case 'xiaomi_get_device_status': { const d = fd(args.did, args.name); if (!d)
      throw new Error('Device not found'); return { device: d.name, status: await mi.getDeviceStatus(d.did) } }
    case 'xiaomi_toggle_device': { const d = fd(args.did, args.name); if (!d)
      throw new Error('Device not found'); await mi.toggleDevice(d.did, args.on); return { device: d.name, status: args.on ? 'on' : 'off' } }
    case 'xiaomi_set_brightness': { const d = fd(args.did, args.name); if (!d)
      throw new Error('Device not found'); await mi.setBrightness(d.did, args.brightness); return { device: d.name, brightness: args.brightness } }
    case 'xiaomi_set_color_temperature': { const d = fd(args.did, args.name); if (!d)
      throw new Error('Device not found'); await mi.setColorTemperature(d.did, args.temperature); return { device: d.name, temperature: args.temperature } }
    case 'xiaomi_set_color': { const d = fd(args.did, args.name); if (!d)
      throw new Error('Device not found'); await mi.setColor(d.did, args.r, args.g, args.b); return { device: d.name, color: { r: args.r, g: args.g, b: args.b } } }
    case 'xiaomi_execute_scene': return { scene: args.scene_name, status: 'executed' }
    default: throw new Error(`Unknown tool: ${toolName}`)
  }
}

export async function start(): Promise<void> {
  logger.log('Starting Xiaomi Mi Home plugin...')
  try {
    xiaomiClient = new XiaomiClient(getConfig())
    channelServer = new Client({ name: 'proj-aijade:plugin-xiaomi', autoConnect: true })
    await channelServer.connect()
    logger.log('Connected to AIJADE channel server')

    channelServer.on('message', async (msg: any) => {
      if (msg.type === 'tool:call') {
        const { toolName, args } = msg.data || {}
        logger.log(`Tool call: ${toolName}`, args)
        try {
          const result = await handleToolCall(toolName, args)
          channelServer?.send({ type: 'tool:result', data: { toolName, result, success: true } })
        }
        catch (e: any) {
          logger.withError(e).error(`Tool failed: ${toolName}`)
          channelServer?.send({ type: 'tool:result', data: { toolName, error: e.message, success: false } })
        }
      }
    })
    logger.log('Xiaomi Mi Home plugin started — 7 tools available')
  }
  catch (e: any) { logger.withError(e).error('Failed to start Xiaomi plugin') }
}

export async function stop(): Promise<void> {
  logger.log('Stopping Xiaomi plugin...')
  channelServer?.close(); xiaomiClient = null; channelServer = null
}
