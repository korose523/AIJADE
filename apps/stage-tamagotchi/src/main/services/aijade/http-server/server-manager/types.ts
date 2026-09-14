/**
 * Shared lifecycle contract for AIJADE local HTTP sub-servers.
 *
 * Use when:
 * - Registering standalone local HTTP services under `services/aijade/http-server`
 * - Composing startup/shutdown order in the server manager
 *
 * Expects:
 * - `start` to be idempotent
 * - `stop` to be safe to call after partial startup
 *
 * Returns:
 * - Promise lifecycle completion for each server action
 */
export interface ServerManager {
  key: string
  start: () => Promise<void>
  stop: () => Promise<void>
}
