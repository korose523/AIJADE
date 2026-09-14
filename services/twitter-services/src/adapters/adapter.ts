import type { Config } from '../config/types'
import type { Context } from '../core/browser/context'
import type { AijadeAdapter } from './aijade-adapter'
import type { MCPAdapter } from './mcp-adapter'

import { logger } from '../utils/logger'

export function useAdapter() {
  const adapters: { aijade?: AijadeAdapter, mcp?: MCPAdapter } = {}

  async function initAdapters(config: Config, ctx: Context): Promise<{ aijade?: AijadeAdapter, mcp?: MCPAdapter }> {
    if (config.adapters.aijade?.enabled) {
      logger.main.log('Starting Aijade adapter...')
      const { AijadeAdapter } = await import('./aijade-adapter')

      adapters.aijade = new AijadeAdapter(ctx, {
        url: config.adapters.aijade.url,
        token: config.adapters.aijade.token,
        credentials: config.credentials || {},
      })

      await adapters.aijade.start()
      logger.main.log('Aijade adapter started')
    }

    if (config.adapters.mcp?.enabled) {
      logger.main.log('Starting MCP adapter...')
      const { MCPAdapter } = await import('./mcp-adapter')

      adapters.mcp = new MCPAdapter(config.adapters.mcp.port, ctx)

      await adapters.mcp.start()
      logger.main.log('MCP adapter started')
    }

    return adapters
  }

  return {
    adapters,
    initAdapters,
  }
}
