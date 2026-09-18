import { authedFetch } from './auth-fetch'
import { SERVER_URL } from './server'

/**
 * P0-1 真实 ref 的渲染端来源。
 *
 * 服务端 `POST /api/v1/v9/persona/derive`（`apps/server/src/routes/v9/persona.ts`）
 * 从会话已提交的长期记忆证据派生**真实** `PerformanceIntent`（内部走
 * `@proj-aijade/growth-services` 的 `PerformanceDirector`，产物落库
 * `persona_snapshots` / `performance_intents` 表），并返回
 * `{ persona_snapshot_ref, intent_ref }`。本模块经 REST 把这份真实产物回读并按
 * session 缓存，供 `createPerformanceBridge` 的 `getPersonaSnapshotRef` /
 * `getIntentRef` 同步读取。
 *
 * 约束：
 * - **三层隔离**：`stage-ui` 全程不 import `growth-services` / 内核——真实 ref 是
 *   服务端产物经 HTTP 回读，不是本地合成（报告 §5.3 铁律）。
 * - **宁缺勿伪造**：派发失败（401/422/网络/空 ref）只打日志、不缓存；getter 返回
 *   `undefined`，bridge 层据此跳过 `persona.render_requested` 上报。
 * - **每会话至多一次**：服务端 `derive` 每调用一次就落一行新快照 + intent，因此按
 *   session 缓存 + singleflight，绝不在每次发送时重复派发。
 */
export const V9_PERSONA_DERIVE_ENDPOINT = `${SERVER_URL}/api/v1/v9/persona/derive`

export interface V9PersonaIntentRefs {
  personaSnapshotRef: string
  intentRef: string
}

export interface V9PersonaDeriveOptions {
  deviceId?: string
  agentId?: string
  userScope?: string
  privacyLevel?: 0 | 1 | 2 | 3
  /** 可注入的 fetch（测试用）；缺省走带 OIDC 401 刷新的 `authedFetch`。 */
  fetchImpl?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
}

const refsBySession = new Map<string, V9PersonaIntentRefs>()
const inFlight = new Map<string, Promise<void>>()

export function getPersonaSnapshotRefFor(sessionId: string | undefined): string | undefined {
  if (!sessionId)
    return undefined
  return refsBySession.get(sessionId)?.personaSnapshotRef
}

export function getIntentRefFor(sessionId: string | undefined): string | undefined {
  if (!sessionId)
    return undefined
  return refsBySession.get(sessionId)?.intentRef
}

/**
 * 为 `sessionId` 派发（并缓存）真实 persona/intent ref。fire-and-forget 语义：
 * 永不 reject，失败只日志——调用方 `void` 之即可。
 */
export function ensureV9PersonaIntent(sessionId: string, opts: V9PersonaDeriveOptions = {}): Promise<void> {
  if (refsBySession.has(sessionId))
    return Promise.resolve()
  const existing = inFlight.get(sessionId)
  if (existing)
    return existing

  const doFetch = opts.fetchImpl ?? authedFetch
  const task = (async () => {
    try {
      const res = await doFetch(V9_PERSONA_DERIVE_ENDPOINT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          device_id: opts.deviceId ?? 'browser',
          agent_id: opts.agentId ?? 'stage-ui',
          user_scope: opts.userScope ?? 'chat',
          privacy_level: opts.privacyLevel ?? 1,
        }),
      })
      if (!res.ok) {
        // 422 NO_EVIDENCE 是合法业务态（会话还没有可派生证据）——ref 保持缺失。
        console.warn(`[v9-persona-intent] derive rejected: session=${sessionId} status=${res.status}`)
        return
      }
      const body = (await res.json()) as { persona_snapshot_ref?: unknown, intent_ref?: unknown }
      const personaSnapshotRef = typeof body.persona_snapshot_ref === 'string' ? body.persona_snapshot_ref : ''
      const intentRef = typeof body.intent_ref === 'string' ? body.intent_ref : ''
      // 服务端返回空串 ⇒ 视为未产出，绝不缓存空 ref（宁缺勿伪造）。
      if (!personaSnapshotRef || !intentRef) {
        console.warn(`[v9-persona-intent] derive returned empty refs: session=${sessionId}`)
        return
      }
      refsBySession.set(sessionId, { personaSnapshotRef, intentRef })
    }
    catch (err) {
      console.warn(`[v9-persona-intent] derive failed: session=${sessionId}`, err)
    }
    finally {
      inFlight.delete(sessionId)
    }
  })()
  inFlight.set(sessionId, task)
  return task
}
