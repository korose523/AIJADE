import { useElectronEventaInvoke } from '@proj-aijade/electron-vueuse'
import { useLlmToolsStore } from '@proj-aijade/stage-ui/stores/llm-tools'
import { setMcpToolBridge } from '@proj-aijade/stage-ui/stores/mcp-tool-bridge'
import { createMcpTools } from '@proj-aijade/stage-ui/tools/mcp'
import { defineStore } from 'pinia'

import { electronMcpCallTool, electronMcpListTools } from '../../shared/eventa'

/**
 * Registers Electron-backed MCP tools into the shared LLM tools store.
 *
 * Use when:
 * - The Tamagotchi renderer needs live MCP tools during chat streaming
 *
 * Expects:
 * - Electron Eventa handlers for MCP listing and invocation are available
 *
 * Returns:
 * - Store actions for refreshing and disposing MCP runtime tools
 */
export const useTamagotchiMcpToolsStore = defineStore('tamagotchi-mcp-tools', () => {
  const llmToolsStore = useLlmToolsStore()
  const listMcpTools = useElectronEventaInvoke(electronMcpListTools)
  const callMcpTool = useElectronEventaInvoke(electronMcpCallTool)

  async function refresh() {
    // Feed the real computer-control bridge that `chat.ts` (stage-ui) consumes
    // through the Hermes-fused `computer_use` capability. Without this, the
    // capability falls back to a safe dry-run; with it, the LLM-driven
    // `computer_use` tool talks to AIJADE's `computer-use-mcp` server.
    setMcpToolBridge({
      listTools: () => listMcpTools(),
      callTool: payload => callMcpTool(payload),
    })

    return llmToolsStore.registerTools('mcp', Promise.all(createMcpTools({
      listTools: () => listMcpTools(),
      callTool: payload => callMcpTool(payload),
    })))
  }

  function dispose() {
    llmToolsStore.clearTools('mcp')
  }

  return {
    dispose,
    refresh,
  }
})
