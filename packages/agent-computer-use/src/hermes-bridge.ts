import type { ComputerUseBackend } from './backend'
import type { ComputerUseAction, ComputerUseParams, ComputerUseResult } from './schema'

/**
 * Fusion seam with Hermes Agent's computer-control backend.
 *
 * Hermes Agent (Nous Research) drives the desktop through a `computer_use`
 * tool backed by the cua-driver (trycua/cua) over MCP stdio — on Windows via
 * `SendInput` + Windows UI Automation. AIJADE already ships a cross-platform
 * `services/computer-use-mcp`; this module lets that capability (or Hermes's
 * own cua backend) be addressed through AIJADE's unified `computer_use` contract.
 *
 * The actual process spawn / stdio MCP transport lives in the integration
 * layer (stage-ui or the runtime host), which has Node APIs. This module only
 * defines the transport contract and payload shape so the two can be wired
 * without coupling the capability package to `node:child_process`.
 */
import { SAFE_ACTIONS } from './schema'

/** Talks to an external computer-use backend (Hermes cua over MCP, AIJADE computer-use-mcp, …). */
export interface ComputerUseTransport {
  request: (action: ComputerUseAction, params: ComputerUseParams) => Promise<ComputerUseResult>
}

/**
 * Minimal MCP client the integration layer provides so `agent-computer-use`
 * can stay decoupled from `node:child_process` / the MCP SDK. The Electron main
 * populates this from its `McpStdioManager` (which spawns AIJADE's
 * `computer-use-mcp` server); tests provide a stub.
 */
export interface McpComputerUseClient {
  callTool: (name: string, args: Record<string, unknown>) => Promise<{
    content?: Array<Record<string, unknown>>
    structuredContent?: Record<string, unknown>
    toolResult?: unknown
    isError?: boolean
  }>
}

/** Map an MCP `callTool` result into AIJADE's {@link ComputerUseResult}. */
function mapMcpResult(
  action: ComputerUseAction,
  raw: Awaited<ReturnType<McpComputerUseClient['callTool']>>,
): ComputerUseResult {
  const safe = SAFE_ACTIONS.has(action)
  let summary = ''
  if (raw.structuredContent && Object.keys(raw.structuredContent).length > 0) {
    summary = JSON.stringify(raw.structuredContent)
  }
  else if (raw.toolResult !== undefined) {
    summary = typeof raw.toolResult === 'string' ? raw.toolResult : JSON.stringify(raw.toolResult)
  }
  else if (Array.isArray(raw.content)) {
    summary = raw.content
      .map((c) => {
        if (typeof c === 'string')
          return c
        if (c && typeof c === 'object' && 'text' in c)
          return String((c as { text?: unknown }).text ?? '')
        return JSON.stringify(c)
      })
      .join('\n')
  }
  return {
    ok: !raw.isError,
    safe,
    summary: summary || (raw.isError ? 'computer-use backend returned an error' : `${action} ok`),
    data: raw.structuredContent ?? raw.toolResult,
  }
}

/**
 * Build a {@link ComputerUseTransport} that delegates to AIJADE's real
 * `computer-use-mcp` server via the provided MCP client. The server is
 * registered under `serverName` in `mcp.json` (default `computer_use`), and the
 * desktop-driving tool is `computer_use` — so the qualified MCP tool name is
 * `${serverName}::computer_use`.
 */
export function createComputerUseMcpTransport(
  client: McpComputerUseClient,
  serverName = 'computer_use',
): ComputerUseTransport {
  return {
    async request(action, params) {
      const raw = await client.callTool(`${serverName}::computer_use`, params as unknown as Record<string, unknown>)
      return mapMcpResult(action, raw)
    },
  }
}

/**
 * Build the MCP `tools/call` payload for Hermes's `computer_use` tool. The
 * integration layer forwards this to the Hermes cua-driver stdio process.
 */
export function buildHermesMcpCall(params: ComputerUseParams): {
  method: 'tools/call'
  params: { name: 'computer_use', arguments: ComputerUseParams }
} {
  return { method: 'tools/call', params: { name: 'computer_use', arguments: params } }
}

/** Wrap an external transport as an AIJADE {@link ComputerUseBackend}. */
export function createHermesBackend(transport: ComputerUseTransport): ComputerUseBackend {
  return {
    async execute(params: ComputerUseParams): Promise<ComputerUseResult> {
      try {
        return await transport.request(params.action, params)
      }
      catch (err) {
        return {
          ok: false,
          safe: SAFE_ACTIONS.has(params.action),
          summary: `hermes backend error: ${(err as Error).message}`,
        }
      }
    },
  }
}
