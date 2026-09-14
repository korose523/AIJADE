/**
 * Xiaomi Mi Cloud API Client for AIJADE
 */
import { ofetch } from 'ofetch'

export interface XiaomiConfig {
  username: string
  password: string
  region?: string
}

export interface XiaomiDevice {
  did: string
  name: string
  model: string
  type: string
  isOnline: boolean
  token: string
  localip?: string
  mac?: string
}

const REGION_URLS: Record<string, string> = {
  cn: 'https://api.io.mi.com/app',
  sg: 'https://api.sgp.io.mi.com/app',
  de: 'https://api.de.io.mi.com/app',
  us: 'https://api.us.io.mi.com/app',
  ru: 'https://api.ru.io.mi.com/app',
  tw: 'https://api.tw.io.mi.com/app',
  in: 'https://api.in.io.mi.com/app',
}

export class XiaomiClient {
  private config: XiaomiConfig
  private auth: any = null
  private devices: Map<string, XiaomiDevice> = new Map()
  private baseUrl: string

  constructor(config: XiaomiConfig) {
    this.config = { region: 'cn', ...config }
    this.baseUrl = REGION_URLS[this.config.region || 'cn'] || REGION_URLS.cn
  }

  private getCookie(): string {
    return `userId=${this.auth?.userId || ''}; serviceToken=${this.auth?.serviceToken || ''}; locale=${this.auth?.locale || 'zh_CN'}`
  }

  async login(): Promise<any> {
    const loginUrl = 'https://account.xiaomi.com/pass/serviceLogin?sid=xiaomiio&_json=true'
    const signResp = await ofetch(loginUrl)
    const sign = (signResp as any)?._sign || ''
    const authResp = await ofetch('https://account.xiaomi.com/pass/serviceLoginAuth2', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        user: this.config.username,
        hash: '',
        sid: 'xiaomiio',
        callback: 'https://sts.api.io.mi.com/sts',
        qs: '%3Fsid%3Dxiaomiio',
        _sign: sign,
        _json: 'true',
      }).toString(),
    })
    const authData = authResp as any
    if (authData.code !== 0)
      throw new Error(`Xiaomi login failed: ${authData.desc || 'unknown'}`)
    this.auth = { userId: authData.userId, ssecurity: authData.ssecurity, serviceToken: authData.cid || '', locale: authData.locale || 'zh_CN' }
    const tokenResp = await ofetch(authData.location, { headers: { Cookie: this.getCookie() } })
    if (tokenResp && (tokenResp as any).token)
      this.auth.serviceToken = (tokenResp as any).token
    return this.auth
  }

  async getDevices(): Promise<XiaomiDevice[]> {
    if (!this.auth)
      await this.login()
    const resp = await ofetch(`${this.baseUrl}/home/device_list`, {
      headers: { Cookie: this.getCookie() },
      params: { data: JSON.stringify({}) },
    })
    const data = resp as any
    if (data.code !== 0)
      throw new Error(`Failed: ${data.message || 'unknown'}`)
    const devices: XiaomiDevice[] = (data.result?.list || []).map((d: any) => ({
      did: d.did,
      name: d.name,
      model: d.model,
      type: this.getDeviceType(d.model),
      isOnline: d.isOnline ?? true,
      token: d.token || '',
      localip: d.localip,
      mac: d.mac,
    }))
    for (const d of devices) this.devices.set(d.did, d)
    return devices
  }

  async getDeviceStatus(did: string) {
    if (!this.auth)
      await this.login()
    const resp = await ofetch(`${this.baseUrl}/device/get_prop`, {
      headers: { Cookie: this.getCookie() },
      params: { data: JSON.stringify({ did }) },
    })
    return (resp as any).result || resp
  }

  async sendCommand(did: string, method: string, params: any[] = []) {
    if (!this.auth)
      await this.login()
    return ofetch(`${this.baseUrl}/home/rpc/${did}`, {
      method: 'POST',
      headers: { 'Cookie': this.getCookie(), 'Content-Type': 'application/json' },
      body: { method, params, id: Date.now() },
    })
  }

  async toggleDevice(did: string, on: boolean) { return this.sendCommand(did, 'set_power', [on ? 'on' : 'off']) }
  async setBrightness(did: string, b: number) { return this.sendCommand(did, 'set_bright', [Math.max(1, Math.min(100, b))]) }
  async setColorTemperature(did: string, t: number) { return this.sendCommand(did, 'set_ct_abx', [Math.max(2700, Math.min(6500, t))]) }
  async setColor(did: string, r: number, g: number, b: number) { return this.sendCommand(did, 'set_rgb', [(r << 16) | (g << 8) | b]) }

  private getDeviceType(model: string): string {
    for (const [k, t] of Object.entries({ gateway: 'gateway', plug: 'outlet', light: 'light', sensor_ht: 'sensor', sensor_motion: 'sensor', sensor_magnet: 'sensor', curtain: 'curtain', airpurifier: 'airpurifier', vacuum: 'vacuum', camera: 'camera', lock: 'lock', switch: 'switch' })) {
      if (model.includes(k))
        return t
    }
    return 'unknown'
  }
}
