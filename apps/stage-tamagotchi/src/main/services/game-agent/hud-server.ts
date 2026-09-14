import type { IncomingMessage, ServerResponse } from 'node:http'

import { Buffer } from 'node:buffer'
import { createServer } from 'node:http'

import { ipcMain } from 'electron'

/**
 * 观察叠层 HUD 服务（主进程）。
 *
 * 参考 obs-urlsource 的核心思路——把一个"外部 URL/API"渲染进 OBS 场景——
 * 这里把 AIJADE 当下的"观察注意力"通过本地 HTTP 暴露出去，OBS 里就能用：
 *
 *   - 浏览器源（browser_source）加载 /hud          → 富文本 HUD（含注意力框、聚焦、旁白）
 *   - obs-urlsource 的 url_source 拉取 /hud.txt    → 纯文本叠层（兼容未装 CEF 源的环境）
 *
 * 这样 AIJADE 像人类主播一样"边看边说、还把目光画在画面上"，观众（和你）能直观看到
 * AIJADE 此刻在盯什么、打算干什么。所有渲染都在 OBS 侧，AIJADE 主逻辑零依赖。
 *
 * 注意：本服务仅做"感知可视化"，不读取任何游戏内存、不注入任何操作。
 */

export interface ObservationBox {
  label: string
  x: number
  y: number
  w: number
  h: number
  color?: string
}

export interface ObservationState {
  ts: number
  observing: boolean
  game: string
  source: string
  focus: string
  goal: string
  narration: string
  confidence: number
  fps: number
  boxes: ObservationBox[]
}

const EMPTY: ObservationState = {
  ts: 0,
  observing: false,
  game: '',
  source: '',
  focus: '',
  goal: '',
  narration: '',
  confidence: 0,
  fps: 0,
  boxes: [],
}

let server: ReturnType<typeof createServer> | null = null
let port = 0
let state: ObservationState = { ...EMPTY }

// ——— 富文本 HUD（浏览器源用）———
function hudHtml(): string {
  return `<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html,body{margin:0;height:100%;background:transparent;overflow:hidden;
    font-family:-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;color:#eaf6ff}
  #stage{position:relative;width:100%;height:100%}
  .box{position:absolute;border:2px solid #4dd0ff;border-radius:6px;
    box-shadow:0 0 12px rgba(77,208,255,.6);pointer-events:none}
  .box .tag{position:absolute;left:-2px;top:-20px;font-size:13px;line-height:18px;
    padding:0 6px;background:rgba(77,208,255,.85);color:#022;border-radius:4px;white-space:nowrap}
  #bar{position:absolute;left:0;right:0;bottom:0;padding:10px 14px;
    background:linear-gradient(transparent,rgba(4,10,20,.78));pointer-events:none}
  #bar .row{display:flex;align-items:baseline;gap:10px;margin-top:2px}
  #game{font-size:14px;font-weight:600;color:#9fe6ff;letter-spacing:.5px}
  #live{font-size:12px;color:#7CFFB2}
  #fps{margin-left:auto;font-size:12px;color:#cfe}
  #focus{font-size:20px;font-weight:700;color:#fff;text-shadow:0 1px 6px #000}
  #goal{font-size:14px;color:#ffd479}
  #say{font-size:14px;color:#bfe9ff;font-style:italic}
  #conf{font-size:11px;color:#9ab}
</style>
</head>
<body>
<div id="stage">
  <div id="boxes"></div>
  <div id="bar">
    <div class="row"><span id="game"></span><span id="live">● 观察中</span><span id="fps"></span></div>
    <div id="focus"></div>
    <div id="goal"></div>
    <div id="say"></div>
    <div id="conf"></div>
  </div>
</div>
<script>
const $ = id => document.getElementById(id);
function pct(v){ return (Math.max(0,Math.min(1,v))*100).toFixed(2)+'%'; }
async function tick(){
  try{
    const r = await fetch('/hud.json',{cache:'no-store'});
    const s = await r.json();
    const stage = $('stage');
    const W = stage.clientWidth, H = stage.clientHeight;
    const boxes = $('boxes');
    boxes.innerHTML='';
    (s.boxes||[]).forEach(b=>{
      const d=document.createElement('div');
      d.className='box';
      d.style.left=pct(b.x); d.style.top=pct(b.y);
      d.style.width=pct(b.w); d.style.height=pct(b.h);
      if(b.color) d.style.borderColor=b.color;
      const t=document.createElement('div');
      t.className='tag'; t.textContent=b.label;
      d.appendChild(t); boxes.appendChild(d);
    });
    $('game').textContent = s.game ? ('🎮 '+s.game) : '';
    $('live').textContent = s.observing ? '● 观察中' : '○ 待机';
    $('fps').textContent = s.fps ? (s.fps.toFixed(1)+' fps') : '';
    $('focus').textContent = s.focus || '';
    $('goal').textContent = s.goal ? ('意图：'+s.goal) : '';
    $('say').textContent = s.narration || '';
    $('conf').textContent = (typeof s.confidence==='number') ? ('置信度 '+(s.confidence*100).toFixed(0)+'%') : '';
  }catch(e){ /* 拉取失败静默等待下一轮 */ }
}
tick(); setInterval(tick, 800);
</script>
</body></html>`
}

// ——— 纯文本（obs-urlsource 的 url_source 用）———
function hudTxt(s: ObservationState): string {
  if (!s.observing)
    return `[AIJADE 观察] 待机中…`
  return [
    `[AIJADE 观察] 游戏：${s.game || '—'}`,
    `聚焦：${s.focus || '—'}`,
    `意图：${s.goal || '—'}`,
    `旁白：${s.narration || '—'}`,
    `置信度：${typeof s.confidence === 'number' ? `${Math.round(s.confidence * 100)}%` : '—'}`,
  ].join('\n')
}

function send(res: ServerResponse, body: string, type: string) {
  const buf = Buffer.from(body, 'utf8')
  res.writeHead(200, {
    'Content-Type': type,
    'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*',
  })
  res.end(buf)
}

function handle(req: IncomingMessage, res: ServerResponse) {
  const url = (req.url || '/').split('?')[0]
  if (url === '/hud' || url === '/')
    return send(res, hudHtml(), 'text/html; charset=utf-8')
  if (url === '/hud.json')
    return send(res, JSON.stringify(state), 'application/json; charset=utf-8')
  if (url === '/hud.txt')
    return send(res, hudTxt(state), 'text/plain; charset=utf-8')
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' })
  res.end('not found')
}

/** 注册 HUD 服务的 IPC 通道（在应用启动时调用一次）。 */
export function registerHudServer() {
  ipcMain.handle('game-agent:hud:start', () => {
    if (server)
      return port
    server = createServer(handle)
    return new Promise<number>((resolve) => {
      server!.listen(0, '127.0.0.1', () => {
        const addr = server!.address()
        if (addr && typeof addr === 'object')
          port = addr.port
        resolve(port)
      })
    })
  })

  ipcMain.handle('game-agent:hud:stop', () => {
    if (server) {
      server.close()
      server = null
    }
    port = 0
    state = { ...EMPTY }
  })

  // 渲染端把 AIJADE 的观察状态推过来，HUD 服务只是个状态容器，
  // 真正的渲染交给 OBS 里的浏览器源 / url_source 去轮询上面的 HTTP 端点。
  ipcMain.handle('game-agent:hud:push', (_e, s: ObservationState) => {
    state = s || { ...EMPTY }
  })

  ipcMain.handle('game-agent:hud:status', () => ({ running: !!server, port }))
}
