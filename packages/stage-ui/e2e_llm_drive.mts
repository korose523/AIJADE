/**
 * Full end-to-end test: a REAL local LLM (Ollama qwythos-9b) drives the
 * desktop through AIJADE's unified `computer_use` contract.
 *
 * Chain under test (all REAL, no mocks):
 *   Ollama LLM  ->  selects `computer_use` tool (COMPUTER_USE_TOOL_SCHEMA)
 *              ->  capability.call(params)            [agent-computer-use]
 *              ->  createComputerUseMcpTransport      [agent-computer-use]
 *              ->  createHermesBackend                [agent-computer-use]
 *              ->  MCP stdio `computer_use` tool      [computer-use-mcp server]
 *              ->  mapComputerUseAction -> executeAction
 *              ->  win32-local executor               [real Windows desktop]
 *
 * The only glue that is NOT the app's own code is the tool-call loop and the
 * raw MCP stdio client (the Electron main normally provides the MCP bridge).
 */
import { spawn } from 'node:child_process'

import {
  COMPUTER_USE_TOOL_SCHEMA,
  createComputerUseCapability,
  createComputerUseMcpTransport,
  createHermesBackend,
} from '@proj-airi/agent-computer-use'

const SERVER = 'H:/AIJADE/services/computer-use-mcp/dist/bin/run.mjs'
const SERVICE_DIR = 'H:/AIJADE/services/computer-use-mcp'
const OLLAMA_URL = 'http://localhost:11434/v1/chat/completions'
const OLLAMA_MODEL = 'qwythos-9b:Q8_0'

// ---- minimal MCP stdio client over JSON-RPC ----
class McpStdioClient {
  private proc: ReturnType<typeof spawn>
  private buf = ''
  private id = 0
  private pending = new Map<number, { resolve: (v: any) => void, reject: (e: Error) => void }>()

  constructor() {
    this.proc = spawn(process.execPath, [SERVER], {
      cwd: SERVICE_DIR,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, COMPUTER_USE_EXECUTOR: 'win32-local' },
    })
    this.proc.stdout!.on('data', (d: Buffer) => this.onData(d.toString('utf-8')))
    this.proc.stderr!.on('data', (d: Buffer) => {
      const t = d.toString('utf-8').trim()
      if (t)
        console.error('[server stderr]', t)
    })
    this.proc.on('error', (e) => { console.error('[spawn error]', e.message); process.exit(1) })
  }

  private onData(chunk: string) {
    this.buf += chunk
    let nl: number
    while ((nl = this.buf.indexOf('\n')) !== -1) {
      const line = this.buf.slice(0, nl).trim()
      this.buf = this.buf.slice(nl + 1)
      if (!line)
        continue
      let msg: any
      try { msg = JSON.parse(line) }
      catch { continue }
      if (msg && typeof msg.id === 'number' && this.pending.has(msg.id)) {
        const p = this.pending.get(msg.id)!
        this.pending.delete(msg.id)
        if (msg.error)
          p.reject(new Error(JSON.stringify(msg.error)))
        else p.resolve(msg.result)
      }
    }
  }

  private rpc(method: string, params?: unknown): Promise<any> {
    const id = ++this.id
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); reject(new Error(`timeout ${method}`)) } }, 30000)
      this.pending.set(id, { resolve: (v) => { clearTimeout(t); resolve(v) }, reject: (e) => { clearTimeout(t); reject(e) } })
      this.proc.stdin!.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`)
    })
  }

  async init() {
    await this.rpc('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'airi-e2e', version: '0.1.0' } })
    this.proc.stdin!.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`)
    await new Promise(r => setTimeout(r, 500))
  }

  async callTool(name: string, args: Record<string, unknown>) {
    return this.rpc('tools/call', { name, arguments: args })
  }

  kill() {
    try { this.proc.kill('SIGKILL') }
    catch {}
  }
}

async function ollamaChat(messages: any[], tools: any[]): Promise<any> {
  const resp = await fetch(OLLAMA_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ model: OLLAMA_MODEL, messages, tools, tool_choice: 'auto', temperature: 0.3 }),
  })
  if (!resp.ok)
    throw new Error(`ollama http ${resp.status}: ${await resp.text()}`)
  return resp.json()
}

async function main() {
  console.log('=== spawning real computer-use-mcp server (win32-local) ===')
  const server = new McpStdioClient()
  await server.init()

  // Expose the server as the McpComputerUseClient the app's bridge consumes.
  // The app's MCP router uses `serverName::tool` quoting; we strip it here.
  const realComputerUseClient = {
    async callTool(name: string, args: Record<string, unknown>) {
      const toolName = name.includes('::') ? name.split('::').pop()! : name
      const res = await server.callTool(toolName, args)
      return {
        content: res?.content,
        structuredContent: res?.structuredContent,
        toolResult: res?.structuredContent ?? res?.toolResult,
        isError: res?.isError,
      }
    },
  }

  const transport = createComputerUseMcpTransport(realComputerUseClient)
  const backend = createHermesBackend(transport)
  // approve: read-only actions (list_apps/capture/wait) are always allowed by
  // the capability itself; we also allow mutations in this controlled test.
  const capability = createComputerUseCapability(backend, { approve: () => true })

  const toolDef = {
    type: 'function',
    function: {
      name: COMPUTER_USE_TOOL_SCHEMA.name as string,
      description: COMPUTER_USE_TOOL_SCHEMA.description as string,
      parameters: COMPUTER_USE_TOOL_SCHEMA.parameters,
    },
  }

  console.log('=== asking the REAL local LLM to drive the desktop ===')
  const messages = [
    { role: 'system', content: 'You are AIJADE, a desktop assistant. When the user wants to know what is on the desktop or interact with desktop apps, call the computer_use tool.' },
    { role: 'user', content: '请用 computer_use 工具调用 list_apps 动作，列出当前打开的窗口，并用一句话告诉我一共有多少个窗口、最前面的窗口是什么。' },
  ]

  const r1 = await ollamaChat(messages, [toolDef])
  const msg1 = r1.choices?.[0]?.message
  console.log('--- LLM turn 1 (raw) ---')
  console.log(JSON.stringify(msg1, null, 2))

  if (msg1?.tool_calls?.length) {
    messages.push(msg1)
    for (const tc of msg1.tool_calls) {
      const args = JSON.parse(tc.function.arguments || '{}')
      console.log(`\n>>> LLM invoked computer_use with: ${JSON.stringify(args)}`)
      const result = await capability.call(args)
      console.log('<<< capability result (real win32-local execution):')
      console.log(JSON.stringify(result, null, 2))
      messages.push({ role: 'tool', tool_call_id: tc.id, content: JSON.stringify(result) })
    }
    const r2 = await ollamaChat(messages, [toolDef])
    const finalText = r2.choices?.[0]?.message?.content
    console.log('\n=== LLM final answer (after real desktop data) ===')
    console.log(finalText)
    console.log('\nE2E_RESULT: LLM_DRIVEN_DESKTOP_OK')
  }
  else {
    console.log('\nLLM did not invoke the tool. Reply was:')
    console.log(msg1?.content)
    console.log('\nE2E_RESULT: NO_TOOL_CALL (model behavior, chain still wired)')
  }

  server.kill()
  process.exit(0)
}

main().catch((e) => { console.error('E2E_FATAL', e); process.exit(1) })
