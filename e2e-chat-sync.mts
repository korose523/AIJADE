import WebSocket from 'ws'

import { defineInvoke, defineInvokeEventa, defineOutboundEventa } from '@moeru/eventa'
import { createContext } from '@moeru/eventa/adapters/websocket/native'

const SERVER = process.env.SERVER_URL || 'http://localhost:3000'
const TOKEN = process.argv[2] || process.env.AIJADE_TOKEN || ''

if (!TOKEN) {
  console.error('usage: tsx e2e-chat-sync.mts <session-token>')
  process.exit(1)
}

// Eventa invoke/outbound definitions — MUST match the string names used by
// @proj-aijade/server-sdk-shared (src/index.ts): chat:send-messages,
// chat:pull-messages, chat:new-messages.
const sendMessages = defineInvokeEventa('chat:send-messages')
const pullMessages = defineInvokeEventa('chat:pull-messages')
const newMessages = defineOutboundEventa('chat:new-messages')

// Bridge the node `ws` client to the browser-like WebSocket API that the
// eventa native adapter expects (onmessage/onopen/onclose/onerror + send).
function connect(url: string) {
  const ws = new WebSocket(url)
  let openResolve: () => void = () => {}
  let openReject: (e: any) => void = () => {}
  const opened = new Promise<void>((res, rej) => { openResolve = res; openReject = rej })
  const wrapper: any = { url, send: (d: any) => ws.send(d) }
  ws.on('message', (data: any) => {
    const str = typeof data === 'string' ? data : Buffer.from(data).toString('utf8')
    wrapper.onmessage && wrapper.onmessage({ data: str })
  })
  ws.on('open', () => { wrapper.onopen && wrapper.onopen({}); openResolve() })
  ws.on('close', (code: number, reason: any) => wrapper.onclose && wrapper.onclose({ code, reason: Buffer.from(reason).toString() }))
  ws.on('error', (e: any) => { wrapper.onerror && wrapper.onerror({ error: e }); openReject(e) })
  return { wrapper, opened }
}

function wsUrl(token: string) {
  const u = new URL(SERVER)
  u.protocol = u.protocol === 'https:' ? 'wss:' : 'ws:'
  u.pathname = `${u.pathname.replace(/\/+$/, '')}/ws/chat`
  u.searchParams.set('token', token)
  return u.toString()
}

async function main() {
  // 1) Resolve the authenticated user id from the session.
  const sessRes = await fetch(`${SERVER}/api/auth/get-session`, { headers: { Authorization: `Bearer ${TOKEN}` } })
  const sess = await sessRes.json()
  const userId: string | undefined = sess?.user?.id
  if (!userId) { console.error('get-session failed:', sessRes.status, JSON.stringify(sess)); process.exit(2) }
  console.log(`authenticated user: ${userId} (session ${sessRes.status})`)

  // 2) Create a chat (creator is auto-added as a member → will receive sync).
  const chatRes = await fetch(`${SERVER}/api/v1/chats`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${TOKEN}` },
    body: JSON.stringify({ type: 'private', title: 'AIJADE E2E sync test' }),
  })
  const chat = await chatRes.json()
  const chatId: string = chat.id
  if (!chatId) { console.error('createChat failed:', chatRes.status, JSON.stringify(chat)); process.exit(2) }
  console.log(`created chat: ${chatId} (http ${chatRes.status})`)

  // 3) Open TWO websocket connections for the SAME user (device A + device B).
  const a = connect(wsUrl(TOKEN))
  const b = connect(wsUrl(TOKEN))
  await Promise.all([a.opened, b.opened])
  console.log('both websockets open (A=device1, B=device2)')

  const ctxA = createContext(a.wrapper).context
  const ctxB = createContext(b.wrapper).context

  // 4) Device B subscribes to inbound newMessages pushes.
  // NOTE: eventa's `on()` handler receives an EVENT object whose real data is
  // in `.body` (the browser client does v.safeParse(..., event.body)).
  const received = new Promise<any>((resolve) => {
    ctxB.on(newMessages, (event: any) => {
      const body = event?.body
      console.log(`B received push: chatId=${body?.chatId} msgs=${body?.messages?.length}`)
      resolve(body)
    })
  })

  // 5) Device A sends a message via the sendMessages RPC.
  const invokeA = defineInvoke(() => ctxA, sendMessages)
  const msgId = globalThis.crypto.randomUUID()
  const content = `hello-from-A-${Date.now()}`
  const t0 = Date.now()
  const resp = await invokeA({ chatId, messages: [{ id: msgId, role: 'user', content }] })
  const sendMs = Date.now() - t0
  console.log(`A sendMessages → seq=${resp?.seq} (${sendMs}ms)`)

  // 6) Assert device B got the real-time push.
  let payload: any
  try {
    payload = await Promise.race([
      received,
      new Promise((_, rej) => setTimeout(() => rej(new Error('timeout: no push on B within 8s')), 8000)),
    ])
  }
  catch (e) {
    console.error(e.message)
    process.exit(1)
  }
  const recvMs = Date.now() - t0
  const ok = !!payload?.messages?.some((m: any) => m.content === content)
  console.log('\n================ RESULT ================')
  console.log(`push reached device B : ${!!payload}`)
  console.log(`content round-tripped : ${ok}`)
  console.log(`chatId on push        : ${payload?.chatId}`)
  console.log(`send→push latency      : ${recvMs}ms`)
  console.log(ok ? 'PASS ✅  typing→real-time-sync closed loop works' : 'FAIL ❌')
  process.exit(ok ? 0 : 1)
}

main().catch((e) => { console.error('ERROR', e); process.exit(2) })
